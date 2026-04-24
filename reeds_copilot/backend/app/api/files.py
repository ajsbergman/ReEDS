"""File browsing and preview endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from ..core.config import Settings, get_settings
from ..models.schemas import FileListResponse, FileEntry, FilePreviewResponse
from ..services.file_inspector import list_directory, preview_file

router = APIRouter(prefix="/files", tags=["files"])


@router.get("/list", response_model=FileListResponse)
def list_files(
    path: str = Query(default=".", description="Relative path inside the repo"),
    settings: Settings = Depends(get_settings),
):
    try:
        entries = list_directory(settings.repo_root, path)
    except (FileNotFoundError, PermissionError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return FileListResponse(
        path=path,
        entries=[FileEntry(**e) for e in entries],
    )


@router.get("/preview", response_model=FilePreviewResponse)
def preview(
    path: str = Query(..., description="Relative path inside the repo"),
    settings: Settings = Depends(get_settings),
):
    try:
        result = preview_file(settings.repo_root, path, settings)
    except (FileNotFoundError, PermissionError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return FilePreviewResponse(**result)
