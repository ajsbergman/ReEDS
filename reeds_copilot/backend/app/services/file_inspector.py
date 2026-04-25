"""File inspection helpers – list, preview text, preview CSV."""
from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from ..core.config import Settings

log = logging.getLogger(__name__)

TEXT_SUFFIXES = {
    ".py", ".gms", ".jl", ".r", ".sh", ".bat",
    ".md", ".rst", ".txt", ".json", ".yaml", ".yml",
    ".toml", ".cfg", ".ini", ".opt", ".csv", ".tsv",
    ".html", ".xml", ".sql",
}

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".svg", ".webp"}


def safe_resolve(repo_root: Path, rel_path: str) -> Path:
    """Resolve *rel_path* relative to *repo_root* and ensure it stays inside."""
    resolved = (repo_root / rel_path).resolve()
    if not str(resolved).startswith(str(repo_root.resolve())):
        raise PermissionError("Path escapes repository root.")
    return resolved


def list_directory(repo_root: Path, rel_path: str) -> list[dict]:
    target = safe_resolve(repo_root, rel_path)
    if not target.is_dir():
        raise FileNotFoundError(f"Not a directory: {rel_path}")

    entries = []
    for child in sorted(target.iterdir()):
        if child.name.startswith("."):
            continue
        try:
            st = child.stat()
            size = st.st_size if child.is_file() else None
            mtime = st.st_mtime
        except OSError:
            size = None
            mtime = 0
        entries.append({
            "name": child.name,
            "rel_path": str(child.relative_to(repo_root)).replace("\\", "/"),
            "is_dir": child.is_dir(),
            "size": size,
            "modified_at": mtime,
        })
    return entries


MAX_FULL_SIZE = 10 * 1024 * 1024  # 10 MB safety cap for full view


def preview_file(repo_root: Path, rel_path: str, settings: Settings, full: bool = False) -> dict:
    target = safe_resolve(repo_root, rel_path)
    if not target.is_file():
        raise FileNotFoundError(f"Not a file: {rel_path}")

    suffix = target.suffix.lower()
    result: dict = {"rel_path": rel_path, "file_type": suffix}

    if suffix == ".csv":
        return _preview_csv(target, rel_path, settings, full=full)

    if suffix in IMAGE_SUFFIXES:
        result.update({
            "content": None,
            "is_image": True,
            "truncated": False,
        })
        return result

    if suffix in TEXT_SUFFIXES or suffix == "":
        text = target.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
        if full:
            # Cap at 10 MB worth of text
            if target.stat().st_size > MAX_FULL_SIZE:
                lines = lines[:50000]
                truncated = True
            else:
                truncated = False
        else:
            truncated = len(lines) > settings.max_file_preview_lines
            if truncated:
                lines = lines[: settings.max_file_preview_lines]
        result.update({
            "content": "\n".join(lines),
            "truncated": truncated,
        })
        return result

    result["content"] = "(binary or unsupported file type)"
    return result


def _preview_csv(target: Path, rel_path: str, settings: Settings, full: bool = False) -> dict:
    max_rows = None if full else settings.max_csv_preview_rows
    try:
        df = pd.read_csv(target, nrows=max_rows, low_memory=False)
    except Exception as exc:
        return {
            "rel_path": rel_path,
            "file_type": ".csv",
            "content": f"Error reading CSV: {exc}",
        }

    # Count total rows cheaply
    try:
        with open(target, "r", encoding="utf-8", errors="replace") as fh:
            total_rows = sum(1 for _ in fh) - 1  # minus header
    except Exception:
        total_rows = len(df)

    display_rows = len(df) if full else min(len(df), settings.max_csv_preview_rows)

    return {
        "rel_path": rel_path,
        "file_type": ".csv",
        "columns": list(df.columns),
        "rows": df.head(display_rows).to_dict(orient="records"),
        "total_rows": total_rows,
        "truncated": total_rows > display_rows,
    }
