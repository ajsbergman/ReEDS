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


# ── Copilot-style filesystem exploration tools ───────────────────────────────
# These let the LLM verify that files actually exist and read exact lines
# instead of hallucinating paths or paraphrasing code from training data.

_EXPLORE_IGNORE_DIRS = {
    ".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build",
    ".pytest_cache", ".mypy_cache", ".ruff_cache", ".idea", ".vscode",
    "runs",  # run outputs are massive; use the run-specific tools instead
}
_EXPLORE_MAX_RESULTS = 80


def _explore_safe_path(repo_root: Path, rel_path: str) -> Path | None:
    """Resolve a path inside repo_root. Returns None if it escapes or is missing."""
    try:
        rel = (rel_path or "").strip().lstrip("/\\").replace("\\", "/")
        if not rel or rel == ".":
            return repo_root.resolve()
        p = (repo_root / rel).resolve()
        root = repo_root.resolve()
        if root not in p.parents and p != root:
            return None
        return p
    except Exception:
        return None


@tool(
    description=(
        "Find files by name or glob pattern across the ReEDS repo. "
        "USE THIS to verify a file exists BEFORE citing it in an answer. "
        "Returns relative paths, one per line. "
        "Examples: pattern='b_inputs.gms', pattern='**/*battery*', "
        "pattern='docs/source/*.md', pattern='inputs/techs/*.csv'."
    ),
    parameters={
        "pattern": {
            "type": "string",
            "description": "Glob pattern (supports ** for recursive). e.g. '**/*battery*.csv'",
        },
        "max_results": {
            "type": "integer",
            "description": "Max results to return (default 40, hard cap 80).",
        },
    },
    required=["pattern"],
)
def find_files(repo_root: Path, pattern: str, max_results: int = 40) -> tuple[str, list[dict]]:
    """Glob the repo for matching files."""
    pat = (pattern or "").strip().lstrip("/\\")
    if not pat:
        return "Empty pattern.", []
    cap = min(max(1, int(max_results or 40)), _EXPLORE_MAX_RESULTS)

    # Make a bare filename act like **/<name>
    if "/" not in pat and "\\" not in pat and "*" not in pat:
        pat = f"**/{pat}"

    try:
        matches = []
        for p in repo_root.glob(pat):
            if not p.is_file():
                continue
            rel = p.relative_to(repo_root).as_posix()
            if any(part in _EXPLORE_IGNORE_DIRS for part in rel.split("/")):
                continue
            matches.append(rel)
            if len(matches) >= cap:
                break
    except Exception as exc:
        return f"Glob error: {exc}", []

    if not matches:
        return f"No files match pattern `{pat}`.", []
    matches.sort()
    return f"Found {len(matches)} file(s) matching `{pat}`:\n" + "\n".join(matches), []


@tool(
    description=(
        "Search for an exact string or regex inside the ReEDS repo. "
        "USE THIS to find where a parameter, set, or equation is defined. "
        "Returns up to ~40 hits as `path:line: snippet`. Citations should use "
        "the returned `path#L<line>` so the user's viewer jumps to the line."
    ),
    parameters={
        "query": {"type": "string", "description": "Plain text or regex to search for."},
        "is_regex": {"type": "boolean", "description": "Treat query as regex (default false)."},
        "include_glob": {
            "type": "string",
            "description": "Optional glob to restrict files, e.g. '**/*.gms' or 'inputs/**'.",
        },
        "max_results": {"type": "integer", "description": "Max hits (default 30, hard cap 80)."},
    },
    required=["query"],
)
def grep_repo(
    repo_root: Path,
    query: str,
    is_regex: bool = False,
    include_glob: str = "",
    max_results: int = 30,
) -> tuple[str, list[dict]]:
    """Grep through the repo, skipping noisy dirs and binaries."""
    import re

    q = (query or "").strip()
    if not q:
        return "Empty query.", []
    cap = min(max(1, int(max_results or 30)), _EXPLORE_MAX_RESULTS)
    try:
        regex = re.compile(q, re.IGNORECASE) if is_regex else re.compile(re.escape(q), re.IGNORECASE)
    except re.error as exc:
        return f"Invalid regex: {exc}", []

    text_suffixes = {
        ".gms", ".py", ".md", ".rst", ".txt", ".csv", ".json", ".yaml", ".yml",
        ".toml", ".cfg", ".ini", ".opt", ".jl", ".sh", ".bat", ".r", ".tsv",
    }
    glob = (include_glob or "**/*").strip()

    hits: list[str] = []
    try:
        for p in repo_root.glob(glob):
            if not p.is_file():
                continue
            rel = p.relative_to(repo_root).as_posix()
            if any(part in _EXPLORE_IGNORE_DIRS for part in rel.split("/")):
                continue
            if p.suffix.lower() not in text_suffixes:
                continue
            try:
                if p.stat().st_size > 2_000_000:  # skip huge files
                    continue
                with p.open("r", encoding="utf-8", errors="replace") as fh:
                    for i, line in enumerate(fh, start=1):
                        if regex.search(line):
                            snippet = line.rstrip("\n")[:200]
                            hits.append(f"{rel}#L{i}: {snippet}")
                            if len(hits) >= cap:
                                break
            except Exception:
                continue
            if len(hits) >= cap:
                break
    except Exception as exc:
        return f"Search error: {exc}", []

    if not hits:
        return f"No matches for `{q}`" + (f" in `{glob}`." if include_glob else "."), []
    return f"Found {len(hits)} hit(s) for `{q}`:\n" + "\n".join(hits), []


@tool(
    description=(
        "Read a specific range of lines from a repo file. "
        "USE THIS to verify the exact contents of a file BEFORE quoting or "
        "paraphrasing it. Returns the requested lines numbered like "
        "`  42: <code>` so you can cite `path#L42` accurately."
    ),
    parameters={
        "path": {"type": "string", "description": "Repo-relative path, e.g. 'b_inputs.gms'."},
        "start_line": {"type": "integer", "description": "1-based start line (default 1)."},
        "end_line": {
            "type": "integer",
            "description": "1-based end line inclusive (default start+200, max 400-line span).",
        },
    },
    required=["path"],
)
def read_repo_file(
    repo_root: Path, path: str, start_line: int = 1, end_line: int = 0,
) -> tuple[str, list[dict]]:
    """Read a slice of a file, with line numbers."""
    p = _explore_safe_path(repo_root, path)
    if p is None or not p.is_file():
        return f"File not found: `{path}`. Use find_files to locate it.", []
    try:
        if p.stat().st_size > 4_000_000:
            return f"File `{path}` is too large to read inline ({p.stat().st_size} bytes).", []
        text = p.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        return f"Read error: {exc}", []

    lines = text.splitlines()
    n = len(lines)
    s = max(1, int(start_line or 1))
    if s > n:
        return f"`{path}` only has {n} line(s); start_line {s} is past the end.", []
    e = int(end_line or 0)
    if e <= 0:
        e = min(n, s + 199)
    e = min(n, max(s, e))
    if e - s + 1 > 400:
        e = s + 399
    width = len(str(e))
    body = "\n".join(f"{str(i).rjust(width)}: {lines[i - 1]}" for i in range(s, e + 1))
    header = f"{path}  (lines {s}-{e} of {n})"
    return f"{header}\n{body}", []


@tool(
    description=(
        "List the contents of a directory inside the ReEDS repo. "
        "Use this to discover what files exist before searching or reading."
    ),
    parameters={
        "path": {"type": "string", "description": "Repo-relative directory (default repo root)."},
    },
)
def list_repo_dir(repo_root: Path, path: str = "") -> tuple[str, list[dict]]:
    """List a directory non-recursively."""
    target = _explore_safe_path(repo_root, path or "")
    if target is None or not target.is_dir():
        return f"Directory not found: `{path}`.", []
    entries = []
    for child in sorted(target.iterdir(), key=lambda c: (not c.is_dir(), c.name.lower())):
        if child.name.startswith(".") or child.name in _EXPLORE_IGNORE_DIRS:
            continue
        entries.append(f"{'📁' if child.is_dir() else '📄'} {child.name}")
        if len(entries) >= _EXPLORE_MAX_RESULTS:
            entries.append(f"… (truncated, more than {_EXPLORE_MAX_RESULTS} entries)")
            break
    if not entries:
        return f"`{path or '.'}` is empty.", []
    rel = target.relative_to(repo_root).as_posix() or "."
    return f"Contents of `{rel}/`:\n" + "\n".join(entries), []
