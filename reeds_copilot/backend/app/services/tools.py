"""Chat tools – read-only functions the LLM can invoke during conversation.

Tools are registered via the ``@tool`` decorator from
:mod:`app.services.tool_registry`.  Importing this module is enough to
populate the global registry.
"""
from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from .tool_registry import registry, tool  # noqa: F401 – import triggers registration

log = logging.getLogger(__name__)

# ── Attachment helpers ────────────────────────────────────────────────────────

def _img_attachment(rel_path: str, caption: str = "") -> dict:
    return {"type": "image", "path": rel_path, "caption": caption}

def _csv_attachment(headers: list[str], rows: list[list], title: str = "") -> dict:
    return {"type": "csv_table", "headers": headers, "rows": rows, "title": title}

def _file_links(files: list[dict]) -> dict:
    return {"type": "file_list", "files": files}

def _run_card(run_name: str, status: str, detail: str = "") -> dict:
    return {"type": "run_card", "run_name": run_name, "status": status, "detail": detail}


# ── Shared helpers ────────────────────────────────────────────────────────────

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp"}


def _safe_run_path(repo_root: Path, run_name: str) -> Path | None:
    """Resolve a run name to its path, return None if invalid/missing."""
    import re
    if not re.match(r"^[a-zA-Z0-9_\-\.]+$", run_name):
        return None
    p = repo_root / "runs" / run_name
    return p if p.is_dir() else None


# ── Tool implementations ──────────────────────────────────────────────────────

@tool(
    description=(
        "List output files in a completed ReEDS run's outputs directory. "
        "Returns file names, sizes, and relative paths. "
        "Use this when a user asks about results, outputs, or figures from a specific run."
    ),
    parameters={
        "run_name": {
            "type": "string",
            "description": "Name of the run folder (e.g. 'test_Pacific').",
        },
        "subdirectory": {
            "type": "string",
            "description": "Optional subdirectory within outputs/ to list (e.g. 'figures', 'comparisons'). Defaults to listing top-level outputs.",
            "default": "",
        },
        "pattern": {
            "type": "string",
            "description": "Optional glob pattern to filter files (e.g. '*.png', '*.csv'). Defaults to all files.",
            "default": "*",
        },
    },
    required=["run_name"],
)
def list_run_outputs(repo_root: Path, run_name: str, subdirectory: str = "", pattern: str = "*") -> tuple[str, list[dict]]:
    """Return (text_summary, attachments)."""
    run_dir = _safe_run_path(repo_root, run_name)
    if not run_dir:
        return f"Run '{run_name}' not found.", []

    out_dir = run_dir / "outputs"
    if subdirectory:
        out_dir = out_dir / subdirectory
    if not out_dir.is_dir():
        return f"No outputs directory found at runs/{run_name}/outputs/{subdirectory}.", []

    files = []
    for f in sorted(out_dir.glob(pattern)):
        if f.is_file():
            rel = str(f.relative_to(repo_root)).replace("\\", "/")
            files.append({
                "name": f.name,
                "path": rel,
                "size": f.stat().st_size,
                "suffix": f.suffix.lower(),
            })
    if not files:
        return f"No files matching '{pattern}' in runs/{run_name}/outputs/{subdirectory}.", []

    # Group by type
    images = [f for f in files if f["suffix"] in IMAGE_SUFFIXES]
    csvs = [f for f in files if f["suffix"] == ".csv"]
    others = [f for f in files if f not in images and f not in csvs]

    lines = [f"Found {len(files)} files in `runs/{run_name}/outputs/{subdirectory}`:"]
    if images:
        lines.append(f"- {len(images)} images")
    if csvs:
        lines.append(f"- {len(csvs)} CSV files")
    if others:
        lines.append(f"- {len(others)} other files")

    summary = "\n".join(lines)
    attachments = [_file_links(files[:50])]  # cap at 50 to avoid huge payloads
    return summary, attachments


@tool(
    description=(
        "Find and display a figure/image from a ReEDS run's outputs. "
        "Returns the image path for embedding in the response. "
        "Use this when a user asks to see a plot, chart, figure, or visualization."
    ),
    parameters={
        "run_name": {
            "type": "string",
            "description": "Name of the run folder.",
        },
        "figure_name": {
            "type": "string",
            "description": "Partial name or keyword to match (e.g. 'generation', 'capacity', 'transmission'). Case-insensitive.",
        },
    },
    required=["run_name", "figure_name"],
)
def show_figure(repo_root: Path, run_name: str, figure_name: str) -> tuple[str, list[dict]]:
    """Find and return a figure matching the name pattern."""
    run_dir = _safe_run_path(repo_root, run_name)
    if not run_dir:
        return f"Run '{run_name}' not found.", []

    keyword = figure_name.lower()
    matches = []
    for f in (run_dir / "outputs").rglob("*"):
        if f.is_file() and f.suffix.lower() in IMAGE_SUFFIXES:
            if keyword in f.stem.lower():
                matches.append(f)

    if not matches:
        return f"No figures matching '{figure_name}' in runs/{run_name}/outputs/.", []

    # Prefer files in figures/ subdir, then sort by name length (most specific first)
    def sort_key(f: Path) -> tuple[int, int]:
        in_figures = 0 if "figures" in f.parts else 1
        return (in_figures, len(f.name))
    matches.sort(key=sort_key)

    attachments = []
    shown = []
    for f in matches[:3]:  # show up to 3
        rel = str(f.relative_to(repo_root)).replace("\\", "/")
        attachments.append(_img_attachment(rel, f.stem))
        shown.append(f.name)

    remaining = len(matches) - len(shown)
    text = f"Found {len(matches)} figure(s) matching '{figure_name}'. Showing {len(shown)}."
    if remaining > 0:
        text += f" ({remaining} more available)"
    return text, attachments


@tool(
    description=(
        "Read a CSV file from the repository and return a preview. "
        "Useful for showing input data, output results, or configuration files. "
        "Returns column names and the first N rows."
    ),
    parameters={
        "path": {
            "type": "string",
            "description": "Relative path from the repo root (e.g. 'runs/test_Pacific/outputs/cap.csv').",
        },
        "head": {
            "type": "integer",
            "description": "Number of rows to return. Default 20, max 100.",
            "default": 20,
        },
    },
    required=["path"],
)
def read_csv_data(repo_root: Path, path: str, head: int = 20) -> tuple[str, list[dict]]:
    """Read a CSV and return a preview."""
    head = min(max(head, 1), 100)
    try:
        resolved = (repo_root / path).resolve()
        if not str(resolved).startswith(str(repo_root.resolve())):
            return "Path escapes repository root.", []
    except Exception:
        return f"Invalid path: {path}", []

    if not resolved.is_file():
        return f"File not found: {path}", []
    if resolved.suffix.lower() != ".csv":
        return f"Not a CSV file: {path}", []
    if resolved.stat().st_size > 50 * 1024 * 1024:
        return "File too large (>50 MB).", []

    try:
        df = pd.read_csv(resolved, nrows=head)
    except Exception as exc:
        return f"Error reading CSV: {exc}", []

    headers = list(df.columns)
    rows = df.fillna("").values.tolist()

    total_lines = sum(1 for _ in open(resolved, encoding="utf-8", errors="replace")) - 1
    text = f"`{path}`: {total_lines:,} rows × {len(headers)} columns. Showing first {len(rows)}:"
    attachments = [_csv_attachment(headers, rows, title=Path(path).name)]
    return text, attachments


@tool(
    description=(
        "Get the status and metadata of a ReEDS run. "
        "Returns whether the run exists, its status (running/completed/failed), "
        "and key details like solve years and runtime."
    ),
    parameters={
        "run_name": {
            "type": "string",
            "description": "Name of the run folder.",
        },
    },
    required=["run_name"],
)
def get_run_status(repo_root: Path, run_name: str) -> tuple[str, list[dict]]:
    """Get run status info."""
    run_dir = _safe_run_path(repo_root, run_name)
    if not run_dir:
        return f"Run '{run_name}' not found in runs/ directory.", []

    # Check for common status indicators
    outputs_dir = run_dir / "outputs"
    has_outputs = outputs_dir.is_dir() and any(outputs_dir.iterdir()) if outputs_dir.is_dir() else False

    # Try to read meta.csv or similar
    meta = {}
    meta_file = run_dir / "meta.csv"
    if meta_file.is_file():
        try:
            df = pd.read_csv(meta_file)
            if len(df) > 0:
                meta = df.iloc[0].to_dict()
        except Exception:
            pass

    # Check for gamslog
    gamslog = run_dir / "gamslog.lst"
    log_tail = ""
    if gamslog.is_file():
        try:
            lines = gamslog.read_text(encoding="utf-8", errors="replace").splitlines()
            log_tail = "\n".join(lines[-5:])
        except Exception:
            pass

    status = "completed" if has_outputs else "unknown"
    detail_parts = [f"Run: `{run_name}`", f"Status: {status}"]
    if has_outputs:
        n_files = sum(1 for f in outputs_dir.rglob("*") if f.is_file())
        detail_parts.append(f"Output files: {n_files}")
    if meta:
        for k, v in list(meta.items())[:5]:
            detail_parts.append(f"{k}: {v}")
    if log_tail:
        detail_parts.append(f"Last log lines:\n```\n{log_tail}\n```")

    text = "\n".join(detail_parts)
    attachments = [_run_card(run_name, status, text)]
    return text, attachments


@tool(
    description=(
        "List all available ReEDS run folders. "
        "Use this when the user asks what runs are available or when you need to find cases."
    ),
)
def list_runs(repo_root: Path) -> tuple[str, list[dict]]:
    """List all run folders."""
    runs_dir = repo_root / "runs"
    if not runs_dir.is_dir():
        return "No runs/ directory found.", []

    runs = []
    for d in sorted(runs_dir.iterdir()):
        if d.is_dir() and not d.name.startswith("."):
            has_outputs = (d / "outputs").is_dir()
            runs.append({"name": d.name, "has_outputs": has_outputs})

    if not runs:
        return "No run folders found.", []

    lines = [f"Found {len(runs)} run(s):"]
    for r in runs:
        mark = "✅" if r["has_outputs"] else "⏳"
        lines.append(f"- {mark} `{r['name']}`")

    return "\n".join(lines), []
