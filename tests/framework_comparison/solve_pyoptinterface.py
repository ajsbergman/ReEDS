"""
pyoptinterface implementation of the ReEDS-representative LP test problem.

All constraint and variable names mirror the GAMS originals in
reeds/core/setup/c_model.gms and reeds/core/setup/d_objective.gms.

Key pyoptinterface patterns used:
- Variables: m.add_variable(lb=0.0) returns a VariableIndex handle
- Constraints: m.add_linear_constraint(expr, poi.Eq/Leq/Geq, rhs)
- Expressions: arithmetic on VariableIndex objects + poi.quicksum()
- Objective: m.set_objective(expr, poi.ObjectiveSense.Minimize)
- Result: m.get_model_attribute(ModelAttribute.ObjectiveValue)

valcap sparsity is handled naturally: variables and constraints are
simply not created for inactive (i,r,t) combinations — equivalent to
GAMS $valcap dollar-conditionals.
"""

from __future__ import annotations
import time
import pyoptinterface as poi
from pyoptinterface import highs
from pyoptinterface._src.attributes import ModelAttribute, TerminationStatusCode

from data_generator import ProblemData


def solve(data: ProblemData, solver: str = "highs") -> tuple[float, float, float]:
    R, I, H, T = data.regions, data.techs, data.hours, data.years
    ri, ii, hi, ti = data.r_idx, data.i_idx, data.h_idx, data.t_idx

    # Pre-build neighbour lookups
    imports_from = {r: [] for r in R}
    exports_to   = {r: [] for r in R}
    for (r_from, r_to) in data.routes:
        imports_from[r_to].append(r_from)
        exports_to[r_from].append(r_to)

    # ------------------------------------------------------------------ build
    t0 = time.perf_counter()
    m = highs.Model()
    m.set_model_attribute(ModelAttribute.Silent, True)

    GEN  = {}
    CAP  = {}
    INV  = {}
    FLOW = {}

    # Variables — only created for active valcap(i,r,t) combinations
    for i in I:
        for r in R:
            for t in T:
                if data.valcap[ii[i], ri[r], ti[t]]:
                    CAP[(i, r, t)] = m.add_variable(lb=0.0)
                    INV[(i, r, t)] = m.add_variable(lb=0.0)
                    for h in H:
                        GEN[(i, r, h, t)] = m.add_variable(lb=0.0)

    for (r_from, r_to) in data.routes:
        for h in H:
            for t in T:
                FLOW[(r_from, r_to, h, t)] = m.add_variable(lb=0.0)

    # -- eq_cap_accum: CAP[i,r,t] - sum_{tt<=t} INV[i,r,tt] = cap_init[i,r]
    for i in I:
        for r in R:
            for t in T:
                if data.valcap[ii[i], ri[r], ti[t]]:
                    lhs = CAP[(i, r, t)] - poi.quicksum(
                        INV[(i, r, tt)] for tt in T
                        if tt <= t and data.valcap[ii[i], ri[r], ti[tt]]
                    )
                    m.add_linear_constraint(lhs, poi.Eq,
                                            data.cap_init[ii[i], ri[r]])

    # -- eq_cap_limit: GEN[i,r,h,t] - cf[i,h]*CAP[i,r,t] <= 0
    for i in I:
        for r in R:
            for t in T:
                if not data.valcap[ii[i], ri[r], ti[t]]:
                    continue
                cap_var = CAP[(i, r, t)]
                cf_row  = data.cf[ii[i], :]
                for h in H:
                    m.add_linear_constraint(
                        GEN[(i, r, h, t)] - cf_row[hi[h]] * cap_var,
                        poi.Leq, 0.0,
                    )

    # -- eq_mingen: GEN[i,r,h,t] >= minloadfrac[i] * CAP[i,r,t]
    for i in I:
        mf = data.minloadfrac[ii[i]]
        if mf <= 0:
            continue
        for r in R:
            for t in T:
                if not data.valcap[ii[i], ri[r], ti[t]]:
                    continue
                cap_var = CAP[(i, r, t)]
                for h in H:
                    m.add_linear_constraint(
                        GEN[(i, r, h, t)] - mf * cap_var,
                        poi.Geq, 0.0,
                    )

    # -- eq_supply_demand_balance
    for r in R:
        for h in H:
            for t in T:
                lhs = poi.quicksum(
                    GEN[(i, r, h, t)] for i in I
                    if data.valcap[ii[i], ri[r], ti[t]]
                )
                for rf in imports_from[r]:
                    lhs += (1 - data.tranloss) * FLOW[(rf, r, h, t)]
                for rt in exports_to[r]:
                    lhs -= FLOW[(r, rt, h, t)]
                m.add_linear_constraint(lhs, poi.Eq,
                                        data.load[ri[r], hi[h], ti[t]])

    # -- eq_reserve_margin
    for r in R:
        for t in T:
            peak = float(data.load[ri[r], :, ti[t]].max())
            lhs = poi.quicksum(
                CAP[(i, r, t)] for i in I
                if data.valcap[ii[i], ri[r], ti[t]]
            )
            m.add_linear_constraint(lhs, poi.Geq, (1 + data.prm) * peak)

    # -- eq_transmission_limit
    for (r_from, r_to) in data.routes:
        cap_val = data.transcap[(r_from, r_to)]
        for h in H:
            for t in T:
                m.add_linear_constraint(
                    FLOW[(r_from, r_to, h, t)], poi.Leq, cap_val,
                )

    # -- eq_emit_cap: sum_{i,r,h} emit_rate[i]*hw[h]*GEN <= emit_cap[t]
    for t in T:
        lhs = poi.quicksum(
            data.emit_rate[ii[i]] * data.hours_weight[hi[h]] * GEN[(i, r, h, t)]
            for i in I for r in R for h in H
            if data.valcap[ii[i], ri[r], ti[t]] and data.emit_rate[ii[i]] > 0
        )
        m.add_linear_constraint(lhs, poi.Leq, data.emit_cap[ti[t]])

    # -- Objective
    # Scale objective by 1/OBJ_SCALE to avoid dual simplex ratio errors at
    # large problem sizes when cost coefficients span [1, 5e6].  HiGHS 1.13
    # (bundled with pyoptinterface) is less robust to wide cost ranges than
    # HiGHS 1.14.  The final objective is multiplied back by OBJ_SCALE.
    OBJ_SCALE = 1e6
    obj = poi.ExprBuilder()
    for k, t in enumerate(T):
        pv = data.pvf[k]
        for i in I:
            cinv = data.cost_inv[ii[i]] / OBJ_SCALE
            cop  = data.cost_op[ii[i]]  / OBJ_SCALE
            for r in R:
                if not data.valcap[ii[i], ri[r], ti[t]]:
                    continue
                obj += pv * cinv * INV[(i, r, t)]
                hw   = data.hours_weight
                for h in H:
                    obj += pv * cop * hw[hi[h]] * GEN[(i, r, h, t)]
    m.set_objective(obj, poi.ObjectiveSense.Minimize)

    build_s = time.perf_counter() - t0

    # ------------------------------------------------------------------ solve
    t1 = time.perf_counter()
    m.optimize()
    solve_s = time.perf_counter() - t1

    status = m.get_model_attribute(ModelAttribute.TerminationStatus)
    if status != TerminationStatusCode.OPTIMAL:
        raise RuntimeError(f"HiGHS did not find an optimal solution: {status.name}")

    obj_val = m.get_model_attribute(ModelAttribute.ObjectiveValue)
    return float(obj_val * OBJ_SCALE), build_s, solve_s


if __name__ == "__main__":
    import sys
    sys.path.insert(0, __file__.rsplit("\\", 1)[0])
    from data_generator import make_problem
    for size in ("small", "medium", "large"):
        data = make_problem(size)
        obj, b, s = solve(data)
        print(f"{size:6s}  obj={obj:>18,.0f}  build={b:.3f}s  solve={s:.3f}s")
