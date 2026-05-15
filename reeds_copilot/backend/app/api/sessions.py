"""Chat session CRUD endpoints."""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from ..core.config import Settings, get_settings
from ..services import chat_store

log = logging.getLogger(__name__)

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


# ── AI-generated chat titles ──────────────────────────────────────────────


class GenerateTitleRequest(BaseModel):
    messages: list[dict[str, Any]]


_TITLE_SYSTEM_PROMPT = (
    "You generate concise titles for chat conversations. "
    "Read the conversation and reply with a single short title — "
    "3 to 6 words, no surrounding quotes, no trailing punctuation, "
    "Title Case. Do not add any explanation or preamble; output only the title."
)


def _fallback_title(messages: list[dict[str, Any]]) -> str:
    for m in messages:
        if m.get("role") == "user":
            txt = str(m.get("content", "")).strip().splitlines()[0]
            return (txt[:60] + "…") if len(txt) > 60 else (txt or "New Chat")
    return "New Chat"


@router.post("/{session_id}/generate-title")
async def generate_title(
    session_id: str,
    body: GenerateTitleRequest,
    request: Request,
    settings: Settings = Depends(get_settings),
):
    """Ask the LLM for a short, human-friendly title for this conversation
    (similar to ChatGPT's auto-titling). Persists the title and returns it.
    """
    existing = chat_store.get_session(_data_root(settings), session_id)
    if existing is None:
        raise HTTPException(404, "Session not found")

    # Build a compact transcript — first ~6 messages, each clipped to 600 chars
    lines: list[str] = []
    for m in body.messages[:6]:
        role = str(m.get("role", "user")).upper()
        content = str(m.get("content", "")).strip()
        if len(content) > 600:
            content = content[:600] + "…"
        if content:
            lines.append(f"{role}: {content}")
    transcript = "\n\n".join(lines)
    user_prompt = (
        "Conversation:\n\n" + transcript + "\n\nReply with just the title."
    )

    title = _fallback_title(body.messages)
    try:
        llm = request.app.state.llm
        raw = await llm.generate(
            user_prompt=user_prompt,
            context="",
            system_prompt=_TITLE_SYSTEM_PROMPT,
        )
        # Sanitize: first line, strip quotes/markdown, cap length
        cleaned = (raw or "").strip().splitlines()[0].strip()
        cleaned = cleaned.strip('"\'`*_ ').rstrip(".")
        if cleaned:
            title = cleaned[:80]
    except Exception as e:  # noqa: BLE001
        log.warning("generate_title LLM call failed for %s: %s", session_id, e)

    chat_store.update_session(_data_root(settings), session_id, body.messages, title)
    return {"title": title}
