"""Chat endpoint."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from ..core.config import Settings, get_settings
from ..models.schemas import ChatRequest, ChatResponse, SourceSnippet
from ..services.retrieval import text_search

router = APIRouter(tags=["chat"])

MODE_CATEGORY_MAP = {
    "general": None,
    "docs": "docs",
    "code": "code",
    "inputs": "inputs",
    "outputs": "outputs",
}


def _build_context(sources: list[SourceSnippet], selected_content: str | None) -> str:
    parts: list[str] = []
    if selected_content:
        parts.append(f"<selected_file>\n{selected_content}\n</selected_file>")
    for src in sources:
        parts.append(f"--- {src.file_path} ---\n{src.snippet}")
    return "\n\n".join(parts)


@router.post("/chat", response_model=ChatResponse)
async def chat(body: ChatRequest, request: Request, settings: Settings = Depends(get_settings)):
    repo_index = request.app.state.repo_index
    llm = request.app.state.llm

    # Retrieve context
    category = MODE_CATEGORY_MAP.get(body.mode)
    hits = text_search(repo_index, body.message, category=category, max_results=settings.max_retrieval_results)
    sources = [
        SourceSnippet(file_path=h.file_path, snippet=h.snippet, match_type=h.match_type, score=h.score)
        for h in hits
    ]

    # Optionally load selected file
    selected_content: str | None = None
    if body.selected_path:
        from ..services.file_inspector import safe_resolve
        try:
            target = safe_resolve(settings.repo_root, body.selected_path)
            if target.is_file() and target.stat().st_size < 256 * 1024:
                selected_content = target.read_text(encoding="utf-8", errors="replace")
        except Exception:
            pass

    context = _build_context(sources, selected_content)

    mode_hint = f"The user is in '{body.mode}' mode."
    user_prompt = f"{mode_hint}\n\nUser question: {body.message}"

    try:
        answer = await llm.generate(user_prompt=user_prompt, context=context)
    except Exception as exc:
        import logging
        logging.getLogger(__name__).error("LLM generation failed: %s", exc, exc_info=True)
        answer = "**LLM Error:** Could not generate response. Please check your API key and try again."

    return ChatResponse(answer=answer, sources=sources)
