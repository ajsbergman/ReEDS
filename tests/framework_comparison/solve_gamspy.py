"""
gamspy implementation of the ReEDS-representative LP test problem.

All constraint and variable names mirror the GAMS originals in
reeds/core/setup/c_model.gms and reeds/core/setup/d_objective.gms.

Key gamspy patterns used:
- gp.Alias(c, "tt", t_set) for cumulative-sum index
- tt.where[gp.Ord(tt) <= gp.Ord(t_set)] for past-year filter
- valcap_set as sparse domain to filter equations (equiv. $valcap)
- h_ramp_set (no wrap) for eq_ramping; h_suc_set (cyclic) for eq_soc
- cf_p is 3D: [i, r, h] for region-specific VRE profiles
- sc_p sparsity (only dispatchable techs) filters RAMPUP in objective

Note: gamspy build_s includes GAMS model-compilation overhead.
"""

from __future__ import annotations
import time
import gamspy as gp

from data_generator import ProblemData


def _param(c, name, domain, records):
    """Create a GAMSPy parameter; skip records when empty to avoid dimension errors."""
    if records:
        return gp.Parameter(c, name, domain=domain, records=records)
    return gp.Parameter(c, name, domain=domain)


def solve(data: ProblemData, solver: str = "highs", build_only: bool = False) -> tuple[float, float, float]:
    R, I, H, T = data.regions, data.techs, data.hours, data.years
    ri, ii, hi, ti = data.r_idx, data.i_idx, data.h_idx, data.t_idx

    disp_techs    = [i for i in I if not data.is_vre[ii[i]] and not data.is_storage[ii[i]]]
    storage_techs = [i for i in I if data.is_storage[ii[i]]]
    has_disp      = bool(disp_techs)
    has_storage   = bool(storage_techs)

    # ------------------------------------------------------------------ build
    t0 = time.perf_counter()
    c = gp.Container()

    # Sets
    r_set = gp.Set(c, "r", records=R)
    i_set = gp.Set(c, "i", records=I)
    h_set = gp.Set(c, "h", records=[str(h) for h in H])
    t_set = gp.Set(c, "t", records=[str(t) for t in T])
    tt    = gp.Alias(c, "tt", t_set)
    rr    = gp.Alias(c, "rr", r_set)
    hh    = gp.Alias(c, "hh", h_set)

    rt_set = gp.Set(c, "rt", domain=[r_set, rr],
                    records=[(a, b) for a, b in data.routes])

    valcap_set = gp.Set(c, "valcap", domain=[i_set, r_set, t_set],
                        records=[(i, r, str(t))
                                 for i in I for r in R for t in T
                                 if data.valcap[ii[i], ri[r], ti[t]]])

    # Consecutive-hour sets: h_ramp (no wrap) for ramping; h_suc (cyclic) for SOC
    h_ramp_set = gp.Set(c, "h_ramp", domain=[h_set, hh],
                        records=[(str(H[k]), str(H[k + 1])) for k in range(len(H) - 1)])
    h_suc_set  = gp.Set(c, "h_suc",  domain=[h_set, hh],
                        records=[(str(H[k]), str(H[(k + 1) % len(H)])) for k in range(len(H))])

    # Sparse domain sets — combined to avoid GAMS split-domain limitations
    if has_disp:
        # (i,r,h,hh,t) for eq_ramping: disp valcap × consecutive h pairs
        ramp_domain = gp.Set(c, "ramp_domain", domain=[i_set, r_set, h_set, hh, t_set],
                             records=[(i, r, str(H[k]), str(H[k + 1]), str(t))
                                      for i in disp_techs for r in R
                                      for k in range(len(H) - 1)
                                      for t in T
                                      if data.valcap[ii[i], ri[r], ti[t]]])
    if has_storage:
        stor_set      = gp.Set(c, "stor", domain=[i_set], records=storage_techs)
        stor_valcap   = gp.Set(c, "stor_valcap", domain=[i_set, r_set, t_set],
                               records=[(i, r, str(t))
                                        for i in storage_techs for r in R for t in T
                                        if data.valcap[ii[i], ri[r], ti[t]]])
        # (i,r,h,t) for eq_soc_cap / eq_charge_cap: storage valcap × all h
        stor_h_domain = gp.Set(c, "stor_h_domain", domain=[i_set, r_set, h_set, t_set],
                               records=[(i, r, str(h), str(t))
                                        for i in storage_techs for r in R
                                        for h in H for t in T
                                        if data.valcap[ii[i], ri[r], ti[t]]])
        # (i,r,h,hh,t) for eq_soc: storage valcap × cyclic consecutive h pairs
        soc_domain    = gp.Set(c, "soc_domain", domain=[i_set, r_set, h_set, hh, t_set],
                               records=[(i, r, str(H[k]), str(H[(k + 1) % len(H)]), str(t))
                                        for i in storage_techs for r in R
                                        for k in range(len(H))
                                        for t in T
                                        if data.valcap[ii[i], ri[r], ti[t]]])

    mincf_valcap = gp.Set(c, "mincf_valcap", domain=[i_set, r_set, t_set],
                           records=[(i, r, str(t))
                                    for i in I for r in R for t in T
                                    if (data.valcap[ii[i], ri[r], ti[t]]
                                        and data.min_cf[ii[i]] > 0
                                        and not data.is_storage[ii[i]])])

    # Binary mask for valcap — used to restrict sums to active (i,r,t) only,
    # preventing non-valcap GEN/CAP from satisfying supply/reserve constraints for free.
    valcap_p = gp.Parameter(c, "valcap_p", domain=[i_set, r_set, t_set],
                            records=[(i, r, str(t), 1.0)
                                     for i in I for r in R for t in T
                                     if data.valcap[ii[i], ri[r], ti[t]]])

    # Parameters
    load_p = gp.Parameter(c, "load_p", domain=[r_set, h_set, t_set],
                          records=[(r, str(h), str(t), float(data.load[ri[r], hi[h], ti[t]]))
                                   for r in R for h in H for t in T])

    cf_p   = gp.Parameter(c, "cf_p",   domain=[i_set, r_set, h_set],
                          records=[(i, r, str(h), float(data.cf[ii[i], ri[r], hi[h]]))
                                   for i in I for r in R for h in H])

    cinv_p = gp.Parameter(c, "cinv_p", domain=[i_set],
                          records=[(i, float(data.cost_inv[ii[i]])) for i in I])

    cop_p  = gp.Parameter(c, "cop_p",  domain=[i_set],
                          records=[(i, float(data.cost_op[ii[i]])) for i in I])

    sc_p    = _param(c, "sc_p",    [i_set],
                     [(i, float(data.startcost[ii[i]])) for i in I if data.startcost[ii[i]] > 0])
    mincf_p = _param(c, "mincf_p", [i_set],
                     [(i, float(data.min_cf[ii[i]])) for i in I if data.min_cf[ii[i]] > 0])
    mf_p    = _param(c, "mf_p",    [i_set],
                     [(i, float(data.minloadfrac[ii[i]])) for i in I if data.minloadfrac[ii[i]] > 0])
    er_p    = _param(c, "er_p",    [i_set],
                     [(i, float(data.emit_rate[ii[i]])) for i in I if data.emit_rate[ii[i]] > 0])

    ci_p   = gp.Parameter(c, "ci_p",   domain=[i_set, r_set],
                          records=[(i, r, float(data.cap_init[ii[i], ri[r]]))
                                   for i in I for r in R])
    tc_p   = gp.Parameter(c, "tc_p",   domain=[r_set, rr],
                          records=[(a, b, float(data.transcap[(a, b)]))
                                   for (a, b) in data.routes])
    pvf_p  = gp.Parameter(c, "pvf_p",  domain=[t_set],
                          records=[(str(t), float(data.pvf[ti[t]])) for t in T])
    hw_p   = gp.Parameter(c, "hw_p",   domain=[h_set],
                          records=[(str(h), float(data.hours_weight[hi[h]])) for h in H])
    peak_p = gp.Parameter(c, "peak_p", domain=[r_set, t_set],
                          records=[(r, str(t), float(data.load[ri[r], :, ti[t]].max()))
                                   for r in R for t in T])
    ec_p   = gp.Parameter(c, "ec_p",   domain=[t_set],
                          records=[(str(t), float(data.emit_cap[ti[t]])) for t in T])

    total_hw = float(data.hours_weight.sum())

    # Variables
    GEN  = gp.Variable(c, "GEN",  domain=[i_set, r_set, h_set, t_set], type="positive")
    CAP  = gp.Variable(c, "CAP",  domain=[i_set, r_set, t_set],        type="positive")
    INV  = gp.Variable(c, "INV",  domain=[i_set, r_set, t_set],        type="positive")
    FLOW = gp.Variable(c, "FLOW", domain=[r_set, rr, h_set, t_set],    type="positive")
    Z    = gp.Variable(c, "Z")

    if has_disp:
        RAMPUP = gp.Variable(c, "RAMPUP", domain=[i_set, r_set, h_set, t_set], type="positive")
    if has_storage:
        CHARGE = gp.Variable(c, "CHARGE", domain=[i_set, r_set, h_set, t_set], type="positive")
        SOC    = gp.Variable(c, "SOC",    domain=[i_set, r_set, h_set, t_set], type="positive")

    equations = []

    # -- eq_cap_accum
    eq_cap_accum = gp.Equation(c, "eq_cap_accum", domain=[i_set, r_set, t_set])
    eq_cap_accum[valcap_set[i_set, r_set, t_set]] = (
        CAP[i_set, r_set, t_set] == (
            ci_p[i_set, r_set]
            + gp.Sum(tt.where[gp.Ord(tt) <= gp.Ord(t_set)], INV[i_set, r_set, tt])
        )
    )
    equations.append(eq_cap_accum)

    # -- eq_cap_limit: 3D cf (region-specific VRE profiles)
    eq_cap_limit = gp.Equation(c, "eq_cap_limit", domain=[i_set, r_set, h_set, t_set])
    eq_cap_limit[...] = (
        GEN[i_set, r_set, h_set, t_set]
        <= cf_p[i_set, r_set, h_set] * CAP[i_set, r_set, t_set]
    )
    equations.append(eq_cap_limit)

    # -- eq_mingen: mf_p sparsity restricts to dispatchable techs with minload > 0
    eq_mingen = gp.Equation(c, "eq_mingen", domain=[i_set, r_set, h_set, t_set])
    eq_mingen[...] = (
        GEN[i_set, r_set, h_set, t_set]
        >= mf_p[i_set] * CAP[i_set, r_set, t_set]
    )
    equations.append(eq_mingen)

    # -- eq_supply_demand_balance
    eq_supply = gp.Equation(c, "eq_supply_demand_balance", domain=[r_set, h_set, t_set])
    supply_lhs = (
        gp.Sum(i_set, valcap_p[i_set, r_set, t_set] * GEN[i_set, r_set, h_set, t_set])
        + gp.Sum(rt_set[rr, r_set], (1 - data.tranloss) * FLOW[rr, r_set, h_set, t_set])
        - gp.Sum(rt_set[r_set, rr], FLOW[r_set, rr, h_set, t_set])
    )
    if has_storage:
        supply_lhs = (
            supply_lhs - gp.Sum(stor_set[i_set], CHARGE[i_set, r_set, h_set, t_set])
        )
    eq_supply[...] = supply_lhs == load_p[r_set, h_set, t_set]
    equations.append(eq_supply)

    # -- eq_reserve_margin
    eq_reserve = gp.Equation(c, "eq_reserve_margin", domain=[r_set, t_set])
    eq_reserve[...] = (
        gp.Sum(i_set, valcap_p[i_set, r_set, t_set] * CAP[i_set, r_set, t_set])
        >= (1 + data.prm) * peak_p[r_set, t_set]
    )
    equations.append(eq_reserve)

    # -- eq_transmission_limit
    eq_trans = gp.Equation(c, "eq_transmission_limit", domain=[r_set, rr, h_set, t_set])
    eq_trans[rt_set[r_set, rr], h_set, t_set] = (
        FLOW[r_set, rr, h_set, t_set] <= tc_p[r_set, rr]
    )
    equations.append(eq_trans)

    # -- eq_emit_cap
    eq_emit = gp.Equation(c, "eq_emit_cap", domain=[t_set])
    eq_emit[...] = (
        gp.Sum([i_set, r_set, h_set],
               er_p[i_set] * hw_p[h_set] * GEN[i_set, r_set, h_set, t_set])
        <= ec_p[t_set]
    )
    equations.append(eq_emit)

    # -- eq_ramping: RAMPUP[i,r,h,t] >= GEN[i,r,hh,t] - GEN[i,r,h,t]
    #    ramp_domain pre-combines disp valcap × consecutive h pairs
    if has_disp:
        eq_ramping = gp.Equation(c, "eq_ramping", domain=[i_set, r_set, h_set, hh, t_set])
        eq_ramping[ramp_domain[i_set, r_set, h_set, hh, t_set]] = (
            RAMPUP[i_set, r_set, h_set, t_set]
            >= GEN[i_set, r_set, hh, t_set] - GEN[i_set, r_set, h_set, t_set]
        )
        equations.append(eq_ramping)

    # -- eq_min_cf: sum_h hw*GEN >= mincf * CAP * total_hw
    eq_min_cf = gp.Equation(c, "eq_min_cf", domain=[i_set, r_set, t_set])
    eq_min_cf[mincf_valcap[i_set, r_set, t_set]] = (
        gp.Sum(h_set, hw_p[h_set] * GEN[i_set, r_set, h_set, t_set])
        >= mincf_p[i_set] * CAP[i_set, r_set, t_set] * total_hw
    )
    equations.append(eq_min_cf)

    # -- Storage constraints
    if has_storage:
        eq_soc_cap = gp.Equation(c, "eq_soc_cap", domain=[i_set, r_set, h_set, t_set])
        eq_soc_cap[stor_h_domain[i_set, r_set, h_set, t_set]] = (
            SOC[i_set, r_set, h_set, t_set] <= data.duration_h * CAP[i_set, r_set, t_set]
        )
        equations.append(eq_soc_cap)

        eq_charge_cap = gp.Equation(c, "eq_charge_cap", domain=[i_set, r_set, h_set, t_set])
        eq_charge_cap[stor_h_domain[i_set, r_set, h_set, t_set]] = (
            CHARGE[i_set, r_set, h_set, t_set] <= CAP[i_set, r_set, t_set]
        )
        equations.append(eq_charge_cap)

        # SOC[hh] = SOC[h] + eff*CHARGE[h] - GEN[h], cyclic via soc_domain
        eq_soc = gp.Equation(c, "eq_soc", domain=[i_set, r_set, h_set, hh, t_set])
        eq_soc[soc_domain[i_set, r_set, h_set, hh, t_set]] = (
            SOC[i_set, r_set, hh, t_set]
            == SOC[i_set, r_set, h_set, t_set]
               + data.charge_eff * CHARGE[i_set, r_set, h_set, t_set]
               - GEN[i_set, r_set, h_set, t_set]
        )
        equations.append(eq_soc)

    # -- Objective
    eq_obj = gp.Equation(c, "eq_obj")
    if has_disp:
        # sc_p sparsity restricts RAMPUP sum to techs with startcost > 0 (disp only);
        # RAMPUP at the last h has no lower-bound constraint and is 0 at optimality.
        eq_obj[...] = Z == gp.Sum(t_set, pvf_p[t_set] * (
            gp.Sum([i_set, r_set], cinv_p[i_set] * INV[i_set, r_set, t_set])
            + gp.Sum([i_set, r_set, h_set],
                     cop_p[i_set] * hw_p[h_set] * GEN[i_set, r_set, h_set, t_set])
            + gp.Sum([i_set, r_set, h_set],
                     sc_p[i_set] * RAMPUP[i_set, r_set, h_set, t_set])
        ))
    else:
        eq_obj[...] = Z == gp.Sum(t_set, pvf_p[t_set] * (
            gp.Sum([i_set, r_set], cinv_p[i_set] * INV[i_set, r_set, t_set])
            + gp.Sum([i_set, r_set, h_set],
                     cop_p[i_set] * hw_p[h_set] * GEN[i_set, r_set, h_set, t_set])
        ))
    equations.append(eq_obj)

    model = gp.Model(
        c, "reeds_mini",
        equations=equations,
        problem="LP",
        sense=gp.Sense.MIN,
        objective=Z,
    )

    build_s = time.perf_counter() - t0
    if build_only:
        return float("nan"), build_s, 0.0

    # ------------------------------------------------------------------ solve
    t1 = time.perf_counter()
    if solver.lower() == "highs":
        solver_opts = {"solver": "ipm"}
    elif solver.lower() == "cplex":
        solver_opts = {"lpmethod": 4}
    else:
        solver_opts = {}
    model.solve(solver=solver, output=None, solver_options=solver_opts)
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
