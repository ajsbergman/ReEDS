"""Application configuration loaded from environment variables."""
from __future__ import annotations

import os
from pathlib import Path
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Repo root – defaults to two levels up from this file (i.e. the ReEDS repo root)
    repo_root: Path = Field(
        default_factory=lambda: Path(__file__).resolve().parents[4],
        description="Absolute path to the ReEDS repository root.",
    )

    # LLM provider
    llm_provider: str = Field(default="anthropic", alias="REEDS_COPILOT_LLM_PROVIDER")
    model_name: str = Field(default="", alias="REEDS_COPILOT_MODEL")  # empty = use provider default
    anthropic_api_key: str = Field(default="", alias="ANTHROPIC_API_KEY")
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    google_api_key: str = Field(default="", alias="GOOGLE_API_KEY")

    # Retrieval
    max_retrieval_results: int = Field(default=10, alias="REEDS_COPILOT_MAX_RESULTS")
    max_file_preview_lines: int = 500
    max_csv_preview_rows: int = 200

    # Server
    host: str = "0.0.0.0"
    port: int = 8000
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    model_config = {
        "env_prefix": "",
        "populate_by_name": True,
        "env_file": ".env",
        "env_file_encoding": "utf-8",
    }


@lru_cache()
def get_settings() -> Settings:
    return Settings()
