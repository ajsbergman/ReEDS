#!/usr/bin/env python3
"""Create a markdown benchmark comparison table from framework CSV results."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path


NUMERIC_COLUMNS = ("build_s", "solve_s", "total_s", "peak_mb", "objective")
SIZE_ORDER = {"small": 0, "medium": 1, "large": 2, "xlarge": 3}


def fmt_float(value: str) -> str:
    """Format a string value as a 3-decimal float, or return the original if not numeric.

    Parameters
    ----------
    value : str
        Raw cell value from a CSV row.

    Returns
    -------
    str
        Three-decimal representation, empty string for blank/None, or the
        original string when conversion fails.

    Examples
    --------
    >>> fmt_float("1.23456")
    '1.235'
    >>> fmt_float("")
    ''
    >>> fmt_float("n/a")
    'n/a'
    """
    if value is None:
        return ""
    stripped = value.strip()
    if not stripped:
        return ""
    try:
        number = float(stripped)
    except ValueError:
        return stripped
    return f"{number:.3f}"


def pick_input(path: Path) -> Path:
    """Resolve the input CSV path, auto-selecting the latest file when given a directory.

    Parameters
    ----------
    path : Path
        A CSV file path or a directory containing ``benchmark_*.csv`` files.

    Returns
    -------
    Path
        The resolved CSV file to read.

    Raises
    ------
    FileNotFoundError
        When ``path`` is a directory with no matching ``benchmark_*.csv`` files.

    Examples
    --------
    >>> import pathlib
    >>> pick_input(pathlib.Path("results/benchmark_20260519.csv"))  # doctest: +SKIP
    PosixPath('results/benchmark_20260519.csv')
    """
    if path.is_file():
        return path
    candidates = sorted(path.glob("benchmark_*.csv"))
    if not candidates:
        raise FileNotFoundError(f"No benchmark_*.csv files found under: {path}")
    return candidates[-1]


def framework_name(row: dict[str, str]) -> str:
    """Return a display name for the framework/solver combination in a result row.

    Parameters
    ----------
    row : dict[str, str]
        A CSV row dictionary. Newer result pulls use ``label`` instead of a
        precomputed ``framework`` column.

    Returns
    -------
    str
        Hyphen-separated framework name without a trailing size suffix.

    Examples
    --------
    >>> framework_name({"framework": "linopy-highs", "size": "small"})
    'linopy-highs'
    >>> framework_name({"label": "linopy_highs_small", "size": "small"})
    'linopy-highs'
    """
    framework = (row.get("framework") or "").strip()
    if framework:
        return framework

    module = (row.get("module") or "").strip()
    solver = (row.get("solver") or "").strip()
    if module and solver:
        return f"{module.removeprefix('solve_').replace('_', '-')}-{solver}"

    label = (row.get("label") or "").strip()
    size = (row.get("size") or "").strip()
    suffix = f"_{size}"
    if size and label.endswith(suffix):
        label = label[: -len(suffix)]
    return label.replace("_", "-")


def row_status(row: dict[str, str]) -> str:
    """Return the pass/fail status string for a result row.

    Parameters
    ----------
    row : dict[str, str]
        A CSV row dictionary with an optional ``error`` field.

    Returns
    -------
    str
        ``'failed'`` when the ``error`` field is non-empty, ``'ok'`` otherwise.

    Examples
    --------
    >>> row_status({"error": ""})
    'ok'
    >>> row_status({"error": "timeout"})
    'failed'
    """
    return "failed" if (row.get("error") or "").strip() else "ok"


def truncate(text: str, *, max_len: int = 80) -> str:
    """Collapse whitespace in text and truncate to a maximum length.

    Parameters
    ----------
    text : str
        Input string, may contain newlines or repeated spaces.
    max_len : int, default=80
        Maximum character length of the returned string.

    Returns
    -------
    str
        Whitespace-collapsed string, truncated with ``…`` when over ``max_len``.

    Examples
    --------
    >>> truncate("hello world", max_len=7)
    'hello …'
    >>> truncate("short")
    'short'
    """
    clean = " ".join(text.split())
    if len(clean) <= max_len:
        return clean
    return clean[: max_len - 1] + "…"


def build_table(input_csv: Path) -> str:
    """Build a markdown comparison table from a benchmark CSV file.

    Parameters
    ----------
    input_csv : Path
        Path to a CSV file with benchmark result rows.

    Returns
    -------
    str
        Markdown-formatted table string, including a heading and source line.

    Examples
    --------
    >>> import pathlib
    >>> table = build_table(pathlib.Path("results/benchmark_20260519.csv"))  # doctest: +SKIP
    >>> table.startswith("# Benchmark")  # doctest: +SKIP
    True
    """
    with input_csv.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    rows.sort(
        key=lambda r: (SIZE_ORDER.get(r.get("size", ""), 99), framework_name(r))
    )

    header = [
        "framework",
        "size",
        "status",
        "build_s",
        "solve_s",
        "total_s",
        "peak_mb",
        "objective",
        "error",
    ]

    markdown = [
        f"# Benchmark comparison table\n",
        f"Source: `{input_csv}`\n",
        "| " + " | ".join(header) + " |",
        "| " + " | ".join(["---"] * len(header)) + " |",
    ]

    for row in rows:
        out = {
            "framework": framework_name(row),
            "size": row.get("size", ""),
            "status": row_status(row),
            "error": truncate(row.get("error", "")),
        }
        for col in NUMERIC_COLUMNS:
            out[col] = fmt_float(row.get(col, ""))

        markdown.append(
            "| "
            + " | ".join(out.get(col, "") for col in header)
            + " |"
        )

    return "\n".join(markdown) + "\n"


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments for the benchmark table generator.

    Returns
    -------
    argparse.Namespace
        Parsed arguments with ``input`` and ``output`` fields.

    Examples
    --------
    >>> import sys
    >>> sys.argv = ["prog", "results/"]
    >>> args = parse_args()
    >>> args.input
    'results/'
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "input",
        nargs="?",
        default="tests/framework_comparison/results",
        help="CSV file or directory containing benchmark_*.csv (default: results directory)",
    )
    parser.add_argument(
        "-o",
        "--output",
        default="",
        help="Optional output markdown file path. Prints to stdout if omitted.",
    )
    return parser.parse_args()


def main() -> int:
    """Entry point: parse arguments, build table, and write or print output.

    Returns
    -------
    int
        Exit code: 0 on success.

    Examples
    --------
    >>> import sys
    >>> sys.argv = ["prog", "--help"]  # doctest: +SKIP
    """
    args = parse_args()
    selected_input = pick_input(Path(args.input))
    table = build_table(selected_input)

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(table, encoding="utf-8")
        print(f"Wrote {output_path}")
    else:
        print(table)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
