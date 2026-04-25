"""File browsing and preview endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse

from ..core.config import Settings, get_settings
from ..models.schemas import FileListResponse, FileEntry, FilePreviewResponse
from ..services.file_inspector import list_directory, preview_file, safe_resolve

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
    full: bool = Query(False, description="Return full file content (up to 10 MB)"),
    settings: Settings = Depends(get_settings),
):
    try:
        result = preview_file(settings.repo_root, path, settings, full=full)
    except (FileNotFoundError, PermissionError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return FilePreviewResponse(**result)


@router.get("/download")
def download_file(
    path: str = Query(..., description="Relative path inside the repo"),
    settings: Settings = Depends(get_settings),
):
    """Stream the full file as a download."""
    try:
        target = safe_resolve(settings.repo_root, path)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    if not target.is_file():
        raise HTTPException(status_code=404, detail=f"Not a file: {path}")
    return FileResponse(
        path=str(target),
        filename=target.name,
        media_type="application/octet-stream",
    )
