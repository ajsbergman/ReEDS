"""API endpoints for launching and monitoring ReEDS runs."""
from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..core.config import Settings, get_settings
from ..services import run_manager

router = APIRouter(prefix="/runs", tags=["runs"])


# ── Request / Response models ────────────────────────────────────────────────

class StartRunRequest(BaseModel):
    batch_name: str = Field(..., min_length=1, max_length=200)
    cases_suffix: str = ""
    cases: list[str] = []
    simult_runs: int = Field(default=1, ge=1, le=32)
    target: Literal["local", "hpc"] = "local"
    conda_env: str = "reeds2"


class RunListItem(BaseModel):
    id: str
    batch_name: str
    cases_suffix: str
    cases: list[str]
    simult_runs: int
    target: str
    status: str
    created_at: float
    finished_at: float | None
    error: str | None


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.get("/conda-envs")
def list_conda_envs():
    """List available conda environments."""
    return run_manager.list_conda_envs()


@router.get("/cases-files")
def list_cases_files(settings: Settings = Depends(get_settings)):
    """List available cases_*.csv files and their case names."""
    return run_manager.list_cases_files(settings.repo_root)


@router.get("/cases-files/{suffix}")
def get_cases_detail(suffix: str, settings: Settings = Depends(get_settings)):
    """Get detailed switches for a specific cases file."""
    data = run_manager.get_case_details(settings.repo_root, suffix)
    if "error" in data:
        raise HTTPException(status_code=404, detail=data["error"])
    return data


@router.post("", status_code=201)
def start_run(body: StartRunRequest, settings: Settings = Depends(get_settings)):
    """Start a new ReEDS run."""
    if body.target == "hpc":
        raise HTTPException(status_code=501, detail="HPC runs not yet implemented")

    rec = run_manager.start_local_run(
        repo_root=settings.repo_root,
        batch_name=body.batch_name,
        cases_suffix=body.cases_suffix,
        cases=body.cases or None,
        simult_runs=body.simult_runs,
        conda_env=body.conda_env,
    )
    return rec.to_dict()


@router.get("")
def list_runs():
    """List all runs (newest first)."""
    return run_manager.list_runs()


@router.get("/folders/list")
def list_run_folders(settings: Settings = Depends(get_settings)):
    """List run folders under {repo}/runs/."""
    return run_manager.list_run_folders(settings.repo_root)


@router.get("/{run_id}")
def get_run(run_id: str):
    """Get details of a specific run (including log tail)."""
    data = run_manager.get_run(run_id)
    if not data:
        raise HTTPException(status_code=404, detail="Run not found")
    return data


@router.post("/{run_id}/cancel")
def cancel_run(run_id: str, settings: Settings = Depends(get_settings)):
    """Cancel a running ReEDS run."""
    ok = run_manager.cancel_run(settings.repo_root, run_id)
    if not ok:
        raise HTTPException(status_code=400, detail="Run not found or not running")
    return {"success": True}


@router.delete("/{run_id}")
def delete_run(run_id: str, settings: Settings = Depends(get_settings)):
    """Delete a run record (only completed/failed/cancelled)."""
    ok = run_manager.delete_run(settings.repo_root, run_id)
    if not ok:
        raise HTTPException(status_code=400, detail="Run not found or still running")
    return {"success": True}
