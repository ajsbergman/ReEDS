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
    model = body.model.strip() or None  # None = use provider default
    try:
        provider = build_llm_provider(provider_name, key, model)
        request.app.state.llm = provider
        _active_provider_name = provider_name
        _active_model_name = getattr(provider, "_model", DEFAULT_MODELS.get(provider_name, ""))
        return UpdateApiKeyResponse(
            success=True,
            message=f"Switched to {provider_name} ({_active_model_name}). Chat is ready.",
        )
    except Exception as exc:
        return UpdateApiKeyResponse(success=False, message=str(exc))


@router.get("/config/models")
def list_available_models(request: Request):
    """List available models from the active provider (Google only for now)."""
    llm = request.app.state.llm
    provider = _active_provider_name or "unknown"
    api_key = getattr(llm, "_api_key", "")

    if provider == "google" and api_key:
        try:
            from google import genai
            client = genai.Client(api_key=api_key)
            models = []
            for m in client.models.list():
                name = m.name if isinstance(m.name, str) else str(m.name)
                # Only show generative models
                if "generateContent" in (m.supported_actions or []) or "generate" in name.lower() or "gemini" in name.lower():
                    models.append(name.replace("models/", ""))
            return {"provider": provider, "models": sorted(models)}
        except Exception as exc:
            return {"provider": provider, "models": [], "error": str(exc)}

    return {"provider": provider, "models": []}
