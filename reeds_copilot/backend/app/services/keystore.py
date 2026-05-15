"""Local API-key + model storage.

Persisted in ``reeds_copilot/.user/keys.json`` (git-ignored).

Schema (current)::

    {
        "active_provider": "nlr",
        "providers": {
            "anthropic": {"key": "sk-ant-…", "model": "claude-opus-4-1"},
            "openai":    {"key": "sk-…",     "model": "gpt-4o"},
            "nlr":       {"key": "sk-…",     "model": "claude-opus-4-7"}
        }
    }

Legacy schema (still read-compatible)::

    {"anthropic": "sk-ant-…", "openai": "sk-…"}

We keep a simple JSON file (no encryption) because:
  • the file lives in a user-local, git-ignored directory
  • the user already trusts their local disk for ``~/.bashrc``, ``.env``, etc.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from threading import Lock

log = logging.getLogger(__name__)

# reeds_copilot/.user/keys.json
_USER_DIR = Path(__file__).resolve().parents[3] / ".user"
_KEYS_FILE = _USER_DIR / "keys.json"
_lock = Lock()


def _ensure_dir() -> None:
    _USER_DIR.mkdir(parents=True, exist_ok=True)


def _read_raw() -> dict:
    """Read the file, normalising legacy formats to the current schema."""
    if not _KEYS_FILE.exists():
        return {"active_provider": "", "providers": {}}
    try:
        data = json.loads(_KEYS_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, ValueError, UnicodeDecodeError) as exc:
        log.warning("Could not read %s: %s – starting fresh", _KEYS_FILE, exc)
        return {"active_provider": "", "providers": {}}

    if not isinstance(data, dict):
        return {"active_provider": "", "providers": {}}

    # Current schema
    if "providers" in data and isinstance(data.get("providers"), dict):
        providers: dict[str, dict] = {}
        for p, v in data["providers"].items():
            if isinstance(p, str) and isinstance(v, dict) and isinstance(v.get("key"), str):
                providers[p] = {
                    "key": v["key"],
                    "model": v["model"] if isinstance(v.get("model"), str) else "",
                }
        active = data.get("active_provider", "")
        if not isinstance(active, str):
            active = ""
        return {"active_provider": active, "providers": providers}

    # Legacy flat schema: {"provider": "key", ...}
    providers = {
        p: {"key": v, "model": ""}
        for p, v in data.items()
        if isinstance(p, str) and isinstance(v, str) and v
    }
    return {"active_provider": "", "providers": providers}


def _write_raw(data: dict) -> None:
    _ensure_dir()
    _KEYS_FILE.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


# ── Public API ────────────────────────────────────────────────────────────────

def save_key(provider: str, key: str, model: str = "") -> None:
    """Save (or update) the API key + model for a provider, and mark it active."""
    with _lock:
        data = _read_raw()
        existing = data["providers"].get(provider, {})
        new_model = model.strip() if model else existing.get("model", "")
        data["providers"][provider] = {"key": key, "model": new_model}
        data["active_provider"] = provider
        _write_raw(data)


def save_model(provider: str, model: str) -> None:
    """Update the remembered model for a provider (without touching the key)."""
    with _lock:
        data = _read_raw()
        if provider in data["providers"]:
            data["providers"][provider]["model"] = model.strip()
            data["active_provider"] = provider
            _write_raw(data)


def set_active_provider(provider: str) -> None:
    with _lock:
        data = _read_raw()
        if provider in data["providers"]:
            data["active_provider"] = provider
            _write_raw(data)


def get_key(provider: str) -> str:
    with _lock:
        return _read_raw()["providers"].get(provider, {}).get("key", "")


def get_model(provider: str) -> str:
    with _lock:
        return _read_raw()["providers"].get(provider, {}).get("model", "")


def get_active_provider() -> str:
    with _lock:
        return _read_raw().get("active_provider", "")


def get_all_providers_with_keys() -> list[str]:
    with _lock:
        return [p for p, v in _read_raw()["providers"].items() if v.get("key")]


def delete_key(provider: str) -> bool:
    with _lock:
        data = _read_raw()
        if provider in data["providers"]:
            del data["providers"][provider]
            if data.get("active_provider") == provider:
                data["active_provider"] = ""
            _write_raw(data)
            return True
        return False


def load_all_keys() -> dict[str, str]:
    """Backwards-compatible flat {provider: key} map."""
    with _lock:
        return {p: v["key"] for p, v in _read_raw()["providers"].items() if v.get("key")}
