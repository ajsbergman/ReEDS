"""Persistent chat session storage – JSON files on disk."""
from __future__ import annotations

import json
import logging
import time
import uuid
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

SESSIONS_DIR_NAME = "chat_sessions"


def _sessions_dir(data_root: Path) -> Path:
    d = data_root / SESSIONS_DIR_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def _session_path(data_root: Path, session_id: str) -> Path:
    # Prevent path traversal
    safe_id = Path(session_id).name
    if safe_id != session_id or ".." in session_id:
        raise ValueError("Invalid session id")
    return _sessions_dir(data_root) / f"{safe_id}.json"


def create_session(data_root: Path, title: str = "New Chat") -> dict:
    sid = uuid.uuid4().hex[:12]
    session = {
        "id": sid,
        "title": title,
        "created_at": time.time(),
        "updated_at": time.time(),
        "messages": [],
    }
    _session_path(data_root, sid).write_text(
        json.dumps(session, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return session


def list_sessions(data_root: Path) -> list[dict]:
    d = _sessions_dir(data_root)
    sessions = []
    for f in sorted(d.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            sessions.append({
                "id": data["id"],
                "title": data.get("title", "Untitled"),
                "created_at": data.get("created_at", 0),
                "updated_at": data.get("updated_at", 0),
                "message_count": len(data.get("messages", [])),
            })
        except Exception:
            continue
    return sessions


def get_session(data_root: Path, session_id: str) -> dict | None:
    p = _session_path(data_root, session_id)
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def update_session(data_root: Path, session_id: str, messages: list[dict], title: str | None = None) -> dict | None:
    p = _session_path(data_root, session_id)
    if not p.exists():
        return None
    data = json.loads(p.read_text(encoding="utf-8"))
    data["messages"] = messages
    data["updated_at"] = time.time()
    if title is not None:
        data["title"] = title
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return data


def delete_session(data_root: Path, session_id: str) -> bool:
    p = _session_path(data_root, session_id)
    if p.exists():
        p.unlink()
        return True
    return False
