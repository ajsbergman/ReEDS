"""
linopy implementation of the ReEDS-representative LP test problem.

All constraint and variable names mirror the GAMS originals in
reeds/core/setup/c_model.gms and reeds/core/setup/d_objective.gms.

Key linopy patterns used:
- Variables: m.add_variables(lower=0, coords=..., mask=valcap_da)
  mask=valcap_da excludes inactive (i,r,t) combinations, equivalent
  to GAMS $valcap dollar-conditionals
- Constraints: m.add_constraints(lhs == rhs, name="eq_name", mask=...)
  Masked-out entries are dropped from the LP matrix automatically
- Transmission (sparse): incidence matrix [r x routes] x FLOW[routes,h,t]
- Objective: broadcast xarray DataArrays against Variables and sum
"""

from __future__ import annotations
import time
import numpy as np
import xarray as xr
import linopy

from data_generator import ProblemData


def solve(data: ProblemData, solver: str = "highs") -> tuple[float, float, float]:
    R, I, H, T = data.regions, data.techs, data.hours, data.years
    nRoutes = len(data.routes)
    xp = data.as_xarray()

    # valcap mask — True where (i,r,t) is active
    valcap_da = xp["valcap"]                           # [i, r, t]  bool

    # Net-flow incidence matrix [r x routes]
    flow_mat = np.zeros((len(R), nRoutes))
    for k, (r_from, r_to) in enumerate(data.routes):
        flow_mat[data.r_idx[r_to],   k] += (1 - data.tranloss)
        flow_mat[data.r_idx[r_from], k] -= 1.0
    flow_da = xr.DataArray(flow_mat, dims=["r", "route"],
                           coords={"r": R, "route": list(range(nRoutes))})

    # ------------------------------------------------------------------ build
    t0 = time.perf_counter()
    m = linopy.Model()

    # Variables — mask drops inactive (i,r,t) combinations from the LP
    GEN  = m.add_variables(lower=0,
                            coords=[("i",I),("r",R),("h",H),("t",T)],
                            name="GEN",  mask=valcap_da)
    CAP  = m.add_variables(lower=0,
                            coords=[("i",I),("r",R),("t",T)],
                            name="CAP",  mask=valcap_da)
    INV  = m.add_variables(lower=0,
                            coords=[("i",I),("r",R),("t",T)],
                            name="INV",  mask=valcap_da)
    FLOW = m.add_variables(lower=0,
                            coords=[("route",list(range(nRoutes))),("h",H),("t",T)],
                            name="FLOW")

    # -- eq_cap_accum: CAP[i,r,t] = cap_init[i,r] + sum_{tt<=t} INV[i,r,tt]
    for k, yr in enumerate(T):
        past_inv = INV.sel(t=T[:k+1]).sum("t")   # LinearExpression [i,r]
        m.add_constraints(
            CAP.sel(t=yr) - past_inv == xp["cap_init"],
            name=f"eq_cap_accum_{yr}",
            mask=valcap_da.sel(t=yr),
        )

    # -- eq_cap_limit: GEN[i,r,h,t] <= cf[i,h] * CAP[i,r,t]
    m.add_constraints(GEN <= xp["cf"] * CAP,
                      name="eq_cap_limit", mask=valcap_da)

    # -- eq_mingen: GEN[i,r,h,t] >= minloadfrac[i] * CAP[i,r,t]
    #    Active only for dispatchable techs (minloadfrac > 0) and valid valcap
    has_mingen = valcap_da & (xp["minloadfrac"] > 0)
    m.add_constraints(GEN >= xp["minloadfrac"] * CAP,
                      name="eq_mingen", mask=has_mingen)

    # -- eq_supply_demand_balance: sum_i GEN + net_import = load
    net_import = (flow_da * FLOW).sum("route")   # LinearExpression [r,h,t]
    m.add_constraints(
        GEN.sum("i") + net_import == xp["load"],
        name="eq_supply_demand_balance",
    )

    # -- eq_reserve_margin: sum_i CAP[i,r,t] >= (1+prm) * peak_load[r,t]
    peak_load = xr.DataArray(data.load.max(axis=1),
                             dims=["r","t"], coords={"r":R,"t":T})
    m.add_constraints(
        CAP.sum("i") >= (1 + data.prm) * peak_load,
        name="eq_reserve_margin",
    )

    # -- eq_transmission_limit: FLOW[route,h,t] <= transcap[route]
    tcap = xr.DataArray([data.transcap[rt] for rt in data.routes],
                        dims=["route"], coords={"route": list(range(nRoutes))})
    m.add_constraints(FLOW <= tcap, name="eq_transmission_limit")

    # -- eq_emit_cap: sum_{i,r,h} emit_rate[i]*hw[h]*GEN <= emit_cap[t]
    emissions = (xp["emit_rate"] * xp["hours_weight"] * GEN).sum(["i","r","h"])
    m.add_constraints(emissions <= xp["emit_cap"], name="eq_emit_cap")

    # -- Objective
    obj = (xp["pvf"] * xp["cost_inv"] * INV).sum() \
        + (xp["pvf"] * xp["cost_op"] * xp["hours_weight"] * GEN).sum()
    m.add_objective(obj)

    build_s = time.perf_counter() - t0

    # ------------------------------------------------------------------ solve
    t1 = time.perf_counter()
    m.solve(solver, io_api="direct", output_flag=False)
    solve_s = time.perf_counter() - t1

    return float(m.objective.value), build_s, solve_s


if __name__ == "__main__":
    import sys
    sys.path.insert(0, __file__.rsplit("\\", 1)[0])
    from data_generator import make_problem
    for size in ("small", "medium", "large"):
        data = make_problem(size)
        obj, b, s = solve(data)
        print(f"{size:6s}  obj={obj:>18,.0f}  build={b:.3f}s  solve={s:.3f}s")
