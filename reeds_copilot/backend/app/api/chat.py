"""Chat endpoint."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request

from ..core.config import Settings, get_settings
from ..models.schemas import ChatRequest, ChatResponse, SourceSnippet
from ..services.retrieval import text_search
from ..services.tools import registry  # noqa: F401 – import registers all tools
from ..services.tool_registry import registry as tool_registry
from ..services.llm import TOOL_SYSTEM_PROMPT

log = logging.getLogger(__name__)

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


def _is_run_output(file_path: str) -> bool:
    """Check if a file path is from a run's outputs directory."""
    parts = file_path.replace("\\", "/").split("/")
    # Match patterns like runs/<name>/outputs/...
    for i, p in enumerate(parts):
        if p == "runs" and i + 2 < len(parts) and parts[i + 2] == "outputs":
            return True
    return False


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

    # Build tool executor bound to this repo
    def _exec(tool_name: str, tool_input: dict) -> tuple[str, list[dict]]:
        return tool_registry.execute(settings.repo_root, tool_name, tool_input)

    try:
        if llm.supports_tools:
            # When tools are available, strip run output data from context
            # so the LLM is forced to use tools for run-specific queries.
            tool_sources = [s for s in sources if not _is_run_output(s.file_path)]
            tool_context = _build_context(tool_sources, selected_content)
            answer, attachments = await llm.generate_with_tools(
                user_prompt=user_prompt,
                context=tool_context,
                system_prompt=TOOL_SYSTEM_PROMPT,
                tools=tool_registry.to_anthropic(),
                execute_tool_fn=_exec,
            )
        else:
            answer = await llm.generate(user_prompt=user_prompt, context=context)
            attachments = []
    except Exception as exc:
        log.error("LLM generation failed: %s", exc, exc_info=True)
        # Surface the actual error so the user can diagnose (auth, model name, network, etc.)
        err_msg = str(exc).strip() or exc.__class__.__name__
        # Truncate huge tracebacks
        if len(err_msg) > 600:
            err_msg = err_msg[:600] + "…"
        answer = (
            f"**LLM Error:** {err_msg}\n\n"
            "_Check your API key, model name, and network in **Settings**. "
            "If the error mentions an unknown model, your provider may not support the selected model._"
        )
        attachments = []

    return ChatResponse(answer=answer, sources=sources, attachments=attachments)
