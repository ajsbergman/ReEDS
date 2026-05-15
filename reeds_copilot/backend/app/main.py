"""ReEDS-Copilot backend – FastAPI application."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .core.config import get_settings
from .services.llm import build_llm_provider
from .services import keystore
from .services.repo_index import RepoIndex
from .services.run_manager import init_run_manager
from .api import chat, search, files, health, sessions, runs, setup

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(name)s  %(message)s")
log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()

    # Build repo index
    repo_index = RepoIndex(root=settings.repo_root)
    log.info("Building repo index for %s …", settings.repo_root)
    repo_index.build()
    app.state.repo_index = repo_index

    # Build LLM provider – prefer stored keys from .user/keys.json, fall back to env vars
    stored_keys = keystore.load_all_keys()
    key_map = {
        "anthropic": stored_keys.get("anthropic") or settings.anthropic_api_key,
        "openai": stored_keys.get("openai") or settings.openai_api_key,
        "google": stored_keys.get("google") or settings.google_api_key,
        "nlr": stored_keys.get("nlr", ""),
    }
    # Pick the configured provider, or the first provider that has a key
    provider_name = settings.llm_provider
    api_key = key_map.get(provider_name, "")
    if not api_key:
        # Auto-select the first provider that has a stored key
        for pname, pkey in key_map.items():
            if pkey:
                provider_name = pname
                api_key = pkey
                break
    app.state.llm = build_llm_provider(provider_name, api_key, settings.model_name or None)
    app.state.active_provider_name = provider_name
    app.state.active_model_name = settings.model_name or ""
    log.info("LLM provider: %s  model: %s  key set: %s", provider_name, settings.model_name, bool(api_key))

    # Load persisted run history
    init_run_manager(settings.repo_root)

    yield  # app runs

    log.info("Shutting down ReEDS-Copilot backend.")


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="ReEDS-Copilot",
        description="AI-powered assistant for the ReEDS repository.",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router)
    app.include_router(chat.router)
    app.include_router(search.router)
    app.include_router(files.router)
    app.include_router(sessions.router)
    app.include_router(runs.router)
    app.include_router(setup.router)

    return app


app = create_app()
