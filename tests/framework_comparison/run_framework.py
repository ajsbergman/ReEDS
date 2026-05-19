"""
CLI adapter that runs one LP framework/solver combination and writes a JSON result.

Used by Torc job commands so each job is a thin wrapper over this script.

Usage
-----
    python run_framework.py --module solve_linopy --solver highs --size medium \\
        --label linopy_highs --output results/linopy_highs_medium.json

Arguments
---------
--module     Python module name (solve_arco | solve_gams | solve_gamspy |
             solve_linopy | solve_pyomo | solve_pyoptinterface)
--solver     Solver to use (highs | scip | xpress | cplex). Default: highs.
--size       Problem size (small | medium | large | xlarge). Default: small.
--label      Human-readable run label written to the JSON.
             Default: <module>_<solver>.
--output     Output JSON path.
             Default: torc_output_matrix/framework_results/<label>_<size>.json
--build-only Build the model but skip solve (timing smoke-test).
"""

from __future__ import annotations

import argparse
import importlib
import json
import logging
import sys
import time
import traceback
from dataclasses import asdict, dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

VALID_MODULES = [
    "solve_arco",
    "solve_gams",
    "solve_gamspy",
    "solve_linopy",
    "solve_pyomo",
    "solve_pyoptinterface",
]


@dataclass(slots=True)
class FrameworkResult:
    """Structured result for one framework/solver/size benchmark run.

    Attributes
    ----------
    label : str
        Human-readable run identifier.
    module : str
        Framework module name (e.g. ``solve_linopy``).
    solver : str
        LP solver used (e.g. ``highs``).
    size : str
        Problem size key (e.g. ``small``).
    build_only : bool
        Whether the solve step was skipped.
    objective : float | None
        Optimal objective value, or ``None`` for build-only runs.
    build_s : float | None
        Model build time in seconds.
    solve_s : float | None
        Solver time in seconds.
    total_s : float | None
        Wall-clock time for the full run.
    error : str
        Traceback string on failure, empty string on success.
    """

    label: str
    module: str
    solver: str
    size: str
    build_only: bool
    objective: float | None = None
    build_s: float | None = None
    solve_s: float | None = None
    total_s: float | None = None
    error: str = ""


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments for the framework runner.

    Returns
    -------
    argparse.Namespace
        Parsed arguments with ``module``, ``solver``, ``size``, ``label``,
        ``output``, and ``build_only`` fields.

    Examples
    --------
    >>> import sys
    >>> sys.argv = ["prog", "--module", "solve_linopy", "--size", "small"]
    >>> args = parse_args()
    >>> args.module
    'solve_linopy'
    """
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--module",
        required=True,
        choices=VALID_MODULES,
        metavar="MODULE",
        help=f"Framework module: {' | '.join(VALID_MODULES)}",
    )
    parser.add_argument(
        "--solver",
        default="highs",
        help="LP solver (highs | scip | xpress | cplex). Default: highs.",
    )
    parser.add_argument(
        "--size",
        default="small",
        choices=["small", "medium", "large", "xlarge"],
        help="Problem size. Default: small.",
    )
    parser.add_argument(
        "--label",
        default="",
        help="Run label for the JSON result. Default: <module>_<solver>.",
    )
    parser.add_argument(
        "--output",
        default="",
        help=(
            "Output JSON path. "
            "Default: torc_output_matrix/framework_results/<label>_<size>.json"
        ),
    )
    parser.add_argument(
        "--build-only",
        action="store_true",
        help="Build the model without solving (timing smoke-test).",
    )
    return parser.parse_args()


def resolve_output(label: str, size: str, *, output_arg: str = "") -> Path:
    """Return the output JSON path, defaulting to the canonical Torc results dir.

    Parameters
    ----------
    label : str
        Run label used to construct the default filename.
    size : str
        Problem size used to construct the default filename.
    output_arg : str, default=""
        Explicit output path from the CLI. When non-empty, takes priority.

    Returns
    -------
    Path
        Resolved output path for the JSON result file.

    Examples
    --------
    >>> resolve_output("linopy_highs", "small", output_arg="/tmp/out.json")
    PosixPath('/tmp/out.json')
    >>> resolve_output("linopy_highs", "small").name
    'linopy_highs_small.json'
    """
    if output_arg:
        return Path(output_arg)
    return (
        Path(__file__).parent
        / "torc_output_matrix"
        / "framework_results"
        / f"{label}_{size}.json"
    )


def run_framework(
    module_name: str,
    solver: str,
    size: str,
    *,
    build_only: bool = False,
) -> FrameworkResult:
    """Import and invoke one framework's solve function, returning a structured result.

    Parameters
    ----------
    module_name : str
        One of ``VALID_MODULES`` (e.g. ``'solve_linopy'``).
    solver : str
        Solver identifier passed through to the framework (e.g. ``'highs'``).
    size : str
        Problem size key understood by ``data_generator.make_problem``.
    build_only : bool, default=False
        When ``True``, build the model but skip the solve step.

    Returns
    -------
    FrameworkResult
        Structured result with timing, objective, and error fields.

    Raises
    ------
    ImportError
        When ``module_name`` cannot be imported from the script directory.
    AttributeError
        When the imported module has no ``solve`` callable.

    Examples
    --------
    >>> result = run_framework("solve_linopy", "highs", "small")  # doctest: +SKIP
    >>> result.error
    ''
    >>> isinstance(result.build_s, float)
    True
    """
    from data_generator import make_problem  # noqa: PLC0415

    label = f"{module_name}_{solver}"
    t_wall = time.perf_counter()

    data = make_problem(size)
    mod = importlib.import_module(module_name)
    objective, build_s, solve_s = mod.solve(data, solver=solver, build_only=build_only)

    obj_out = None if objective != objective else float(objective)  # NaN → None
    return FrameworkResult(
        label=label,
        module=module_name,
        solver=solver,
        size=size,
        build_only=build_only,
        objective=obj_out,
        build_s=round(float(build_s), 4),
        solve_s=round(float(solve_s), 4),
        total_s=round(time.perf_counter() - t_wall, 4),
    )


def write_result(result: FrameworkResult, output_path: Path) -> None:
    """Serialise a FrameworkResult to a JSON file, creating parent directories.

    Parameters
    ----------
    result : FrameworkResult
        The result to persist.
    output_path : Path
        Destination file path.

    Returns
    -------
    None

    Examples
    --------
    >>> import pathlib, tempfile
    >>> r = FrameworkResult(label="l", module="m", solver="s", size="small", build_only=False)
    >>> with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
    ...     p = pathlib.Path(f.name)
    >>> write_result(r, p)  # doctest: +SKIP
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(asdict(result), indent=2), encoding="utf-8")


def main() -> int:
    """Entry point: run one framework/solver/size combination and write JSON.

    Returns
    -------
    int
        Always 0; failures are recorded in the JSON ``error`` field so Torc
        can distinguish adapter errors from job scheduling errors.

    Examples
    --------
    >>> import sys
    >>> sys.argv = ["prog", "--module", "solve_linopy", "--size", "small"]
    >>> main()  # doctest: +SKIP
    0
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(name)s %(levelname)s %(message)s",
    )

    args = parse_args()
    label = args.label or f"{args.module}_{args.solver}"
    output_path = resolve_output(label, args.size, output_arg=args.output)

    script_dir = str(Path(__file__).parent)
    if script_dir not in sys.path:
        sys.path.insert(0, script_dir)

    t_wall = time.perf_counter()
    try:
        result = run_framework(
            args.module,
            args.solver,
            args.size,
            build_only=args.build_only,
        )
        result.label = label  # apply user-supplied label override

    except (ImportError, AttributeError, RuntimeError) as exc:
        total_s = round(time.perf_counter() - t_wall, 4)
        result = FrameworkResult(
            label=label,
            module=args.module,
            solver=args.solver,
            size=args.size,
            build_only=args.build_only,
            total_s=total_s,
            error=traceback.format_exc(),
        )
        logger.error(
            '{"event": "run_failed", "label": "%s", "size": "%s", "error": "%s"}',
            label,
            args.size,
            str(exc),
        )
        write_result(result, output_path)
        return 0

    write_result(result, output_path)
    status = "build_only" if args.build_only else "ok"
    logger.info(
        '{"event": "run_complete", "status": "%s", "label": "%s", "size": "%s",'
        ' "obj": %s, "build_s": %s, "solve_s": %s}',
        status,
        label,
        args.size,
        result.objective,
        result.build_s,
        result.solve_s,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
