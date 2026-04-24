"""Health / config endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from ..core.config import Settings, get_settings
from ..models.schemas import HealthResponse, UpdateApiKeyRequest, UpdateApiKeyResponse
from ..services.llm import build_llm_provider, DEFAULT_MODELS

router = APIRouter(tags=["health"])

# Runtime-mutable state (not tied to the frozen Settings object)
_active_provider_name: str = ""
_active_model_name: str = ""


@router.get("/health", response_model=HealthResponse)
def health(request: Request, settings: Settings = Depends(get_settings)) -> HealthResponse:
    llm = request.app.state.llm
    has_key = bool(getattr(llm, "_api_key", None))
    provider = _active_provider_name or settings.llm_provider
    model = _active_model_name or getattr(llm, "_model", "") or DEFAULT_MODELS.get(provider, "")
    return HealthResponse(
        status="ok",
        repo_root=str(settings.repo_root),
        repo_exists=settings.repo_root.is_dir(),
        llm_provider=provider,
        model_name=model,
        api_key_set=has_key,
    )


@router.post("/config/api-key", response_model=UpdateApiKeyResponse)
def update_api_key(
    body: UpdateApiKeyRequest,
    request: Request,
    settings: Settings = Depends(get_settings),
) -> UpdateApiKeyResponse:
    """Set (or replace) the LLM API key and provider at runtime."""
    global _active_provider_name, _active_model_name

    key = body.api_key.strip()
    if not key:
        return UpdateApiKeyResponse(success=False, message="API key cannot be empty.")
    provider_name = body.provider.strip().lower()
    try:
        provider = build_llm_provider(provider_name, key)
        request.app.state.llm = provider
        _active_provider_name = provider_name
        _active_model_name = getattr(provider, "_model", DEFAULT_MODELS.get(provider_name, ""))
        return UpdateApiKeyResponse(
            success=True,
            message=f"Switched to {provider_name} ({_active_model_name}). Chat is ready.",
        )
    except Exception as exc:
        return UpdateApiKeyResponse(success=False, message=str(exc))
