"""
Pyomo implementation of the ReEDS-representative LP test problem.

All constraint and variable names mirror the GAMS originals in
reeds/core/setup/c_model.gms and reeds/core/setup/d_objective.gms.

Key pyomo patterns used:
- ConcreteModel with Set, Var, Constraint, Objective
- @m.Constraint decorator style — one rule per constraint family
- VALCAP / VGEN sparse sets filter to active (i,r,t) combinations,
  equivalent to GAMS $valcap dollar-conditionals
- active_i lookup precomputed per (r,t) to avoid inner-loop scanning
"""

from __future__ import annotations
import time
import pyomo.environ as pyo
from pyomo.opt import SolverFactory

from data_generator import ProblemData


def solve(data: ProblemData, solver: str = "highs") -> tuple[float, float, float]:
    R, I, H, T = data.regions, data.techs, data.hours, data.years
    ri, ii, hi, ti = data.r_idx, data.i_idx, data.h_idx, data.t_idx

    # Pre-build neighbour lookups for supply_demand
    imports_from = {r: [] for r in R}
    exports_to   = {r: [] for r in R}
    for (r_from, r_to) in data.routes:
        imports_from[r_to].append(r_from)
        exports_to[r_from].append(r_to)

    # Sparse index sets derived from valcap
    valcap_irt  = [(i, r, t) for i in I for r in R for t in T
                   if data.valcap[ii[i], ri[r], ti[t]]]
    valcap_irht = [(i, r, h, t) for (i, r, t) in valcap_irt for h in H]

    # Per-(r,t): list of active techs — avoids repeated inner-loop filtering
    active_i = {(r, t): [i for i in I if data.valcap[ii[i], ri[r], ti[t]]]
                for r in R for t in T}

    # Dispatchable (i,r,h,t) combos with a min-load constraint
    mingen_irht = [(i, r, h, t) for (i, r, t) in valcap_irt for h in H
                   if data.minloadfrac[ii[i]] > 0]

    # ------------------------------------------------------------------ build
    t0 = time.perf_counter()
    m = pyo.ConcreteModel()

    m.R      = pyo.Set(initialize=R)
    m.I      = pyo.Set(initialize=I)
    m.H      = pyo.Set(initialize=H)
    m.T      = pyo.Set(initialize=T)
    m.ROUTES = pyo.Set(initialize=data.routes, dimen=2)

    # Sparse sets replace full I×R×T / I×R×H×T cross-products
    m.VALCAP = pyo.Set(initialize=valcap_irt,  dimen=3)
    m.VGEN   = pyo.Set(initialize=valcap_irht, dimen=4)
    m.MINGEN = pyo.Set(initialize=mingen_irht, dimen=4)

    m.GEN  = pyo.Var(m.VGEN,   within=pyo.NonNegativeReals)
    m.CAP  = pyo.Var(m.VALCAP, within=pyo.NonNegativeReals)
    m.INV  = pyo.Var(m.VALCAP, within=pyo.NonNegativeReals)
    m.FLOW = pyo.Var(m.ROUTES, m.H, m.T, within=pyo.NonNegativeReals)

    # -- eq_cap_accum
    @m.Constraint(m.VALCAP)
    def eq_cap_accum(m, i, r, t):
        return m.CAP[i, r, t] == (
            data.cap_init[ii[i], ri[r]]
            + sum(m.INV[i, r, tt] for tt in T
                  if tt <= t and data.valcap[ii[i], ri[r], ti[tt]])
        )

    # -- eq_cap_limit
    @m.Constraint(m.VGEN)
    def eq_cap_limit(m, i, r, h, t):
        return m.GEN[i, r, h, t] <= data.cf[ii[i], hi[h]] * m.CAP[i, r, t]

    # -- eq_mingen: min dispatch fraction for dispatchable techs
    @m.Constraint(m.MINGEN)
    def eq_mingen(m, i, r, h, t):
        return m.GEN[i, r, h, t] >= data.minloadfrac[ii[i]] * m.CAP[i, r, t]

    # -- eq_supply_demand_balance
    @m.Constraint(m.R, m.H, m.T)
    def eq_supply_demand_balance(m, r, h, t):
        gen  = sum(m.GEN[i, r, h, t] for i in active_i[(r, t)])
        imp_ = sum((1 - data.tranloss) * m.FLOW[rf, r, h, t]
                   for rf in imports_from[r])
        exp_ = sum(m.FLOW[r, rt, h, t] for rt in exports_to[r])
        return gen + imp_ - exp_ == data.load[ri[r], hi[h], ti[t]]

    # -- eq_reserve_margin
    @m.Constraint(m.R, m.T)
    def eq_reserve_margin(m, r, t):
        peak = float(data.load[ri[r], :, ti[t]].max())
        return (sum(m.CAP[i, r, t] for i in active_i[(r, t)])
                >= (1 + data.prm) * peak)

    # -- eq_transmission_limit
    @m.Constraint(m.ROUTES, m.H, m.T)
    def eq_transmission_limit(m, r, rr, h, t):
        return m.FLOW[r, rr, h, t] <= data.transcap[(r, rr)]

    # -- eq_emit_cap: annual CO2 cap per year
    @m.Constraint(m.T)
    def eq_emit_cap(m, t):
        return (
            sum(data.emit_rate[ii[i]] * data.hours_weight[hi[h]] * m.GEN[i, r, h, t]
                for i in I for r in R for h in H
                if data.valcap[ii[i], ri[r], ti[t]] and data.emit_rate[ii[i]] > 0)
            <= data.emit_cap[ti[t]]
        )

    # -- Objective
    @m.Objective(sense=pyo.minimize)
    def obj(m):
        return sum(
            data.pvf[ti[t]] * (
                sum(data.cost_inv[ii[i]] * m.INV[i, r, t]
                    for i in I for r in R if data.valcap[ii[i], ri[r], ti[t]])
                + sum(data.cost_op[ii[i]] * data.hours_weight[hi[h]]
                      * m.GEN[i, r, h, t]
                      for i in I for r in R for h in H
                      if data.valcap[ii[i], ri[r], ti[t]])
            )
            for t in T
        )

    build_s = time.perf_counter() - t0

    # ------------------------------------------------------------------ solve
    t1 = time.perf_counter()
    slvr = SolverFactory(solver)
    slvr.solve(m, tee=False)
    solve_s = time.perf_counter() - t1

    return float(pyo.value(m.obj)), build_s, solve_s


if __name__ == "__main__":
    import sys
    sys.path.insert(0, __file__.rsplit("\\", 1)[0])
    from data_generator import make_problem
    for size in ("small", "medium", "large"):
        data = make_problem(size)
        obj, b, s = solve(data)
        print(f"{size:6s}  obj={obj:>18,.0f}  build={b:.3f}s  solve={s:.3f}s")
