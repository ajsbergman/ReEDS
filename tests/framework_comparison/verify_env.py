"""
Environment verification for framework comparison.

Solves the small test problem with each framework using HiGHS,
then cross-checks that all objective values agree within tolerance.

Run from the tests/framework_comparison directory:
    /c/envs/reeds2/python.exe verify_env.py

or from repo root:
    /c/envs/reeds2/python.exe tests/framework_comparison/verify_env.py
"""

from __future__ import annotations
import sys
import time
import importlib

# ---------------------------------------------------------------------------
# 1. Import check
# ---------------------------------------------------------------------------

REQUIRED = {
    "linopy":           "linopy",
    "pyomo":            "pyomo.environ",
    "pyoptinterface":   "pyoptinterface",
    "gamspy":           "gamspy",
    "highspy":          "highspy",
    "highsbox":         "highsbox",
    "numpy":            "numpy",
    "xarray":           "xarray",
}

print("=" * 60)
print("Import checks")
print("=" * 60)
ok = True
for label, module in REQUIRED.items():
    try:
        mod = importlib.import_module(module)
        ver = getattr(mod, "__version__", "?")
        print(f"  {label:<22} OK  ({ver})")
    except ImportError as exc:
        print(f"  {label:<22} FAIL  {exc}")
        ok = False

if not ok:
    sys.exit("One or more imports failed.")

print()

# ---------------------------------------------------------------------------
# 2. Shared test data
# ---------------------------------------------------------------------------

import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from data_generator import make_problem
import numpy as np
import xarray as xr

data = make_problem("small")
print(f"Problem: {data.summary()}")
print()

R, I, H, T = data.regions, data.techs, data.hours, data.years
ri, ii, hi, ti = data.r_idx, data.i_idx, data.h_idx, data.t_idx

# Precompute: net-flow incidence matrix [R x routes]
# flow_mat[r_to_idx, route_i] = +(1-loss),  flow_mat[r_from_idx, route_i] = -1
nR, nRoutes = len(R), len(data.routes)
flow_mat = np.zeros((nR, nRoutes))
for k, (r_from, r_to) in enumerate(data.routes):
    flow_mat[data.r_idx[r_to],   k] += (1 - data.tranloss)
    flow_mat[data.r_idx[r_from], k] -= 1.0

ATOL_REL = 1e-3

# ---------------------------------------------------------------------------
# 3. linopy
# ---------------------------------------------------------------------------

def solve_linopy() -> tuple[float, float, float]:
    import linopy
    xp = data.as_xarray()

    t0 = time.perf_counter()
    m = linopy.Model()

    GEN  = m.add_variables(lower=0,
                            coords=[("i",I), ("r",R), ("h",H), ("t",T)],
                            name="GEN")
    CAP  = m.add_variables(lower=0,
                            coords=[("i",I), ("r",R), ("t",T)],
                            name="CAP")
    INV  = m.add_variables(lower=0,
                            coords=[("i",I), ("r",R), ("t",T)],
                            name="INV")
    FLOW = m.add_variables(lower=0,
                            coords=[("route", list(range(nRoutes))), ("h",H), ("t",T)],
                            name="FLOW")

    # eq_cap_accum: CAP[i,r,t] = cap_init[i,r] + sum_{tt<=t} INV[i,r,tt]
    for k, yr in enumerate(T):
        past_inv = INV.sel(t=T[:k+1]).sum("t")   # LinearExpression [i, r]
        # Keep linopy expr on LHS so linopy handles the DataArray RHS
        m.add_constraints(
            CAP.sel(t=yr) - past_inv == xp["cap_init"],
            name=f"cap_accum_{yr}"
        )

    # eq_cap_limit: GEN[i,r,h,t] <= cf[i,h] * CAP[i,r,t]
    m.add_constraints(GEN <= xp["cf"] * CAP, name="cap_limit")

    # eq_supply_demand using incidence matrix [r x routes]
    flow_da = xr.DataArray(
        flow_mat,
        dims=["r", "route"],
        coords={"r": R, "route": list(range(nRoutes))}
    )
    net_import = (flow_da * FLOW).sum("route")   # [r, h, t]
    m.add_constraints(
        GEN.sum("i") + net_import == xp["load"],
        name="supply_demand"
    )

    # eq_reserve_margin: sum_i CAP[i,r,t] >= (1+prm) * peak_load[r,t]
    peak_load = xr.DataArray(
        data.load.max(axis=1),
        dims=["r","t"], coords={"r": R, "t": T}
    )
    m.add_constraints(
        CAP.sum("i") >= (1 + data.prm) * peak_load,
        name="reserve_margin"
    )

    # eq_trans_limit: FLOW[route,h,t] <= transcap[route]
    tcap = xr.DataArray(
        [data.transcap[rt] for rt in data.routes],
        dims=["route"], coords={"route": list(range(nRoutes))}
    )
    m.add_constraints(FLOW <= tcap, name="trans_limit")

    # Objective: sum_t pvf[t] * (inv_cost + op_cost)
    obj = (xp["pvf"] * xp["cost_inv"] * INV).sum() \
        + (xp["pvf"] * xp["cost_op"] * xp["hours_weight"] * GEN).sum()
    m.add_objective(obj)

    build_s = time.perf_counter() - t0

    t1 = time.perf_counter()
    m.solve("highs", io_api="direct", output_flag=False)
    solve_s = time.perf_counter() - t1

    return float(m.objective.value), build_s, solve_s


# ---------------------------------------------------------------------------
# 4. pyomo
# ---------------------------------------------------------------------------

def solve_pyomo() -> tuple[float, float, float]:
    import pyomo.environ as pyo
    from pyomo.opt import SolverFactory

    t0 = time.perf_counter()
    m = pyo.ConcreteModel()

    m.R      = pyo.Set(initialize=R)
    m.I      = pyo.Set(initialize=I)
    m.H      = pyo.Set(initialize=H)
    m.T      = pyo.Set(initialize=T)
    m.ROUTES = pyo.Set(initialize=data.routes, dimen=2)

    m.GEN  = pyo.Var(m.I, m.R, m.H, m.T, within=pyo.NonNegativeReals)
    m.CAP  = pyo.Var(m.I, m.R, m.T,      within=pyo.NonNegativeReals)
    m.INV  = pyo.Var(m.I, m.R, m.T,      within=pyo.NonNegativeReals)
    m.FLOW = pyo.Var(m.ROUTES, m.H, m.T, within=pyo.NonNegativeReals)

    @m.Constraint(m.I, m.R, m.T)
    def cap_accum(m, i, r, t):
        return m.CAP[i, r, t] == (
            data.cap_init[ii[i], ri[r]]
            + sum(m.INV[i, r, tt] for tt in T if tt <= t)
        )

    @m.Constraint(m.I, m.R, m.H, m.T)
    def cap_limit(m, i, r, h, t):
        return m.GEN[i, r, h, t] <= data.cf[ii[i], hi[h]] * m.CAP[i, r, t]

    @m.Constraint(m.R, m.H, m.T)
    def supply_demand(m, r, h, t):
        gen  = sum(m.GEN[i, r, h, t] for i in I)
        imp_ = sum((1 - data.tranloss) * m.FLOW[rr, r, h, t]
                   for rr in R if (rr, r) in data.routes)
        exp_ = sum(m.FLOW[r, rr, h, t]
                   for rr in R if (r, rr) in data.routes)
        return gen + imp_ - exp_ == data.load[ri[r], hi[h], ti[t]]

    @m.Constraint(m.R, m.T)
    def reserve_margin(m, r, t):
        peak = float(data.load[ri[r], :, ti[t]].max())
        return sum(m.CAP[i, r, t] for i in I) >= (1 + data.prm) * peak

    @m.Constraint(m.ROUTES, m.H, m.T)
    def trans_limit(m, r, rr, h, t):
        return m.FLOW[r, rr, h, t] <= data.transcap[(r, rr)]

    @m.Objective(sense=pyo.minimize)
    def obj(m):
        return sum(
            data.pvf[ti[t]] * (
                sum(data.cost_inv[ii[i]] * m.INV[i, r, t]
                    for i in I for r in R)
                + sum(data.cost_op[ii[i]] * data.hours_weight[hi[h]]
                      * m.GEN[i, r, h, t]
                      for i in I for r in R for h in H)
            )
            for t in T
        )

    build_s = time.perf_counter() - t0

    t1 = time.perf_counter()
    solver = SolverFactory("highs")
    solver.solve(m, tee=False)
    solve_s = time.perf_counter() - t1

    return float(pyo.value(m.obj)), build_s, solve_s


# ---------------------------------------------------------------------------
# 5. pyoptinterface
# ---------------------------------------------------------------------------

def solve_pyoptinterface() -> tuple[float, float, float]:
    import pyoptinterface as poi
    from pyoptinterface import highs
    from pyoptinterface._src.attributes import ModelAttribute

    t0 = time.perf_counter()
    m = highs.Model()
    m.set_model_attribute(ModelAttribute.Silent, True)

    GEN  = {}
    CAP  = {}
    INV  = {}
    FLOW = {}

    for i in I:
        for r in R:
            for t in T:
                CAP[(i,r,t)] = m.add_variable(lb=0.0)
                INV[(i,r,t)] = m.add_variable(lb=0.0)
                for h in H:
                    GEN[(i,r,h,t)] = m.add_variable(lb=0.0)

    for (r_from, r_to) in data.routes:
        for h in H:
            for t in T:
                FLOW[(r_from,r_to,h,t)] = m.add_variable(lb=0.0)

    # cap_accum: CAP[i,r,t] - sum_{tt<=t} INV[i,r,tt] = cap_init[i,r]
    for i in I:
        for r in R:
            for t in T:
                lhs = CAP[(i,r,t)] - sum(INV[(i,r,tt)] for tt in T if tt <= t)
                m.add_linear_constraint(lhs, poi.Eq,
                                        data.cap_init[ii[i], ri[r]])

    # cap_limit: GEN <= cf * CAP
    for i in I:
        for r in R:
            for h in H:
                for t in T:
                    m.add_linear_constraint(
                        GEN[(i,r,h,t)] - data.cf[ii[i], hi[h]] * CAP[(i,r,t)],
                        poi.Leq, 0.0
                    )

    # supply_demand
    for r in R:
        for h in H:
            for t in T:
                lhs = poi.quicksum(GEN[(i,r,h,t)] for i in I)
                for (r_from, r_to) in data.routes:
                    if r_to == r:
                        lhs += (1 - data.tranloss) * FLOW[(r_from,r_to,h,t)]
                    if r_from == r:
                        lhs -= FLOW[(r_from,r_to,h,t)]
                m.add_linear_constraint(lhs, poi.Eq,
                                        data.load[ri[r], hi[h], ti[t]])

    # reserve_margin
    for r in R:
        for t in T:
            peak = float(data.load[ri[r], :, ti[t]].max())
            lhs = poi.quicksum(CAP[(i,r,t)] for i in I)
            m.add_linear_constraint(lhs, poi.Geq, (1 + data.prm) * peak)

    # trans_limit
    for (r_from, r_to) in data.routes:
        for h in H:
            for t in T:
                m.add_linear_constraint(
                    FLOW[(r_from,r_to,h,t)],
                    poi.Leq, data.transcap[(r_from, r_to)]
                )

    # objective
    obj = poi.ExprBuilder()
    for k, t in enumerate(T):
        pv = data.pvf[k]
        for i in I:
            for r in R:
                obj += pv * data.cost_inv[ii[i]] * INV[(i,r,t)]
                for h in H:
                    obj += (pv * data.cost_op[ii[i]]
                            * data.hours_weight[hi[h]]
                            * GEN[(i,r,h,t)])
    m.set_objective(obj, poi.ObjectiveSense.Minimize)

    build_s = time.perf_counter() - t0

    t1 = time.perf_counter()
    m.optimize()
    solve_s = time.perf_counter() - t1

    obj_val = m.get_model_attribute(ModelAttribute.ObjectiveValue)
    return float(obj_val), build_s, solve_s


# ---------------------------------------------------------------------------
# 6. gamspy
# ---------------------------------------------------------------------------

def solve_gamspy(solver: str = "highs") -> tuple[float, float, float]:
    """solver: "highs" (default, comparable to other frameworks) or "cplex" (GAMS benchmark)."""
    import gamspy as gp

    t0 = time.perf_counter()
    c = gp.Container()

    # Sets
    r_set  = gp.Set(c, "r", records=R)
    i_set  = gp.Set(c, "i", records=I)
    h_set  = gp.Set(c, "h", records=[str(h) for h in H])
    t_set  = gp.Set(c, "t", records=[str(t) for t in T])
    tt     = gp.Alias(c, "tt", t_set)
    rr     = gp.Alias(c, "rr", r_set)
    rt_set = gp.Set(c, "rt", domain=[r_set, rr],
                    records=[(a, b) for a, b in data.routes])

    def _recs2d(arr, s1, s2):
        return [(k1, k2, float(arr[j1, j2]))
                for j1, k1 in enumerate(s1)
                for j2, k2 in enumerate(s2)]

    def _recs1d(arr, s1):
        return [(k, float(arr[j])) for j, k in enumerate(s1)]

    load_p  = gp.Parameter(c, "load_p",  domain=[r_set, h_set, t_set],
                            records=[(r, str(h), str(t),
                                      float(data.load[ri[r], hi[h], ti[t]]))
                                     for r in R for h in H for t in T])
    cf_p    = gp.Parameter(c, "cf_p",    domain=[i_set, h_set],
                            records=[(i, str(h), float(data.cf[ii[i], hi[h]]))
                                     for i in I for h in H])
    cinv_p  = gp.Parameter(c, "cinv_p",  domain=[i_set],
                            records=_recs1d(data.cost_inv, I))
    cop_p   = gp.Parameter(c, "cop_p",   domain=[i_set],
                            records=_recs1d(data.cost_op, I))
    ci_p    = gp.Parameter(c, "ci_p",    domain=[i_set, r_set],
                            records=_recs2d(data.cap_init, I, R))
    tc_p    = gp.Parameter(c, "tc_p",    domain=[r_set, rr],
                            records=[(a, b, float(data.transcap[(a,b)]))
                                     for a, b in data.routes])
    pvf_p   = gp.Parameter(c, "pvf_p",   domain=[t_set],
                            records=[(str(t), float(data.pvf[ti[t]])) for t in T])
    hw_p    = gp.Parameter(c, "hw_p",    domain=[h_set],
                            records=[(str(h), float(data.hours_weight[hi[h]])) for h in H])
    peak_p  = gp.Parameter(c, "peak_p",  domain=[r_set, t_set],
                            records=[(r, str(t),
                                      float(data.load[ri[r], :, ti[t]].max()))
                                     for r in R for t in T])

    # Variables
    GEN  = gp.Variable(c, "GEN",  domain=[i_set, r_set, h_set, t_set],
                        type="positive")
    CAP  = gp.Variable(c, "CAP",  domain=[i_set, r_set, t_set],
                        type="positive")
    INV  = gp.Variable(c, "INV",  domain=[i_set, r_set, t_set],
                        type="positive")
    FLOW = gp.Variable(c, "FLOW", domain=[r_set, rr, h_set, t_set],
                        type="positive")
    Z    = gp.Variable(c, "Z")

    # Equations
    eq_cap_accum = gp.Equation(c, "eq_cap_accum",
                                domain=[i_set, r_set, t_set])
    eq_cap_accum[...] = CAP[i_set, r_set, t_set] == (
        ci_p[i_set, r_set]
        + gp.Sum(tt.where[gp.Ord(tt) <= gp.Ord(t_set)],
                 INV[i_set, r_set, tt])
    )

    eq_cap_limit = gp.Equation(c, "eq_cap_limit",
                                domain=[i_set, r_set, h_set, t_set])
    eq_cap_limit[...] = (GEN[i_set, r_set, h_set, t_set]
                         <= cf_p[i_set, h_set] * CAP[i_set, r_set, t_set])

    eq_supply = gp.Equation(c, "eq_supply",
                             domain=[r_set, h_set, t_set])
    eq_supply[...] = (
        gp.Sum(i_set, GEN[i_set, r_set, h_set, t_set])
        + gp.Sum(rt_set[rr, r_set],
                 (1 - data.tranloss) * FLOW[rr, r_set, h_set, t_set])
        - gp.Sum(rt_set[r_set, rr],
                 FLOW[r_set, rr, h_set, t_set])
        == load_p[r_set, h_set, t_set]
    )

    eq_reserve = gp.Equation(c, "eq_reserve", domain=[r_set, t_set])
    eq_reserve[...] = (
        gp.Sum(i_set, CAP[i_set, r_set, t_set])
        >= (1 + data.prm) * peak_p[r_set, t_set]
    )

    eq_trans = gp.Equation(c, "eq_trans",
                            domain=[r_set, rr, h_set, t_set])
    eq_trans[rt_set[r_set, rr], h_set, t_set] = (
        FLOW[r_set, rr, h_set, t_set] <= tc_p[r_set, rr]
    )

    eq_obj = gp.Equation(c, "eq_obj")
    eq_obj[...] = Z == gp.Sum(
        t_set,
        pvf_p[t_set] * (
            gp.Sum([i_set, r_set],
                   cinv_p[i_set] * INV[i_set, r_set, t_set])
            + gp.Sum([i_set, r_set, h_set],
                     cop_p[i_set] * hw_p[h_set]
                     * GEN[i_set, r_set, h_set, t_set])
        )
    )

    model = gp.Model(
        c, "reeds_mini",
        equations=[eq_cap_accum, eq_cap_limit, eq_supply,
                   eq_reserve, eq_trans, eq_obj],
        problem="LP",
        sense=gp.Sense.MIN,
        objective=Z,
    )

    build_s = time.perf_counter() - t0

    t1 = time.perf_counter()
    model.solve(solver=solver, output=sys.stdout)
    solve_s = time.perf_counter() - t1

    return float(Z.records["level"].iloc[0]), build_s, solve_s


# ---------------------------------------------------------------------------
# 7. Run all and compare
# ---------------------------------------------------------------------------

SOLVERS = [
    ("linopy",              lambda: solve_linopy()),
    ("pyomo",               lambda: solve_pyomo()),
    ("pyoptinterface",      lambda: solve_pyoptinterface()),
    ("gamspy (highs)",      lambda: solve_gamspy("highs")),
    ("gamspy (cplex)",      lambda: solve_gamspy("cplex")),
]

print("=" * 60)
print("Solving with each framework (small problem)")
print("=" * 60)

results = {}
for name, fn in SOLVERS:
    try:
        obj, build_s, solve_s = fn()
        results[name] = obj
        print(f"  {name:<22} obj={obj:>15,.0f}  "
              f"build={build_s:.3f}s  solve={solve_s:.3f}s")
    except Exception as exc:
        import traceback
        print(f"  {name:<22} FAILED: {exc}")
        traceback.print_exc()
        results[name] = None

print()
print("=" * 60)
print("Cross-framework objective comparison")
print("=" * 60)
vals = [(n, v) for n, v in results.items() if v is not None]
if len(vals) >= 2:
    ref_name, ref_val = vals[0]
    for name, val in vals:
        rel_diff = abs(val - ref_val) / max(abs(ref_val), 1.0)
        flag = "OK" if rel_diff < ATOL_REL else "MISMATCH"
        print(f"  {name:<22} {flag}  (rel diff vs {ref_name}: {rel_diff:.2e})")
    print()
    all_ok = all(abs(v - ref_val) / max(abs(ref_val), 1.0) < ATOL_REL
                 for _, v in vals)
    if all_ok:
        print("All frameworks agree. Environment is ready for Request 2.")
    else:
        print("WARNING: Objective values differ — check solver status or formulation.")
else:
    print("Fewer than 2 frameworks succeeded.")
