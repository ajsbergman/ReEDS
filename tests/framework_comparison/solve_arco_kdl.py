"""
Arco KDL implementation of the ReEDS-representative LP test problem.

The static formulation lives in reeds_arco.kdl. This module only materializes the
benchmark data to temporary CSV fixtures and invokes the Arco CLI.
"""

from __future__ import annotations

import json
import math
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from data_generator import ProblemData
from solve_arco_utils import OBJ_SCALE, materialize_arco_kdl_case


def _arco_executable() -> str:
    exe = shutil.which("arco")
    if exe is None:
        raise RuntimeError("Arco CLI not found on PATH; install or expose `arco`")
    return exe


def solve(
    data: ProblemData, solver: str = "highs", build_only: bool = False
) -> tuple[float, float, float]:
    if solver != "highs":
        raise ValueError("solve_arco_kdl only supports solver='highs'")

    with tempfile.TemporaryDirectory(prefix="reeds_arco_kdl_") as tmp:
        workdir = Path(tmp)
        t0 = time.perf_counter()
        kdl_path = materialize_arco_kdl_case(data, workdir)
        materialize_s = time.perf_counter() - t0

        if build_only:
            completed = subprocess.run(
                [_arco_executable(), "validate", str(kdl_path)],
                cwd=workdir,
                text=True,
                capture_output=True,
                check=False,
            )
            if completed.returncode != 0:
                raise RuntimeError(completed.stderr.strip() or completed.stdout.strip())
            return float("nan"), materialize_s, 0.0

        completed = subprocess.run(
            [_arco_executable(), "run", str(kdl_path), "--compact"],
            cwd=workdir,
            text=True,
            capture_output=True,
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError(completed.stderr.strip() or completed.stdout.strip())

        payload = json.loads(completed.stdout)
        objective = payload.get("objective", {}).get("value")
        if objective is None or not math.isfinite(float(objective)):
            raise RuntimeError(f"Arco KDL solve did not return a finite objective: {payload}")

        timing = payload.get("timing", {})
        build_s = materialize_s + (
            float(timing.get("parse_ms", 0.0))
            + float(timing.get("validate_ms", 0.0))
            + float(timing.get("compile_ms", 0.0))
        ) / 1000.0
        solve_s = float(timing.get("solve_ms", 0.0)) / 1000.0
        return float(objective) * OBJ_SCALE, build_s, solve_s


if __name__ == "__main__":
    import sys

    sys.path.insert(0, __file__.rsplit("\\", 1)[0])
    from data_generator import make_problem

    for size in ("small", "medium", "large", "xlarge"):
        problem = make_problem(size)
        obj, b, s = solve(problem)
        print(f"{size:6s}  obj={obj:>18,.0f}  build={b:.3f}s  solve={s:.3f}s")
