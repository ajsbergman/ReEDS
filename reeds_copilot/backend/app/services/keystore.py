"""Local API-key storage.

Keys are persisted in ``reeds_copilot/.user/keys.json`` (git-ignored) so
users don't have to re-enter them after every restart.  The file stores one
key per provider::

    {
        "anthropic": "sk-ant-…",
        "openai":    "sk-…",
        "nlr":       "sk-…"
    }

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


def _read_all() -> dict[str, str]:
    if not _KEYS_FILE.exists():
        return {}
    try:
        data = json.loads(_KEYS_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return {k: v for k, v in data.items() if isinstance(k, str) and isinstance(v, str)}
    except (json.JSONDecodeError, OSError, ValueError, UnicodeDecodeError) as exc:
        log.warning("Could not read %s: %s – starting fresh", _KEYS_FILE, exc)
    return {}


def _write_all(data: dict[str, str]) -> None:
    _ensure_dir()
    _KEYS_FILE.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


# ── Public API ────────────────────────────────────────────────────────────────

def save_key(provider: str, key: str) -> None:
    with _lock:
        keys = _read_all()
        keys[provider] = key
        _write_all(keys)


def get_key(provider: str) -> str:
    with _lock:
        return _read_all().get(provider, "")


def get_all_providers_with_keys() -> list[str]:
    with _lock:
        return [p for p, k in _read_all().items() if k]


def delete_key(provider: str) -> bool:
    with _lock:
        keys = _read_all()
        if provider in keys:
            del keys[provider]
            _write_all(keys)
            return True
        return False


def load_all_keys() -> dict[str, str]:
    with _lock:
        return _read_all()
