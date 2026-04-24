"""Search endpoint."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from ..core.config import Settings, get_settings
from ..models.schemas import SearchRequest, SearchResponse, SearchResult
from ..services.retrieval import text_search

router = APIRouter(tags=["search"])


@router.post("/search", response_model=SearchResponse)
def search(body: SearchRequest, request: Request, settings: Settings = Depends(get_settings)):
    repo_index = request.app.state.repo_index
    category = body.category if body.category != "all" else None
    hits = text_search(repo_index, body.query, category=category, max_results=body.max_results)
    results = [
        SearchResult(file_path=h.file_path, snippet=h.snippet, match_type=h.match_type, score=h.score)
        for h in hits
    ]
    return SearchResponse(results=results, total=len(results))
