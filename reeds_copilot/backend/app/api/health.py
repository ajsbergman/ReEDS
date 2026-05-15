"""Health / config endpoints."""
from __future__ import annotations

import os
import threading
import time

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from ..core.config import Settings, get_settings
from ..models.schemas import HealthResponse, UpdateApiKeyRequest, UpdateApiKeyResponse
from ..services.llm import build_llm_provider, DEFAULT_MODELS
from ..services import keystore, run_manager

router = APIRouter(tags=["health"])


def _get_active_provider(request: Request) -> str:
    return getattr(request.app.state, "active_provider_name", "")


def _get_active_model(request: Request) -> str:
    return getattr(request.app.state, "active_model_name", "")


@router.get("/health", response_model=HealthResponse)
def health(request: Request, settings: Settings = Depends(get_settings)) -> HealthResponse:
    llm = request.app.state.llm
    has_key = bool(getattr(llm, "_api_key", None))
    provider = _get_active_provider(request) or settings.llm_provider
    model = _get_active_model(request) or getattr(llm, "_model", "") or DEFAULT_MODELS.get(provider, "")
    return HealthResponse(
        status="ok",
        repo_root=str(settings.repo_root),
        repo_exists=settings.repo_root.is_dir(),
        llm_provider=provider,
        model_name=model,
        api_key_set=has_key,
        stored_keys=keystore.get_all_providers_with_keys(),
    )


@router.post("/config/api-key", response_model=UpdateApiKeyResponse)
def update_api_key(
    body: UpdateApiKeyRequest,
    request: Request,
    settings: Settings = Depends(get_settings),
) -> UpdateApiKeyResponse:
    """Set (or replace) the LLM API key and provider at runtime."""
    key = body.api_key.strip()
    if not key:
        return UpdateApiKeyResponse(success=False, message="API key cannot be empty.")
    provider_name = body.provider.strip().lower()
    model = body.model.strip() or None  # None = use provider default
    try:
        provider = build_llm_provider(provider_name, key, model)
        request.app.state.llm = provider
        request.app.state.active_provider_name = provider_name
        active_model = getattr(provider, "_model", DEFAULT_MODELS.get(provider_name, ""))
        request.app.state.active_model_name = active_model
        # Persist key + chosen model so they survive restarts
        keystore.save_key(provider_name, key, active_model)
        return UpdateApiKeyResponse(
            success=True,
            message=f"Switched to {provider_name} ({active_model}). Chat is ready.",
        )
    except Exception as exc:
        return UpdateApiKeyResponse(success=False, message=str(exc))


@router.get("/config/models")
def list_available_models(request: Request):
    """List available models from the active provider (Google only for now)."""
    llm = request.app.state.llm
    provider = _get_active_provider(request) or "unknown"
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


# ── Stored-key management ────────────────────────────────────────────────────

class SwitchProviderRequest(BaseModel):
    provider: str
    model: str = ""


@router.post("/config/switch-provider", response_model=UpdateApiKeyResponse)
def switch_provider(
    body: SwitchProviderRequest,
    request: Request,
) -> UpdateApiKeyResponse:
    """Switch to a provider whose key is already stored on disk."""
    provider_name = body.provider.strip().lower()
    key = keystore.get_key(provider_name)
    if not key:
        return UpdateApiKeyResponse(
            success=False,
            message=f"No stored API key for '{provider_name}'. Save one first in Settings.",
        )
    # If no model passed by the caller, fall back to the previously remembered one
    model = body.model.strip() or keystore.get_model(provider_name) or None
    try:
        provider = build_llm_provider(provider_name, key, model)
        request.app.state.llm = provider
        request.app.state.active_provider_name = provider_name
        active_model = getattr(provider, "_model", DEFAULT_MODELS.get(provider_name, ""))
        request.app.state.active_model_name = active_model
        # Remember the active provider + chosen model across restarts
        keystore.save_model(provider_name, active_model)
        return UpdateApiKeyResponse(
            success=True,
            message=f"Switched to {provider_name} ({active_model}).",
        )
    except Exception as exc:
        return UpdateApiKeyResponse(success=False, message=str(exc))


@router.delete("/config/api-key/{provider}")
def delete_stored_key(provider: str):
    """Delete a stored API key from disk."""
    removed = keystore.delete_key(provider.strip().lower())
    return {"deleted": removed, "provider": provider}


# ── Shutdown ────────────────────────────────────────────────────────────────

class ShutdownRequest(BaseModel):
    force: bool = False  # if True, kill active local runs too


@router.get("/shutdown/preview")
def shutdown_preview():
    """Report what would be affected by a shutdown (active runs)."""
    runs = run_manager.list_runs()
    active_local = [
        {"id": r["id"], "batch_name": r.get("batch_name", ""), "status": r.get("status", "")}
        for r in runs
        if r.get("target") == "local" and r.get("status") in ("running", "queued")
    ]
    active_hpc = [
        {"id": r["id"], "batch_name": r.get("batch_name", ""), "status": r.get("status", "")}
        for r in runs
        if r.get("target") == "hpc" and r.get("status") in ("running", "queued")
    ]
    return {
        "active_local_runs": active_local,
        "active_hpc_runs": active_hpc,  # informational only — not killed
        "safe_to_shutdown": len(active_local) == 0,
    }


@router.post("/shutdown")
def shutdown(body: ShutdownRequest, settings: Settings = Depends(get_settings)):
    """Gracefully shut down the backend.

    Refuses if active LOCAL runs exist unless ``force=True``.  HPC runs are
    never killed — they keep going on the cluster regardless of the
    backend's state.
    """
    runs = run_manager.list_runs()
    active_local = [
        r for r in runs
        if r.get("target") == "local" and r.get("status") in ("running", "queued")
    ]
    if active_local and not body.force:
        return {
            "shutdown": False,
            "reason": "active_local_runs",
            "count": len(active_local),
            "message": (
                f"{len(active_local)} local run(s) still in progress. "
                f"Send {{ \"force\": true }} to terminate them and shut down."
            ),
        }

    cancelled = 0
    if active_local and body.force:
        cancelled = run_manager.cancel_all_local(settings.repo_root)

    # Schedule a hard shutdown that also closes the launcher / frontend cmd
    # windows so the user gets a clean exit with one click.
    #
    # Strategy on Windows:
    #   1. Kill the frontend by its listening port (5173) — that kills
    #      `node`/vite, and because launch.bat now uses `cmd /c`, the
    #      frontend cmd window auto-closes when its child exits.
    #   2. Kill any cmd.exe whose command line contains "launch.bat" —
    #      this works whether the launcher runs in a classic console OR
    #      inside Windows Terminal (where cmd.exe has no MainWindowTitle).
    #   3. Exit ourselves with os._exit(0) — the backend's own cmd window
    #      then closes too because it was started with `cmd /c`.
    import signal as _signal
    import subprocess as _sp
    import sys as _sys

    frontend_port = 5173

    def _exit_soon():
        # Tiny pause to let the HTTP response flush back to the client; we
        # keep this short so the launcher terminals start exiting at the
        # same time the frontend's 2s countdown begins.
        time.sleep(0.1)
        if _sys.platform.startswith("win"):
            ps_kill = (
                # Kill whatever listens on the frontend port
                f"Get-NetTCPConnection -LocalPort {frontend_port} -State Listen "
                "-ErrorAction SilentlyContinue | "
                "ForEach-Object { Stop-Process -Id $_.OwningProcess -Force "
                "-ErrorAction SilentlyContinue };"
                # Kill the launcher cmd (matches by command line, works in
                # Windows Terminal too where MainWindowTitle is empty)
                "Get-CimInstance Win32_Process -Filter \"Name='cmd.exe'\" "
                "-ErrorAction SilentlyContinue | "
                "Where-Object { $_.CommandLine -like '*launch.bat*' } | "
                "ForEach-Object { Stop-Process -Id $_.ProcessId -Force "
                "-ErrorAction SilentlyContinue }"
            )
            try:
                _sp.run(
                    ["powershell", "-NoProfile", "-Command", ps_kill],
                    timeout=8,
                    stdout=_sp.DEVNULL, stderr=_sp.DEVNULL,
                    creationflags=getattr(_sp, "CREATE_NO_WINDOW", 0),
                )
            except Exception:
                pass
        try:
            _signal.raise_signal(_signal.SIGINT)
        except Exception:
            pass
        time.sleep(0.5)
        os._exit(0)

    threading.Thread(target=_exit_soon, daemon=True).start()
    return {
        "shutdown": True,
        "cancelled_local_runs": cancelled,
        "message": "Backend shutting down…",
    }
