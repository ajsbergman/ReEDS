"""Shared utilities for Arco ReEDS benchmark implementations."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterable

from data_generator import ProblemData


OBJ_SCALE = 1e6
KDL_TEMPLATE = Path(__file__).with_name("reeds_arco.kdl")


def write_csv(path: Path, fieldnames: list[str], rows: Iterable[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def materialize_arco_kdl_case(data: ProblemData, workdir: Path) -> Path:
    """Write CSV fixtures and copy the static KDL entrypoint into *workdir*."""
    data_dir = workdir / "data"
    R, I, H, T = data.regions, data.techs, data.hours, data.years
    ri, ii, hi, ti = data.r_idx, data.i_idx, data.h_idx, data.t_idx

    ordinal_year = {year: pos + 1 for pos, year in enumerate(T)}
    ordinal_hour = {hour: pos + 1 for pos, hour in enumerate(H)}

    write_csv(
        data_dir / "tech.csv",
        [
            "i",
            "cost_inv",
            "cost_op",
            "startcost",
            "emit_rate",
            "minloadfrac",
            "min_cf",
            "is_storage",
            "is_dispatchable",
        ],
        (
            {
                "i": i,
                "cost_inv": data.cost_inv[ii[i]] / OBJ_SCALE,
                "cost_op": data.cost_op[ii[i]] / OBJ_SCALE,
                "startcost": data.startcost[ii[i]] / OBJ_SCALE,
                "emit_rate": data.emit_rate[ii[i]],
                "minloadfrac": data.minloadfrac[ii[i]],
                "min_cf": data.min_cf[ii[i]],
                "is_storage": int(data.is_storage[ii[i]]),
                "is_dispatchable": int(
                    (not data.is_vre[ii[i]]) and (not data.is_storage[ii[i]])
                ),
            }
            for i in I
        ),
    )
    write_csv(data_dir / "region.csv", ["r"], ({"r": r} for r in R))
    write_csv(
        data_dir / "hour.csv",
        ["h", "is_last"],
        (
            {"h": ordinal_hour[h], "is_last": int(pos == len(H) - 1)}
            for pos, h in enumerate(H)
        ),
    )
    write_csv(
        data_dir / "year.csv",
        ["t", "actual_year", "pvf", "emit_cap"],
        (
            {
                "t": ordinal_year[t],
                "actual_year": t,
                "pvf": data.pvf[ti[t]],
                "emit_cap": data.emit_cap[ti[t]],
            }
            for t in T
        ),
    )
    write_csv(
        data_dir / "ir.csv",
        ["i", "r", "cap_init"],
        (
            {"i": i, "r": r, "cap_init": data.cap_init[ii[i], ri[r]]}
            for i in I
            for r in R
        ),
    )
    write_csv(
        data_dir / "irt.csv",
        ["i", "r", "t", "valcap"],
        (
            {
                "i": i,
                "r": r,
                "t": ordinal_year[t],
                "valcap": int(data.valcap[ii[i], ri[r], ti[t]]),
            }
            for i in I
            for r in R
            for t in T
        ),
    )
    write_csv(
        data_dir / "irh.csv",
        ["i", "r", "h", "cf"],
        (
            {"i": i, "r": r, "h": ordinal_hour[h], "cf": data.cf[ii[i], ri[r], hi[h]]}
            for i in I
            for r in R
            for h in H
        ),
    )
    write_csv(
        data_dir / "rht.csv",
        ["r", "h", "t", "load"],
        (
            {
                "r": r,
                "h": ordinal_hour[h],
                "t": ordinal_year[t],
                "load": data.load[ri[r], hi[h], ti[t]],
            }
            for r in R
            for h in H
            for t in T
        ),
    )
    write_csv(
        data_dir / "rt.csv",
        ["r", "t", "peak_load"],
        (
            {
                "r": r,
                "t": ordinal_year[t],
                "peak_load": float(data.load[ri[r], :, ti[t]].max()),
            }
            for r in R
            for t in T
        ),
    )
    write_csv(
        data_dir / "hw.csv",
        ["h", "hours_weight"],
        ({"h": ordinal_hour[h], "hours_weight": data.hours_weight[hi[h]]} for h in H),
    )

    route_ids = [f"route{k}" for k in range(len(data.routes))]
    route_by_id = dict(zip(route_ids, data.routes, strict=True))
    write_csv(
        data_dir / "route.csv",
        ["route", "transcap"],
        ({"route": route, "transcap": data.transcap[route_by_id[route]]} for route in route_ids),
    )
    write_csv(
        data_dir / "route_region.csv",
        ["route", "r", "flow_coef"],
        (
            {
                "route": route,
                "r": r,
                "flow_coef": (
                    (1.0 - data.tranloss)
                    if route_by_id[route][1] == r
                    else (-1.0 if route_by_id[route][0] == r else 0.0)
                ),
            }
            for route in route_ids
            for r in R
        ),
    )

    kdl_path = workdir / "reeds_arco.kdl"
    kdl_path.write_text(KDL_TEMPLATE.read_text(encoding="utf-8"), encoding="utf-8")
    return kdl_path
