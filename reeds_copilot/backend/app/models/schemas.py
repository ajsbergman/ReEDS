"""Pydantic request / response models."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


# ── Chat ──────────────────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str
    mode: Literal["general", "docs", "code", "inputs", "outputs"] = "general"
    selected_path: str | None = None  # optional file/dir for grounding


class SourceSnippet(BaseModel):
    file_path: str
    snippet: str
    match_type: str = ""
    score: float = 0.0
    line: int = 0  # 1-based; 0 = unknown / filename match


class ChatResponse(BaseModel):
    answer: str
    sources: list[SourceSnippet] = []
    attachments: list[dict] = []


# ── Search ────────────────────────────────────────────────────────────────────

class SearchRequest(BaseModel):
    query: str
    category: Literal["all", "docs", "code", "inputs", "outputs"] = "all"
    max_results: int = Field(default=10, le=50)


class SearchResult(BaseModel):
    file_path: str
    snippet: str
    match_type: str
    score: float = 0.0


class SearchResponse(BaseModel):
    results: list[SearchResult]
    total: int


# ── Files ─────────────────────────────────────────────────────────────────────

class FileEntry(BaseModel):
    name: str
    rel_path: str
    is_dir: bool
    size: int | None = None
    modified_at: float = 0
    category: str = ""


class FileListResponse(BaseModel):
    path: str
    entries: list[FileEntry]


class GdxSymbolInfo(BaseModel):
    name: str
    type: str
    dims: int
    records: int
    description: str = ""


class H5DatasetInfo(BaseModel):
    name: str           # "/group/dataset"
    shape: str          # e.g. "100×3" or "scalar"
    dtype: str          # e.g. "float64"
    size: int = 0       # total element count
    ndim: int = 0


class FilePreviewResponse(BaseModel):
    rel_path: str
    file_type: str
    content: str | None = None          # text content
    columns: list[str] | None = None    # CSV columns
    rows: list[dict[str, Any]] | None = None  # CSV sample rows
    total_rows: int | None = None
    truncated: bool = False
    is_image: bool = False
    # GDX-specific
    gdx_symbols: list[GdxSymbolInfo] | None = None  # symbol listing
    gdx_symbol: str | None = None                    # active symbol name
    # HDF5-specific
    h5_datasets: list[H5DatasetInfo] | None = None  # dataset listing
    h5_dataset: str | None = None                    # active dataset path
    h5_shape: str | None = None
    h5_dtype: str | None = None


# ── Health ────────────────────────────────────────────────────────────────────

class UpdateApiKeyRequest(BaseModel):
    api_key: str
    provider: str = "anthropic"
    model: str = ""  # empty = use provider default


class UpdateApiKeyResponse(BaseModel):
    success: bool
    message: str


class HealthResponse(BaseModel):
    status: str = "ok"
    repo_root: str
    repo_exists: bool
    llm_provider: str
    model_name: str
    api_key_set: bool
    stored_keys: list[str] = []  # providers that have a saved key on disk
