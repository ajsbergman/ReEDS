"""Repo scanner / indexer – builds an in-memory catalogue of ReEDS files."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

IGNORE_DIRS = {
    ".git", "__pycache__", "node_modules", ".mypy_cache", ".pytest_cache",
    "egg-info", ".tox", ".venv", "venv", "reeds_copilot",
}
IGNORE_EXTENSIONS = {
    ".pkl", ".h5", ".hdf5", ".zip", ".tar", ".gz", ".bz2",
    ".exe", ".dll", ".so", ".o", ".a", ".parquet", ".feather",
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".svg", ".ico",
}
MAX_FILE_SIZE = 10 * 1024 * 1024  # skip files > 10 MB


def _classify(rel: Path) -> str:
    """Assign a rough category to a file."""
    parts_lower = [p.lower() for p in rel.parts]
    suffix = rel.suffix.lower()

    if "docs" in parts_lower or suffix in {".md", ".rst", ".txt"}:
        return "docs"
    if any(p.startswith("output") or p.startswith("run") for p in parts_lower):
        return "outputs"
    if "inputs" in parts_lower or "input_processing" in parts_lower:
        return "inputs"
    if suffix in {".py", ".gms", ".jl", ".r", ".sh", ".bat"}:
        return "code"
    if suffix in {".csv", ".json", ".yaml", ".yml", ".toml", ".cfg", ".ini", ".opt"}:
        return "config"
    return "other"


@dataclass
class FileRecord:
    rel_path: str
    abs_path: str
    category: str
    size: int
    suffix: str


@dataclass
class RepoIndex:
    root: Path
    files: list[FileRecord] = field(default_factory=list)
    _by_category: dict[str, list[FileRecord]] = field(default_factory=dict)

    # ── Build ──

    def build(self) -> None:
        self.files.clear()
        self._by_category.clear()
        count = 0
        for path in self.root.rglob("*"):
            if path.is_dir():
                continue
            # skip ignored dirs
            if any(part in IGNORE_DIRS for part in path.relative_to(self.root).parts):
                continue
            if path.suffix.lower() in IGNORE_EXTENSIONS:
                continue
            try:
                size = path.stat().st_size
            except OSError:
                continue
            if size > MAX_FILE_SIZE:
                continue

            rel = path.relative_to(self.root)
            cat = _classify(rel)
            rec = FileRecord(
                rel_path=str(rel).replace("\\", "/"),
                abs_path=str(path),
                category=cat,
                size=size,
                suffix=path.suffix.lower(),
            )
            self.files.append(rec)
            self._by_category.setdefault(cat, []).append(rec)
            count += 1

        log.info("Indexed %d files under %s", count, self.root)

    # ── Query helpers ──

    def files_in_category(self, category: str) -> list[FileRecord]:
        return self._by_category.get(category, [])

    def search_filenames(self, query: str, category: str | None = None, limit: int = 20) -> list[FileRecord]:
        query_lower = query.lower()
        pool = self._by_category.get(category, self.files) if category else self.files
        matches = [f for f in pool if query_lower in f.rel_path.lower()]
        return matches[:limit]
