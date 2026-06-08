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
--time-limit Optional solver time limit in seconds for modules that support it.
--presolve   Optional presolve override for modules that support it.
--threads    Optional solver thread count for modules that support it.
             Defaults to SLURM_CPUS_PER_TASK when set.
--highs-solver
             Optional HiGHS algorithm selector for modules that support it.
--highs-run-crossover
             Optional HiGHS crossover selector for modules that support it.
--highs-load-path
             Optional Arco-to-HiGHS load-path selector for modules that support it.
--xpress-lp-algorithm
             Optional Arco/Xpress LP algorithm selector for modules that support it.
--allow-nonoptimal
             Record non-optimal solver statuses instead of failing when supported.
"""

from __future__ import annotations

import argparse
import inspect
import importlib
import json
import logging
import os
import resource
import sys
import time
import traceback
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

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
    status : str
        Solver status when the framework exposes one.
    peak_rss_mb : float | None
        Peak process RSS in MB at result creation.
    solve_metadata : dict[str, float] | None
        Backend timing and shape metadata when the framework exposes it.
    framework_metadata : dict[str, object] | None
        Framework-specific provenance such as package versions and solver runtime info.
    run_options : dict[str, object] | None
        Solver and runner options requested for this run.
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
    status: str = ""
    peak_rss_mb: float | None = None
    solve_metadata: dict[str, float] | None = None
    framework_metadata: dict[str, Any] | None = None
    run_options: dict[str, Any] | None = None
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
    parser.add_argument(
        "--time-limit",
        type=float,
        default=None,
        help="Optional solver time limit in seconds when the selected module supports it.",
    )
    parser.add_argument(
        "--presolve",
        choices=("on", "off"),
        default=None,
        help="Optional presolve override when the selected module supports it.",
    )
    parser.add_argument(
        "--threads",
        type=positive_int,
        default=None,
        help=(
            "Optional solver thread count when the selected module supports it. "
            "Default: SLURM_CPUS_PER_TASK when set."
        ),
    )
    parser.add_argument(
        "--highs-solver",
        choices=("ipm", "simplex", "choose", "pdlp"),
        default=None,
        help="Optional HiGHS algorithm selector when the selected module supports it.",
    )
    parser.add_argument(
        "--highs-run-crossover",
        choices=("on", "off", "choose"),
        default=None,
        help="Optional HiGHS run_crossover selector when the selected module supports it.",
    )
    parser.add_argument(
        "--highs-load-path",
        choices=("wrapper", "direct"),
        default=None,
        help="Optional Arco-to-HiGHS load-path selector when the selected module supports it.",
    )
    parser.add_argument(
        "--xpress-lp-algorithm",
        choices=(
            "auto",
            "primal",
            "dual",
            "barrier",
            "primal_barrier",
            "dual_barrier",
            "primal_dual",
            "all",
        ),
        default=None,
        help="Optional Xpress LP algorithm selector when the selected module supports it.",
    )
    parser.add_argument(
        "--allow-nonoptimal",
        action="store_true",
        help="Record non-optimal solver statuses instead of treating them as errors when supported.",
    )
    return parser.parse_args()


def positive_int(value: str) -> int:
    """Return a positive integer CLI argument value.

    Examples
    --------
    >>> positive_int("4")
    4
    >>> positive_int("0")
    Traceback (most recent call last):
    ...
    argparse.ArgumentTypeError: value must be >= 1
    """
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("value must be an integer") from exc
    if parsed < 1:
        raise argparse.ArgumentTypeError("value must be >= 1")
    return parsed


def default_threads_from_environment() -> int | None:
    """Return Slurm's allocated CPU count when it is a valid positive integer.

    Examples
    --------
    >>> import os
    >>> original = os.environ.get("SLURM_CPUS_PER_TASK")
    >>> os.environ["SLURM_CPUS_PER_TASK"] = "8"
    >>> default_threads_from_environment()
    8
    >>> os.environ["SLURM_CPUS_PER_TASK"] = ""
    >>> default_threads_from_environment() is None
    True
    >>> if original is None:
    ...     _ = os.environ.pop("SLURM_CPUS_PER_TASK", None)
    ... else:
    ...     os.environ["SLURM_CPUS_PER_TASK"] = original
    """
    value = os.environ.get("SLURM_CPUS_PER_TASK", "").strip()
    if not value:
        return None
    try:
        threads = int(value)
    except ValueError:
        return None
    if threads < 1:
        return None
    return threads


def current_peak_rss_mb() -> float:
    """Return peak RSS in MB for this process or completed child processes."""
    max_rss = max(
        float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss),
        float(resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss),
    )
    if sys.platform == "darwin":
        return max_rss / (1024.0 * 1024.0)
    return max_rss / 1024.0


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


def run_options_metadata(
    *,
    time_limit: float | None,
    presolve: str | None,
    threads: int | None,
    highs_solver: str | None,
    highs_run_crossover: str | None,
    highs_load_path: str | None,
    xpress_lp_algorithm: str | None,
    allow_nonoptimal: bool,
) -> dict[str, Any]:
    """Return structured run-option provenance for JSON/CSV comparison."""
    return {
        "time_limit": time_limit,
        "presolve": presolve,
        "threads": threads,
        "highs_solver": highs_solver,
        "highs_run_crossover": highs_run_crossover,
        "highs_load_path": highs_load_path,
        "xpress_lp_algorithm": xpress_lp_algorithm,
        "allow_nonoptimal": allow_nonoptimal,
    }


def module_framework_metadata(module_name: str) -> dict[str, Any] | None:
    """Return framework metadata exposed by a module when available."""
    try:
        mod = importlib.import_module(module_name)
    except Exception:
        return None
    metadata = getattr(mod, "LAST_FRAMEWORK_METADATA", None)
    if isinstance(metadata, dict) and metadata:
        return metadata
    return None


def run_framework(
    module_name: str,
    solver: str,
    size: str,
    *,
    build_only: bool = False,
    time_limit: float | None = None,
    presolve: str | None = None,
    threads: int | None = None,
    highs_solver: str | None = None,
    highs_run_crossover: str | None = None,
    highs_load_path: str | None = None,
    xpress_lp_algorithm: str | None = None,
    allow_nonoptimal: bool = False,
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
    >>> isinstance(run_framework("solve_linopy", "highs", "small").build_s, float)  # doctest: +SKIP
    True
    """
    from data_generator import make_problem  # noqa: PLC0415

    label = f"{module_name}_{solver}"
    t_wall = time.perf_counter()
    run_options = run_options_metadata(
        time_limit=time_limit,
        presolve=presolve,
        threads=threads,
        highs_solver=highs_solver,
        highs_run_crossover=highs_run_crossover,
        highs_load_path=highs_load_path,
        xpress_lp_algorithm=xpress_lp_algorithm,
        allow_nonoptimal=allow_nonoptimal,
    )

    mod = importlib.import_module(module_name)
    solve = mod.solve
    solve_kwargs = {"solver": solver, "build_only": build_only}
    solve_signature = inspect.signature(solve)
    if time_limit is not None and "time_limit" in solve_signature.parameters:
        solve_kwargs["time_limit"] = time_limit
    if presolve is not None and "presolve" in solve_signature.parameters:
        solve_kwargs["presolve"] = presolve == "on"
    if threads is not None and "threads" in solve_signature.parameters:
        solve_kwargs["threads"] = threads
    if highs_solver is not None and "highs_solver" in solve_signature.parameters:
        solve_kwargs["highs_solver"] = highs_solver
    if (
        highs_run_crossover is not None
        and "highs_run_crossover" in solve_signature.parameters
    ):
        solve_kwargs["highs_run_crossover"] = highs_run_crossover
    if highs_load_path is not None and "highs_load_path" in solve_signature.parameters:
        solve_kwargs["highs_load_path"] = (
            None if highs_load_path == "wrapper" else highs_load_path
        )
    if (
        xpress_lp_algorithm is not None
        and "xpress_lp_algorithm" in solve_signature.parameters
    ):
        solve_kwargs["xpress_lp_algorithm"] = xpress_lp_algorithm
    if "require_optimal" in solve_signature.parameters:
        solve_kwargs["require_optimal"] = not allow_nonoptimal
    objective, build_s, solve_s = solve(make_problem(size), **solve_kwargs)

    obj_out = None if objective != objective else float(objective)  # NaN → None
    status = getattr(mod, "LAST_SOLVE_STATUS", None) or (
        "" if build_only else "optimal"
    )
    solve_metadata = getattr(mod, "LAST_SOLVE_METADATA", None) or None
    framework_metadata = module_framework_metadata(module_name)
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
        status=status,
        peak_rss_mb=round(current_peak_rss_mb(), 3),
        solve_metadata=solve_metadata,
        framework_metadata=framework_metadata,
        run_options=run_options,
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
    threads = args.threads if args.threads is not None else default_threads_from_environment()
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
            time_limit=args.time_limit,
            presolve=args.presolve,
            threads=threads,
            highs_solver=args.highs_solver,
            highs_run_crossover=args.highs_run_crossover,
            highs_load_path=args.highs_load_path,
            xpress_lp_algorithm=args.xpress_lp_algorithm,
            allow_nonoptimal=args.allow_nonoptimal,
        )
        result.label = label  # apply user-supplied label override

    except Exception as exc:
        total_s = round(time.perf_counter() - t_wall, 4)
        result = FrameworkResult(
            label=label,
            module=args.module,
            solver=args.solver,
            size=args.size,
            build_only=args.build_only,
            total_s=total_s,
            peak_rss_mb=round(current_peak_rss_mb(), 3),
            framework_metadata=module_framework_metadata(args.module),
            run_options=run_options_metadata(
                time_limit=args.time_limit,
                presolve=args.presolve,
                threads=threads,
                highs_solver=args.highs_solver,
                highs_run_crossover=args.highs_run_crossover,
                highs_load_path=args.highs_load_path,
                xpress_lp_algorithm=args.xpress_lp_algorithm,
                allow_nonoptimal=args.allow_nonoptimal,
            ),
            error=traceback.format_exc(),
        )
        logger.error(
            '{"event": "run_failed", "label": "%s", "size": "%s", "error": "%s"}',
            label,
            args.size,
            str(exc),
        )
        write_result(result, output_path)
        return 1

    write_result(result, output_path)
    status = "build_only" if args.build_only else result.status or "ok"
    logger.info(
        '{"event": "run_complete", "status": "%s", "label": "%s", "size": "%s",'
        ' "obj": %s, "build_s": %s, "solve_s": %s, "peak_rss_mb": %s}',
        status,
        label,
        args.size,
        result.objective,
        result.build_s,
        result.solve_s,
        result.peak_rss_mb,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
