# /// script
# requires-python = ">=3.12"
# dependencies = [
#   "arco",
#   "numpy",
# ]
#
# [tool.uv.sources]
# arco = { git = "https://github.com/NatLabRockies/arco.git", rev = "main", subdirectory = "bindings/python" }
# ///

"""
Arco-Python implementation of the ReEDS-representative LP test problem.

All constraint and variable names mirror the GAMS originals in
reeds/core/setup/c_model.gms and reeds/core/setup/d_objective.gms.
"""

from __future__ import annotations

import gc
import importlib.metadata
import time
from typing import NotRequired, TypedDict

import arco
import numpy as np

from data_generator import ProblemData


LAST_SOLVE_METADATA: dict[str, float] = {}
LAST_SOLVE_STATUS: str | None = None
LAST_FRAMEWORK_METADATA: dict[str, object] = {}
HIGHS_PRIMAL_SOLUTION_FEASIBLE = 2.0


def _objective_value_for_reporting(
    objective_value: float, solve_metadata: dict[str, float]
) -> float:
    """Return NaN when HiGHS has not reported a feasible primal solution."""
    primal_status = solve_metadata.get("highs_primal_solution_status")
    if primal_status is not None and primal_status != HIGHS_PRIMAL_SOLUTION_FEASIBLE:
        return float("nan")
    return objective_value


def _format_objective_value(objective_value: float) -> str:
    if objective_value != objective_value:
        return "n/a"
    return f"{objective_value:>18,.0f}"


def _constraint_reserve_count(data: ProblemData) -> int:
    transmission_bound_rows = len(data.routes) * len(data.hours) * len(data.years)
    return max(0, data.n_constraints - transmission_bound_rows + 1024)


def _runtime_metadata(solver: str) -> dict[str, object]:
    try:
        arco_version = importlib.metadata.version("arco")
    except importlib.metadata.PackageNotFoundError:
        arco_version = ""
    return {
        "arco_version": arco_version,
        "solver_runtime_info": dict(arco.solver_runtime_info(family=solver)),
    }


def solve(
    data: ProblemData,
    solver: str = "highs",
    build_only: bool = False,
    time_limit: float | None = None,
    presolve: bool | None = None,
    threads: int | None = None,
    highs_solver: str = "ipm",
    highs_run_crossover: str | None = None,
    highs_load_path: str | None = None,
    xpress_lp_algorithm: str | None = None,
    require_optimal: bool = True,
) -> tuple[float, float, float]:
    if solver not in {"highs", "scip", "xpress"}:
        raise ValueError(
            "solve_arco only supports solver='highs', solver='scip', or solver='xpress'"
        )

    global LAST_SOLVE_METADATA
    global LAST_SOLVE_STATUS
    global LAST_FRAMEWORK_METADATA
    LAST_SOLVE_METADATA = {}
    LAST_SOLVE_STATUS = None
    LAST_FRAMEWORK_METADATA = _runtime_metadata(solver)

    regions, techs, hours, years = data.regions, data.techs, data.hours, data.years
    region_index = data.r_idx
    total_hours_weight = float(np.sum(data.hours_weight))
    tranloss_factor = 1.0 - float(data.tranloss)
    reserve_margin_factor = 1.0 + float(data.prm)
    duration_h = float(data.duration_h)
    charge_eff = float(data.charge_eff)

    route_active_matrix = np.zeros((len(regions), len(regions)), dtype=bool)
    transcap_matrix = np.zeros((len(regions), len(regions)), dtype=float)
    for r_from, r_to in data.routes:
        row = region_index[r_from]
        col = region_index[r_to]
        route_active_matrix[row, col] = True
        transcap_matrix[row, col] = float(data.transcap[(r_from, r_to)])

    t0 = time.perf_counter()
    model = arco.Model()
    model.reserve(
        num_variables=data.n_vars,
        num_constraints=_constraint_reserve_count(data),
    )

    I = arco.IndexSet("i", members=techs)  # noqa: E741
    R = arco.IndexSet("r", members=regions)
    H = arco.IndexSet("h", members=hours)
    T = arco.IndexSet("t", members=years)
    H_ramp = H[:-1]
    R_from = R.alias("from")
    R_to = R.alias("to")

    valcap = arco.param(data.valcap, I, R, T)
    is_vre = arco.param(data.is_vre, I)
    is_storage = arco.param(data.is_storage, I)
    is_dispatch = ~is_vre & ~is_storage
    storage_active = valcap & is_storage
    dispatch_active = valcap & is_dispatch

    cf = arco.param(data.cf, I, R, H)
    cap_init = arco.param(data.cap_init, I, R)
    load = arco.param(data.load, R, H, T)
    peak_load = arco.param(data.load.max(axis=1), R, T)
    minloadfrac = arco.param(data.minloadfrac, I)
    min_cf = arco.param(data.min_cf, I)
    emit_rate = arco.param(data.emit_rate, I)
    emit_cap = arco.param(data.emit_cap, T)
    hours_weight = arco.param(data.hours_weight, H)
    pvf = arco.param(data.pvf, T)
    cost_inv = arco.param(data.cost_inv, I)
    cost_op = arco.param(data.cost_op, I)
    startcost = arco.param(data.startcost, I)

    route_active = arco.param(route_active_matrix, R_from, R_to)
    transcap = arco.param(transcap_matrix, R_from, R_to)
    del route_active_matrix, transcap_matrix

    cap = model.add_variables(
        I,
        R,
        T,
        bounds=arco.NonNegativeFloat,
        active=valcap,
        name="CAP",
    )
    inv = model.add_variables(
        I,
        R,
        T,
        bounds=arco.NonNegativeFloat,
        active=valcap,
        name="INV",
    )
    gen = model.add_variables(
        I,
        R,
        H,
        T,
        bounds=arco.NonNegativeFloat,
        active=valcap,
        name="GEN",
    )
    flow = model.add_variables(
        R_from,
        R_to,
        H,
        T,
        bounds=arco.Bounds(0, transcap),
        active=route_active,
        name="FLOW",
    )
    del route_active, transcap
    rampup = model.add_variables(
        I,
        R,
        H_ramp,
        T,
        bounds=arco.NonNegativeFloat,
        active=dispatch_active,
        name="RAMPUP",
    )
    charge = model.add_variables(
        I,
        R,
        H,
        T,
        bounds=arco.NonNegativeFloat,
        active=storage_active,
        name="CHARGE",
    )
    soc = model.add_variables(
        I,
        R,
        H,
        T,
        bounds=arco.NonNegativeFloat,
        active=storage_active,
        name="SOC",
    )

    model.add_constraints(
        cap == cap_init + np.cumsum(inv, axis=T),
        name="eq_cap_accum",
    )
    del cap_init
    model.add_constraints(
        gen <= cf * cap,
        name="eq_cap_limit",
    )
    del cf
    model.add_constraints(
        gen >= minloadfrac * cap,
        active=valcap & (minloadfrac > 0) & ~is_storage,
        name="eq_mingen",
    )
    del minloadfrac, is_vre

    gen_by_region = gen @ I
    charge_by_region = charge @ I
    imports_by_region = (flow @ R_from).relabel_axis(R_to, R)
    exports_by_region = (flow @ R_to).relabel_axis(R_from, R)
    model.add_constraints(
        gen_by_region
        + tranloss_factor * imports_by_region
        - exports_by_region
        - charge_by_region
        == load,
        name="eq_supply_demand_balance",
    )
    del (
        gen_by_region,
        charge_by_region,
        imports_by_region,
        exports_by_region,
        flow,
        load,
    )
    model.add_constraints(
        (cap @ I) >= reserve_margin_factor * peak_load,
        name="eq_reserve_margin",
    )
    del peak_load
    model.add_constraints(
        (emit_rate * hours_weight * gen) @ (I, R, H) <= emit_cap,
        name="eq_emit_cap",
    )
    del emit_rate, emit_cap
    model.add_constraints(
        rampup >= np.diff(gen, axis=H),
        active=dispatch_active,
        name="eq_ramping",
    )
    del dispatch_active, is_dispatch
    model.add_constraints(
        (hours_weight * gen) @ H >= min_cf * total_hours_weight * cap,
        active=valcap & (min_cf > 0),
        name="eq_min_cf",
    )
    del min_cf, total_hours_weight
    model.add_constraints(
        soc <= duration_h * cap,
        active=storage_active,
        name="eq_soc_cap",
    )
    model.add_constraints(
        charge <= cap,
        active=storage_active,
        name="eq_charge_cap",
    )
    del cap
    model.add_constraints(
        np.roll(soc, -1, axis=H) == soc + charge_eff * charge - gen,
        active=storage_active,
        name="eq_soc",
    )
    del charge, soc, storage_active, is_storage

    objective = (pvf * cost_inv * inv).sum()
    model.minimize(objective)
    del objective, cost_inv, inv
    objective = (pvf * cost_op * hours_weight * gen).sum()
    model.add_objective_terms(objective)
    del objective, cost_op, gen, hours_weight
    objective = (pvf * startcost * rampup).sum()
    model.add_objective_terms(objective)
    del objective, rampup, startcost, pvf

    build_s = time.perf_counter() - t0
    if build_only:
        return float("nan"), build_s, 0.0

    del (
        data,
        valcap,
        I,
        R,
        H,
        T,
        H_ramp,
        R_from,
        R_to,
        regions,
        techs,
        hours,
        years,
        region_index,
    )
    gc.collect()
    build_s = time.perf_counter() - t0

    highs_kwargs = {
        "log_to_console": False,
        "parameters": {
            "solver": highs_solver,
            "arco.consume_model": "true",
            "arco.fingerprint": "false",
            "arco.extract_solution": "false",
        },
    }
    if time_limit is not None:
        highs_kwargs["time_limit"] = time_limit
    if presolve is not None:
        highs_kwargs["presolve"] = presolve
    if threads is not None:
        highs_kwargs["threads"] = threads
    if highs_run_crossover is not None:
        highs_kwargs["parameters"]["run_crossover"] = highs_run_crossover
    if highs_load_path is not None:
        highs_kwargs["parameters"]["arco.highs_load_path"] = highs_load_path

    objective_only_parameters = {
        "arco.consume_model": "true",
        "arco.fingerprint": "false",
        "arco.extract_solution": "false",
    }
    scip_kwargs = {"log_to_console": False}
    xpress_kwargs = {
        "log_to_console": False,
        "parameters": objective_only_parameters,
    }
    if xpress_lp_algorithm is not None:
        xpress_kwargs["parameters"] = {
            **objective_only_parameters,
            "xpress.lp_algorithm": xpress_lp_algorithm,
        }
    for kwargs in (scip_kwargs, xpress_kwargs):
        if time_limit is not None:
            kwargs["time_limit"] = time_limit
        if presolve is not None:
            kwargs["presolve"] = presolve
        if threads is not None:
            kwargs["threads"] = threads

    if solver == "highs":
        selected_solver = arco.HiGHS(**highs_kwargs)
    elif solver == "scip":
        selected_solver = arco.Scip(**scip_kwargs)
    else:
        selected_solver = arco.Xpress(**xpress_kwargs)

    t1 = time.perf_counter()
    result = model.solve(solver=selected_solver)
    solve_s = time.perf_counter() - t1

    LAST_SOLVE_METADATA = dict(result.metadata)
    LAST_SOLVE_STATUS = str(result.status)

    if require_optimal and not result.is_optimal():
        raise RuntimeError(
            f"{solver} did not find an optimal solution: {result.status}"
        )

    objective_value = _objective_value_for_reporting(
        float(result.objective_value), LAST_SOLVE_METADATA
    )
    return objective_value, build_s, solve_s


class ArcoProbePayload(TypedDict):
    objective: float | None
    build_s: float
    solve_s: float
    status: NotRequired[str]
    solve_metadata: NotRequired[dict[str, float]]


def solve_probe(
    data: ProblemData,
    solver: str = "highs",
    *,
    time_limit: float | None = None,
    presolve: bool | None = None,
    threads: int | None = None,
    highs_solver: str = "ipm",
    xpress_lp_algorithm: str | None = None,
    highs_load_path: str | None = None,
) -> ArcoProbePayload:
    objective, build_s, solve_s = solve(
        data,
        solver=solver,
        build_only=False,
        time_limit=time_limit,
        presolve=presolve,
        threads=threads,
        highs_solver=highs_solver,
        highs_load_path=highs_load_path,
        xpress_lp_algorithm=xpress_lp_algorithm,
        require_optimal=False,
    )
    payload: ArcoProbePayload = {
        "objective": None if objective != objective else objective,
        "build_s": build_s,
        "solve_s": solve_s,
    }
    if LAST_SOLVE_STATUS is not None:
        payload["status"] = LAST_SOLVE_STATUS
    if LAST_SOLVE_METADATA:
        payload["solve_metadata"] = LAST_SOLVE_METADATA
    return payload


if __name__ == "__main__":
    import sys

    sys.path.insert(0, __file__.rsplit("\\", 1)[0])
    from data_generator import make_problem

    for size in ("small", "medium", "large", "xlarge"):
        data = make_problem(size)
        obj, b, s = solve(data)
        print(
            f"{size:6s}  obj={_format_objective_value(obj)}  "
            f"build={b:.3f}s  solve={s:.3f}s"
        )
