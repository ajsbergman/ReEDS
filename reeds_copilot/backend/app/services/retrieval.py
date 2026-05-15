"""Simple text search over indexed repo files."""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

from .repo_index import RepoIndex, FileRecord

log = logging.getLogger(__name__)

SEARCHABLE_SUFFIXES = {
    ".py", ".gms", ".jl", ".r", ".sh", ".bat",
    ".md", ".rst", ".txt",
    ".csv", ".json", ".yaml", ".yml", ".toml", ".cfg", ".ini", ".opt",
}
CONTEXT_LINES = 2  # lines of context around a match
MAX_FILE_READ = 512 * 1024  # 512 KB


@dataclass
class SearchHit:
    file_path: str
    snippet: str
    match_type: str
    score: float
    line: int = 0  # 1-based line number of the first match (0 = unknown)


def _snippet_around(lines: list[str], idx: int, context: int = CONTEXT_LINES) -> str:
    start = max(0, idx - context)
    end = min(len(lines), idx + context + 1)
    return "\n".join(lines[start:end])


def text_search(
    index: RepoIndex,
    query: str,
    category: str | None = None,
    max_results: int = 10,
) -> list[SearchHit]:
    """Brute-force text search with basic ranking."""
    hits: list[SearchHit] = []
    pattern = re.compile(re.escape(query), re.IGNORECASE)

    pool = index.files_in_category(category) if category and category != "all" else index.files
    candidates = [f for f in pool if f.suffix in SEARCHABLE_SUFFIXES]

    for rec in candidates:
        try:
            text = Path(rec.abs_path).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        if len(text) > MAX_FILE_READ:
            text = text[:MAX_FILE_READ]

        lines = text.splitlines()
        match_count = 0
        best_snippet = ""
        first_match_line = 0
        for i, line in enumerate(lines):
            if pattern.search(line):
                if match_count == 0:
                    best_snippet = _snippet_around(lines, i)
                    first_match_line = i + 1  # 1-based
                match_count += 1

        if match_count > 0:
            hits.append(SearchHit(
                file_path=rec.rel_path,
                snippet=best_snippet,
                match_type="text",
                score=match_count,
                line=first_match_line,
            ))

        if len(hits) >= max_results * 3:
            break  # early exit – we'll trim later

    # Also check filename matches
    filename_hits = index.search_filenames(query, category, limit=max_results)
    for rec in filename_hits:
        if not any(h.file_path == rec.rel_path for h in hits):
            hits.append(SearchHit(
                file_path=rec.rel_path,
                snippet="(filename match)",
                match_type="filename",
                score=0.5,
            ))

    # Sort by score descending
    hits.sort(key=lambda h: h.score, reverse=True)
    return hits[:max_results]
