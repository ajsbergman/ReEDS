"""
gamspy implementation of the ReEDS-representative LP test problem.

All constraint and variable names mirror the GAMS originals in
reeds/core/setup/c_model.gms and reeds/core/setup/d_objective.gms.

Key gamspy patterns used:
- gp.Alias(c, "tt", t_set) for cumulative-sum index
- tt.where[gp.Ord(tt) <= gp.Ord(t_set)] for past-year filter
- valcap_set as sparse domain to filter equations (equiv. $valcap)
- disp_set restricts eq_mingen to dispatchable techs
- model.solve(solver=...) accepts "highs" or "cplex"

Note: gamspy build_s includes GAMS model-compilation overhead.
Note: the demo GAMS license caps at 2000 rows/columns; medium and
      larger sizes will raise a license error on an unlicensed install.
"""

from __future__ import annotations
import time
import gamspy as gp

from data_generator import ProblemData


def solve(data: ProblemData, solver: str = "highs") -> tuple[float, float, float]:
    R, I, H, T = data.regions, data.techs, data.hours, data.years
    ri, ii, hi, ti = data.r_idx, data.i_idx, data.h_idx, data.t_idx

    # ------------------------------------------------------------------ build
    t0 = time.perf_counter()
    c = gp.Container()

    # Sets
    r_set  = gp.Set(c, "r",  records=R)
    i_set  = gp.Set(c, "i",  records=I)
    h_set  = gp.Set(c, "h",  records=[str(h) for h in H])
    t_set  = gp.Set(c, "t",  records=[str(t) for t in T])
    tt     = gp.Alias(c, "tt", t_set)
    rr     = gp.Alias(c, "rr", r_set)

    # Sparse route set
    rt_set = gp.Set(c, "rt", domain=[r_set, rr],
                    records=[(a, b) for a, b in data.routes])

    # valcap sparse set — equivalent to GAMS $valcap dollar-conditional
    valcap_set = gp.Set(c, "valcap", domain=[i_set, r_set, t_set],
                        records=[(i, r, str(t))
                                 for i in I for r in R for t in T
                                 if data.valcap[ii[i], ri[r], ti[t]]])

    # Sparse (i,r,t) set for eq_mingen — dispatchable techs within valcap
    disp_irt = gp.Set(c, "disp_irt", domain=[i_set, r_set, t_set],
                      records=[(i, r, str(t))
                               for i in I for r in R for t in T
                               if data.valcap[ii[i], ri[r], ti[t]]
                               and data.minloadfrac[ii[i]] > 0])

    # Parameters
    load_p = gp.Parameter(c, "load_p", domain=[r_set, h_set, t_set],
                          records=[(r, str(h), str(t),
                                    float(data.load[ri[r], hi[h], ti[t]]))
                                   for r in R for h in H for t in T])

    cf_p   = gp.Parameter(c, "cf_p",   domain=[i_set, h_set],
                          records=[(i, str(h), float(data.cf[ii[i], hi[h]]))
                                   for i in I for h in H])

    cinv_p = gp.Parameter(c, "cinv_p", domain=[i_set],
                          records=[(i, float(data.cost_inv[ii[i]])) for i in I])

    cop_p  = gp.Parameter(c, "cop_p",  domain=[i_set],
                          records=[(i, float(data.cost_op[ii[i]])) for i in I])

    ci_p   = gp.Parameter(c, "ci_p",   domain=[i_set, r_set],
                          records=[(i, r, float(data.cap_init[ii[i], ri[r]]))
                                   for i in I for r in R])

    tc_p   = gp.Parameter(c, "tc_p",   domain=[r_set, rr],
                          records=[(a, b, float(data.transcap[(a, b)]))
                                   for (a, b) in data.routes])

    pvf_p  = gp.Parameter(c, "pvf_p",  domain=[t_set],
                          records=[(str(t), float(data.pvf[ti[t]])) for t in T])

    hw_p   = gp.Parameter(c, "hw_p",   domain=[h_set],
                          records=[(str(h), float(data.hours_weight[hi[h]]))
                                   for h in H])

    peak_p = gp.Parameter(c, "peak_p", domain=[r_set, t_set],
                          records=[(r, str(t),
                                    float(data.load[ri[r], :, ti[t]].max()))
                                   for r in R for t in T])

    mf_p   = gp.Parameter(c, "mf_p",   domain=[i_set],
                          records=[(i, float(data.minloadfrac[ii[i]]))
                                   for i in I if data.minloadfrac[ii[i]] > 0])

    er_p   = gp.Parameter(c, "er_p",   domain=[i_set],
                          records=[(i, float(data.emit_rate[ii[i]]))
                                   for i in I if data.emit_rate[ii[i]] > 0])

    ec_p   = gp.Parameter(c, "ec_p",   domain=[t_set],
                          records=[(str(t), float(data.emit_cap[ti[t]])) for t in T])

    # Variables
    GEN  = gp.Variable(c, "GEN",  domain=[i_set, r_set, h_set, t_set], type="positive")
    CAP  = gp.Variable(c, "CAP",  domain=[i_set, r_set, t_set],        type="positive")
    INV  = gp.Variable(c, "INV",  domain=[i_set, r_set, t_set],        type="positive")
    FLOW = gp.Variable(c, "FLOW", domain=[r_set, rr, h_set, t_set],    type="positive")
    Z    = gp.Variable(c, "Z")

    # -- eq_cap_accum (active only for valcap combinations)
    eq_cap_accum = gp.Equation(c, "eq_cap_accum", domain=[i_set, r_set, t_set])
    eq_cap_accum[valcap_set[i_set, r_set, t_set]] = (
        CAP[i_set, r_set, t_set] == (
            ci_p[i_set, r_set]
            + gp.Sum(tt.where[gp.Ord(tt) <= gp.Ord(t_set)],
                     INV[i_set, r_set, tt])
        )
    )

    # -- eq_cap_limit (active only for valcap combinations)
    eq_cap_limit = gp.Equation(c, "eq_cap_limit", domain=[i_set, r_set, h_set, t_set])
    eq_cap_limit[valcap_set[i_set, r_set, t_set], h_set] = (
        GEN[i_set, r_set, h_set, t_set]
        <= cf_p[i_set, h_set] * CAP[i_set, r_set, t_set]
    )

    # -- eq_mingen: dispatchable techs only, within valcap
    eq_mingen = gp.Equation(c, "eq_mingen", domain=[i_set, r_set, h_set, t_set])
    eq_mingen[disp_irt[i_set, r_set, t_set], h_set] = (
        GEN[i_set, r_set, h_set, t_set]
        >= mf_p[i_set] * CAP[i_set, r_set, t_set]
    )

    # -- eq_supply_demand_balance
    eq_supply = gp.Equation(c, "eq_supply_demand_balance",
                             domain=[r_set, h_set, t_set])
    eq_supply[...] = (
        gp.Sum(i_set, GEN[i_set, r_set, h_set, t_set])
        + gp.Sum(rt_set[rr, r_set],
                 (1 - data.tranloss) * FLOW[rr, r_set, h_set, t_set])
        - gp.Sum(rt_set[r_set, rr],
                 FLOW[r_set, rr, h_set, t_set])
        == load_p[r_set, h_set, t_set]
    )

    # -- eq_reserve_margin
    eq_reserve = gp.Equation(c, "eq_reserve_margin", domain=[r_set, t_set])
    eq_reserve[...] = (
        gp.Sum(i_set, CAP[i_set, r_set, t_set])
        >= (1 + data.prm) * peak_p[r_set, t_set]
    )

    # -- eq_transmission_limit (routes only)
    eq_trans = gp.Equation(c, "eq_transmission_limit",
                            domain=[r_set, rr, h_set, t_set])
    eq_trans[rt_set[r_set, rr], h_set, t_set] = (
        FLOW[r_set, rr, h_set, t_set] <= tc_p[r_set, rr]
    )

    # -- eq_emit_cap: annual CO2 cap
    eq_emit = gp.Equation(c, "eq_emit_cap", domain=[t_set])
    eq_emit[...] = (
        gp.Sum([i_set, r_set, h_set],
               er_p[i_set] * hw_p[h_set] * GEN[i_set, r_set, h_set, t_set])
        <= ec_p[t_set]
    )

    # -- Objective
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
        equations=[eq_cap_accum, eq_cap_limit, eq_mingen,
                   eq_supply, eq_reserve, eq_trans, eq_emit, eq_obj],
        problem="LP",
        sense=gp.Sense.MIN,
        objective=Z,
    )

    build_s = time.perf_counter() - t0

    # ------------------------------------------------------------------ solve
    t1 = time.perf_counter()
    model.solve(solver=solver, output=None)
    solve_s = time.perf_counter() - t1

    return float(Z.records["level"].iloc[0]), build_s, solve_s


if __name__ == "__main__":
    import sys, os
    sys.path.insert(0, os.path.dirname(__file__))
    from data_generator import make_problem

    gams_solver = sys.argv[1] if len(sys.argv) > 1 else "highs"
    for size in ("small", "medium", "large"):
        data = make_problem(size)
        obj, b, s = solve(data, solver=gams_solver)
        print(f"{size:6s}  obj={obj:>18,.0f}  build={b:.3f}s  solve={s:.3f}s")
