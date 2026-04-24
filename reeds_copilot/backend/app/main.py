"""ReEDS-Copilot backend – FastAPI application."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .core.config import get_settings
from .services.llm import build_llm_provider
from .services.repo_index import RepoIndex
from .api import chat, search, files, health

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

    # Build LLM provider
    key_map = {
        "anthropic": settings.anthropic_api_key,
        "openai": settings.openai_api_key,
        "google": settings.google_api_key,
    }
    api_key = key_map.get(settings.llm_provider, "")
    app.state.llm = build_llm_provider(settings.llm_provider, api_key, settings.model_name or None)
    log.info("LLM provider: %s  model: %s  key set: %s", settings.llm_provider, settings.model_name, bool(api_key))

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

    return app


app = create_app()
