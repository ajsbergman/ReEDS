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
    # Bind to loopback only by default so the SSH-password-handling API is
    # not exposed on the local network. Override via REEDS_COPILOT_HOST env
    # var if you intentionally need LAN access (and add TLS/auth in front).
    host: str = Field(default="127.0.0.1", alias="REEDS_COPILOT_HOST")
    port: int = 8001
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    # SSH host-key policy:
    #   "strict" (default) — reject unknown hosts (uses ~/.ssh/known_hosts)
    #   "tofu"             — Trust-On-First-Use (auto-add unknown hosts)
    # The frontend can flip this to "tofu" only via explicit user opt-in.
    ssh_host_key_policy: str = Field(default="strict", alias="REEDS_COPILOT_SSH_POLICY")

    model_config = {
        "env_prefix": "",
        "populate_by_name": True,
        "env_file": ".env",
        "env_file_encoding": "utf-8",
    }


@lru_cache()
def get_settings() -> Settings:
    return Settings()
