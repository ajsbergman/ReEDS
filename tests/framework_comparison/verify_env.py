"""
Environment verification for framework comparison.

Solves the small test problem with each framework and cross-checks
that all objective values agree within tolerance.

Run from repo root:
    python tests/framework_comparison/verify_env.py

or from this directory:
    python verify_env.py
"""

from __future__ import annotations
import importlib
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ---------------------------------------------------------------------------
# 1. Import check
# ---------------------------------------------------------------------------

REQUIRED = {
    "linopy":         "linopy",
    "pyomo":          "pyomo.environ",
    "pyoptinterface": "pyoptinterface",
    "gamspy":         "gamspy",
    "highspy":        "highspy",
    "numpy":          "numpy",
    "xarray":         "xarray",
    "psutil":         "psutil",
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
# 2. Solve the small problem with each framework
# ---------------------------------------------------------------------------

from data_generator import make_problem
from solve_linopy import solve as solve_linopy
from solve_pyomo import solve as solve_pyomo
from solve_pyoptinterface import solve as solve_pyoptinterface
from solve_gamspy import solve as solve_gamspy

data = make_problem("small")
print(f"Problem: {data.summary()}")
print()

ATOL_REL = 1e-3

SOLVERS = [
    ("linopy",         lambda: solve_linopy(data)),
    ("pyomo",          lambda: solve_pyomo(data)),
    ("pyoptinterface", lambda: solve_pyoptinterface(data)),
    ("gamspy (highs)", lambda: solve_gamspy(data, solver="highs")),
    ("gamspy (cplex)", lambda: solve_gamspy(data, solver="cplex")),
]

print("=" * 60)
print("Solving with each framework (small problem)")
print("=" * 60)

results: dict[str, float | None] = {}
for name, fn in SOLVERS:
    try:
        obj, build_s, solve_s = fn()
        results[name] = obj
        print(f"  {name:<22} obj={obj:>15,.0f}  "
              f"build={build_s:.3f}s  solve={solve_s:.3f}s")
    except Exception as exc:
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
        print("All frameworks agree. Environment is ready.")
    else:
        print("WARNING: Objective values differ — check solver status or formulation.")
else:
    print("Fewer than 2 frameworks succeeded.")
