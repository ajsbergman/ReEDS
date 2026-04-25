"""Chat session CRUD endpoints."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..core.config import Settings, get_settings
from ..services import chat_store

router = APIRouter(prefix="/chat/sessions", tags=["sessions"])

def _data_root(settings: Settings):
    return settings.repo_root / "reeds_copilot"


class CreateSessionRequest(BaseModel):
    title: str = "New Chat"


class UpdateSessionRequest(BaseModel):
    messages: list[dict[str, Any]]
    title: str | None = None


@router.post("")
def create(body: CreateSessionRequest, settings: Settings = Depends(get_settings)):
    return chat_store.create_session(_data_root(settings), body.title)


@router.get("")
def list_all(settings: Settings = Depends(get_settings)):
    return chat_store.list_sessions(_data_root(settings))


@router.get("/{session_id}")
def get_one(session_id: str, settings: Settings = Depends(get_settings)):
    s = chat_store.get_session(_data_root(settings), session_id)
    if s is None:
        raise HTTPException(404, "Session not found")
    return s


@router.put("/{session_id}")
def update(session_id: str, body: UpdateSessionRequest, settings: Settings = Depends(get_settings)):
    s = chat_store.update_session(_data_root(settings), session_id, body.messages, body.title)
    if s is None:
        raise HTTPException(404, "Session not found")
    return s


@router.delete("/{session_id}")
def delete(session_id: str, settings: Settings = Depends(get_settings)):
    if not chat_store.delete_session(_data_root(settings), session_id):
        raise HTTPException(404, "Session not found")
    return {"ok": True}
