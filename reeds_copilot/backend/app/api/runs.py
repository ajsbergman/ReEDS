"""API endpoints for launching and monitoring ReEDS runs."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Literal

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from ..core.config import Settings, get_settings
from ..services import run_manager
from ..services import env_check

router = APIRouter(prefix="/runs", tags=["runs"])

# Shared regex for validating case/file names
SAFE_NAME_RE = re.compile(r"^[a-zA-Z0-9_\-\.]+$")


# ── Request / Response models ────────────────────────────────────────────────

class StartRunRequest(BaseModel):
    batch_name: str = Field(..., min_length=1, max_length=50)
    cases_suffix: str = ""
    cases: list[str] = []
    simult_runs: int = Field(default=1, ge=1, le=32)
    target: Literal["local", "hpc"] = "local"
    conda_env: str = "reeds2"
    overwrite: bool = False
    # HPC connection fields
    hpc_host: str = ""       # e.g. "kestrel.hpc.nlr.gov"
    hpc_user: str = ""       # SSH username
    hpc_password: str = ""   # SSH password (optional if key auth)
    hpc_reeds_path: str = "" # Absolute path to ReEDS on remote HPC
    # Slurm fields
    slurm_account: str = ""
    slurm_walltime: str = "2-00:00:00"
    slurm_partition: str = ""
    slurm_memory: str = "246000"
    slurm_mail_user: str = ""
    slurm_mail_type: str = ""  # comma-separated: BEGIN,END,FAIL


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.get("/conda-envs")
def list_conda_envs():
    """List available conda environments."""
    return run_manager.list_conda_envs()


@router.get("/env-check")
def run_env_check(conda_env: str = "reeds2", settings: Settings = Depends(get_settings)):
    """Run all environment health checks."""
    return env_check.run_all_checks(settings.repo_root, conda_env)


class FixRequest(BaseModel):
    check_name: str
    conda_env: str = "reeds2"


@router.post("/env-fix")
def run_env_fix(body: FixRequest, settings: Settings = Depends(get_settings)):
    """Attempt to fix a failing environment check."""
    if body.check_name == "manifest":
        return env_check.fix_manifest(settings.repo_root)
    elif body.check_name == "conda_env":
        return env_check.fix_conda_env(body.conda_env, settings.repo_root)
    else:
        raise HTTPException(status_code=400, detail=f"No auto-fix available for '{body.check_name}'")


class SaveGamsLicenseRequest(BaseModel):
    content: str


@router.post("/gams-license")
def save_gams_license(body: SaveGamsLicenseRequest, settings: Settings = Depends(get_settings)):
    """Save GAMS license content to gamslice.txt."""
    return env_check.save_gamslice(settings.repo_root, body.content)


@router.get("/gams-license")
def get_gams_license(settings: Settings = Depends(get_settings)):
    """Get current GAMS license content (if it exists)."""
    p = settings.repo_root / "gamslice.txt"
    if not p.exists():
        return {"exists": False, "content": ""}
    try:
        return {"exists": True, "content": p.read_text(encoding="utf-8")}
    except Exception:
        return {"exists": False, "content": ""}


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
        if not body.hpc_host:
            raise HTTPException(status_code=400, detail="HPC login node (hpc_host) is required")
        if not body.hpc_user:
            raise HTTPException(status_code=400, detail="HPC username (hpc_user) is required")
        if not body.hpc_reeds_path:
            raise HTTPException(status_code=400, detail="Remote ReEDS path (hpc_reeds_path) is required")
        try:
            rec = run_manager.start_hpc_run(
                repo_root=settings.repo_root,
                batch_name=body.batch_name,
                cases_suffix=body.cases_suffix,
                cases=body.cases or None,
                simult_runs=body.simult_runs,
                conda_env=body.conda_env,
                overwrite=body.overwrite,
                hpc_host=body.hpc_host,
                hpc_user=body.hpc_user,
                hpc_password=body.hpc_password,
                hpc_reeds_path=body.hpc_reeds_path,
                slurm_account=body.slurm_account,
                slurm_walltime=body.slurm_walltime,
                slurm_partition=body.slurm_partition,
                slurm_memory=body.slurm_memory,
                slurm_mail_user=body.slurm_mail_user,
                slurm_mail_type=body.slurm_mail_type,
            )
        except RuntimeError as e:
            raise HTTPException(status_code=400, detail=str(e))
        return rec.to_dict()

    rec = run_manager.start_local_run(
        repo_root=settings.repo_root,
        batch_name=body.batch_name,
        cases_suffix=body.cases_suffix,
        cases=body.cases or None,
        simult_runs=body.simult_runs,
        conda_env=body.conda_env,
        overwrite=body.overwrite,
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


@router.post("/cleanup-local")
def cleanup_local(settings: Settings = Depends(get_settings)):
    """Cancel all running local processes (called on browser close)."""
    count = run_manager.cancel_all_local(settings.repo_root)
    return {"cancelled": count}


# ── Compare Cases ────────────────────────────────────────────────────────────

@router.get("/compare/common-files")
def compare_common_files(
    cases: list[str] = Query(..., description="List of case folder names"),
    subdir: str = Query(default="", description="Subdirectory to browse within each case"),
    settings: Settings = Depends(get_settings),
):
    """Browse common entries (dirs + files) at a given level across all cases."""
    runs_dir = settings.repo_root / "runs"

    for case in cases:
        if not SAFE_NAME_RE.match(case):
            raise HTTPException(status_code=400, detail=f"Invalid case name: {case}")

    # List children of {runs}/{case}/{subdir} for each case
    skip_dirs = {"__pycache__", ".git", "node_modules"}
    per_case: list[dict[str, dict]] = []  # [{name: {is_dir, size}}]
    for case in cases:
        target = (runs_dir / case / subdir).resolve() if subdir else (runs_dir / case).resolve()
        if not str(target).startswith(str(runs_dir.resolve())):
            raise HTTPException(status_code=400, detail="Invalid path")
        if not target.is_dir():
            raise HTTPException(status_code=404, detail=f"Not a directory: {case}/{subdir}")
        entries: dict[str, dict] = {}
        for child in target.iterdir():
            if child.name.startswith(".") or child.name in skip_dirs:
                continue
            if child.is_dir():
                entries[child.name] = {"is_dir": True, "size": None}
            else:
                entries[child.name] = {"is_dir": False, "size": child.stat().st_size}
        per_case.append(entries)

    # Intersect: only names present in ALL cases
    common_names = set(per_case[0].keys())
    for pc in per_case[1:]:
        common_names &= set(pc.keys())

    # Build response entries (use first case for metadata)
    result = []
    for name in sorted(common_names):
        info = per_case[0][name]
        result.append({
            "name": name,
            "is_dir": info["is_dir"],
            "size": info["size"],
        })
    return {"subdir": subdir, "entries": result}


@router.get("/compare/case-files")
def compare_case_files(
    case: str = Query(..., description="Case folder name"),
    subdir: str = Query(default="", description="Subdirectory to browse"),
    settings: Settings = Depends(get_settings),
):
    """List files for a single case at a given subdirectory level."""
    if not SAFE_NAME_RE.match(case):
        raise HTTPException(status_code=400, detail=f"Invalid case name: {case}")

    runs_dir = settings.repo_root / "runs"
    target = (runs_dir / case / subdir).resolve() if subdir else (runs_dir / case).resolve()
    if not str(target).startswith(str(runs_dir.resolve())):
        raise HTTPException(status_code=400, detail="Invalid path")
    if not target.is_dir():
        raise HTTPException(status_code=404, detail=f"Not a directory: {case}/{subdir}")

    skip_dirs = {"__pycache__", ".git", "node_modules"}
    result = []
    for child in sorted(target.iterdir(), key=lambda c: c.name.lower()):
        if child.name.startswith(".") or child.name in skip_dirs:
            continue
        if child.is_dir():
            result.append({"name": child.name, "is_dir": True, "size": None})
        else:
            result.append({"name": child.name, "is_dir": False, "size": child.stat().st_size})
    return {"case": case, "subdir": subdir, "entries": result}


class CompareRequest(BaseModel):
    cases: list[str] = Field(..., min_length=2, max_length=20)
    filename: str = Field(default="", description="File name (same for all cases)")
    filenames: dict[str, str] | None = Field(default=None, description="Per-case file names {case: filename}")
    subdir: str = Field(default="outputs", description="Subdirectory within run folder")
    max_rows_per_case: int = Field(default=5000, ge=100, le=50000)


IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".svg", ".webp"}

TEXT_SUFFIXES = {
    ".py", ".gms", ".jl", ".r", ".sh", ".bat", ".md", ".rst", ".txt",
    ".json", ".yaml", ".yml", ".toml", ".cfg", ".ini", ".opt", ".csv",
    ".tsv", ".html", ".xml", ".sql", ".lst", ".log", ".inc", ".dd", ".gpr",
}


@router.post("/compare/data")
def compare_data(
    body: CompareRequest,
    settings: Settings = Depends(get_settings),
):
    """Compare a file across cases. Auto-detects mode based on file type."""

    # Resolve per-case filenames
    case_filenames: dict[str, str] = {}
    if body.filenames:
        for case in body.cases:
            fn = body.filenames.get(case)
            if not fn or not SAFE_NAME_RE.match(fn):
                raise HTTPException(status_code=400, detail=f"Invalid filename for {case}")
            case_filenames[case] = fn
    else:
        if not body.filename or not SAFE_NAME_RE.match(body.filename):
            raise HTTPException(status_code=400, detail="Invalid filename")
        for case in body.cases:
            case_filenames[case] = body.filename

    runs_dir = settings.repo_root / "runs"
    # Use first case's filename for suffix detection and display
    display_filename = case_filenames[body.cases[0]]
    suffix = Path(display_filename).suffix.lower()

    # Resolve paths
    paths: dict[str, Path] = {}
    for case in body.cases:
        fn = case_filenames[case]
        if body.subdir:
            file_path = (runs_dir / case / body.subdir / fn).resolve()
        else:
            file_path = (runs_dir / case / fn).resolve()
        if not str(file_path).startswith(str(runs_dir.resolve())):
            raise HTTPException(status_code=400, detail="Invalid case name")
        if not file_path.is_file():
            raise HTTPException(status_code=404, detail=f"{fn} not found in {case}")
        paths[case] = file_path

    base_resp = {
        "filename": display_filename,
        "subdir": body.subdir,
        "cases": body.cases,
    }

    # ── Image compare ──
    if suffix in IMAGE_SUFFIXES:
        # Return relative paths for the raw file endpoint
        image_paths = {}
        for case, p in paths.items():
            rel = p.relative_to(settings.repo_root)
            image_paths[case] = str(rel).replace("\\", "/")
        return {
            **base_resp,
            "mode": "image_diff",
            "image_paths": image_paths,
            "columns": [], "rows": [], "total_rows": 0,
            "index_cols": [], "value_col": None,
        }

    # ── GDX compare ──
    if suffix == ".gdx":
        try:
            from ..services.file_inspector import _gdx_list_symbols
            symbol_lists = {}
            for case, p in paths.items():
                symbol_lists[case] = _gdx_list_symbols(p)
            # Find common symbols
            name_sets = [set(s["name"] for s in syms) for syms in symbol_lists.values()]
            common = sorted(set.intersection(*name_sets)) if name_sets else []
            # Build comparison: for each common symbol, show records per case
            first_syms = {s["name"]: s for s in symbol_lists[body.cases[0]]}
            case_syms = {
                case: {s["name"]: s for s in syms}
                for case, syms in symbol_lists.items()
            }
            rows = []
            for name in common:
                row: dict = {"name": name, "type": first_syms[name]["type"], "dims": first_syms[name]["dims"]}
                for case in body.cases:
                    row[case] = case_syms[case].get(name, {}).get("records", 0)
                rows.append(row)
            columns = ["name", "type", "dims"] + list(body.cases)
            return {
                **base_resp,
                "mode": "gdx_diff",
                "columns": columns,
                "rows": rows,
                "total_rows": len(rows),
                "index_cols": ["name", "type", "dims"],
                "value_col": None,
                "gdx_total_symbols": {case: len(syms) for case, syms in symbol_lists.items()},
                "gdx_common_count": len(common),
            }
        except Exception as exc:
            return {
                **base_resp,
                "mode": "text_diff",
                "texts": {case: f"Error reading GDX: {exc}" for case in body.cases},
                "columns": [], "rows": [], "total_rows": 0,
                "index_cols": [], "value_col": None,
            }

    # ── CSV compare ──
    if suffix == ".csv":
        frames: dict[str, pd.DataFrame] = {}
        for case, p in paths.items():
            try:
                df = pd.read_csv(p, nrows=body.max_rows_per_case, low_memory=False)
                frames[case] = df
            except Exception as exc:
                raise HTTPException(status_code=400, detail=f"Error reading {case}/{body.filename}: {exc}")

        sample = next(iter(frames.values()))
        value_cols = [c for c in sample.columns if c.lower() == "value"]
        index_cols = [c for c in sample.columns if c.lower() != "value"]

        if value_cols:
            # Side-by-side merge on index columns
            val_col = value_cols[0]
            case_names = list(frames.keys())
            merged = frames[case_names[0]][index_cols].drop_duplicates()
            for case in case_names:
                renamed = frames[case].rename(columns={val_col: case})
                merged = merged.merge(renamed[index_cols + [case]], on=index_cols, how="outer")

            for case in case_names:
                merged[case] = pd.to_numeric(merged[case], errors="coerce")

            if len(case_names) == 2:
                merged["diff"] = merged[case_names[0]] - merged[case_names[1]]
                merged["pct_diff"] = (
                    merged["diff"] / merged[case_names[1]].replace(0, float("nan")) * 100
                ).round(2)
            else:
                merged["diff"] = merged[case_names].max(axis=1) - merged[case_names].min(axis=1)

            try:
                merged = merged.sort_values(index_cols).reset_index(drop=True)
            except Exception:
                pass

            rows = merged.astype(object).where(merged.notna(), None).to_dict(orient="records")
            return {
                **base_resp,
                "mode": "side_by_side",
                "columns": list(merged.columns),
                "rows": rows,
                "total_rows": len(rows),
                "index_cols": index_cols,
                "value_col": val_col,
            }
        else:
            # No Value column — show side-by-side tables per case
            all_cols = list(sample.columns)
            case_tables: dict[str, list[dict]] = {}
            for case in body.cases:
                df = frames[case].head(body.max_rows_per_case)
                clean = df.astype(object).where(df.notna(), None)
                case_tables[case] = clean.to_dict(orient="records")
            return {
                **base_resp,
                "mode": "csv_table",
                "columns": all_cols,
                "rows": [],
                "total_rows": max(len(v) for v in case_tables.values()),
                "index_cols": all_cols,
                "value_col": None,
                "case_tables": case_tables,
            }

    # ── Text compare (fallback) ──
    if suffix in TEXT_SUFFIXES or suffix == "":
        texts = {}
        for case, p in paths.items():
            try:
                texts[case] = p.read_text(encoding="utf-8", errors="replace")[:200_000]
            except Exception:
                texts[case] = "(could not read file)"
        return {
            **base_resp,
            "mode": "text_diff",
            "texts": texts,
            "columns": [], "rows": [], "total_rows": 0,
            "index_cols": [], "value_col": None,
        }

    # ── Unsupported ──
    return {
        **base_resp,
        "mode": "unsupported",
        "columns": [], "rows": [], "total_rows": 0,
        "index_cols": [], "value_col": None,
        "texts": {case: f"(binary file: {suffix})" for case in body.cases},
    }


# ── Post-Processing Tools ────────────────────────────────────────────────────

_pp_jobs: dict[str, dict] = {}  # job_id -> {status, type, log, cases, ...}
_pp_jobs_loaded = False
_MAX_PP_JOBS = 50  # Keep last N jobs to avoid memory leak
_PP_JOBS_DIR = "pp_job_history"


def _pp_jobs_dir(repo_root: Path) -> Path:
    d = repo_root / "reeds_copilot" / _PP_JOBS_DIR
    d.mkdir(parents=True, exist_ok=True)
    return d


def _persist_pp_job(repo_root: Path, job: dict):
    """Save a PP job record to disk."""
    # Don't persist the full log to disk — it can be huge
    data = {k: v for k, v in job.items() if k != "log"}
    data["log_tail"] = (job.get("log") or "")[-2000:]
    path = _pp_jobs_dir(repo_root) / f"{job['id']}.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_pp_jobs(repo_root: Path):
    """Load previously persisted PP jobs into memory (once on startup)."""
    global _pp_jobs_loaded
    if _pp_jobs_loaded:
        return
    _pp_jobs_loaded = True
    d = repo_root / "reeds_copilot" / _PP_JOBS_DIR
    if not d.exists():
        return
    for p in d.glob("*.json"):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            jid = data.get("id", p.stem)
            if jid in _pp_jobs:
                continue  # already in memory (running)
            # Restore log from log_tail
            data["log"] = data.pop("log_tail", "")
            # Mark incomplete jobs as failed (server restarted)
            if data.get("status") in ("queued", "running"):
                data["status"] = "failed"
                data["log"] += "\n[server restarted — job was interrupted]"
            _pp_jobs[jid] = data
        except Exception:
            pass

BOKEH_REPORTS = [
    "standard_report_reduced",
    "standard_report",
    "standard_report_expanded",
    "standard_report_combined",
    "standard_report_CCS",
    "standard_report_RE100",
    "gen_only_report",
    "opres_report",
    "state_report",
    "value_factor_report",
]


class PPCompareCasesRequest(BaseModel):
    cases: list[str] = Field(..., min_length=2, max_length=20)
    casenames: str = ""
    basecase: str = ""
    startyear: int = 2010
    skip_bokehpivot: bool = True
    bpreport: str = "standard_report_reduced"
    detailed: bool = False
    conda_env: str = "reeds2"


class PPBokehReportRequest(BaseModel):
    cases: list[str] = Field(..., min_length=1, max_length=20)
    casenames: str = ""
    report: str = "standard_report_reduced"
    diff: bool = True
    basecase: str = ""
    conda_env: str = "reeds2"


def _run_pp_job(job_id: str, cmd: "list[str] | str", cwd: str,
                env: dict | None = None, repo_root: Path | None = None):
    """Run a post-processing command in background, capturing output."""
    job = _pp_jobs[job_id]
    job["status"] = "running"
    job["started_at"] = time.time()
    if repo_root:
        _persist_pp_job(repo_root, job)
    try:
        use_shell = isinstance(cmd, str)
        proc = subprocess.Popen(
            cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, env=env, shell=use_shell,
        )
        job["pid"] = proc.pid
        lines: list[str] = []
        for line in proc.stdout:  # type: ignore[union-attr]
            lines.append(line)
            if len(lines) > 5000:
                lines = lines[-3000:]
        proc.wait()
        job["log"] = "".join(lines[-2000:])
        job["returncode"] = proc.returncode
        job["status"] = "completed" if proc.returncode == 0 else "failed"
    except Exception as exc:
        job["log"] = str(exc)
        job["status"] = "failed"
    job["finished_at"] = time.time()
    if repo_root:
        _persist_pp_job(repo_root, job)


def _trim_pp_jobs(repo_root: Path | None = None):
    """Remove oldest finished jobs when exceeding _MAX_PP_JOBS."""
    if len(_pp_jobs) <= _MAX_PP_JOBS:
        return
    finished = sorted(
        ((k, v) for k, v in _pp_jobs.items() if v["status"] in ("completed", "failed")),
        key=lambda kv: kv[1].get("finished_at", 0),
    )
    to_remove = len(_pp_jobs) - _MAX_PP_JOBS
    for k, _ in finished[:to_remove]:
        del _pp_jobs[k]
        if repo_root:
            fp = _pp_jobs_dir(repo_root) / f"{k}.json"
            if fp.exists():
                fp.unlink()


@router.get("/postprocess/reports")
def list_bokeh_reports():
    """List available bokehpivot report templates."""
    return {"reports": BOKEH_REPORTS}


@router.post("/postprocess/compare-cases")
def run_compare_cases(
    body: PPCompareCasesRequest,
    settings: Settings = Depends(get_settings),
):
    """Run compare_cases.py as a background process."""
    runs_dir = settings.repo_root / "runs"

    case_paths = []
    for case in body.cases:
        if not SAFE_NAME_RE.match(case):
            raise HTTPException(status_code=400, detail=f"Invalid case name: {case}")
        p = runs_dir / case
        if not p.is_dir():
            raise HTTPException(status_code=404, detail=f"Case not found: {case}")
        case_paths.append(str(p))

    script = str(settings.repo_root / "postprocessing" / "compare_cases.py")
    cmd = ["python", script] + case_paths
    if body.casenames:
        cmd += ["--casenames", body.casenames]
    if body.basecase:
        cmd += ["--basecase", body.basecase]
    cmd += ["--startyear", str(body.startyear)]
    if body.skip_bokehpivot:
        cmd += ["--skipbp"]
    else:
        cmd += ["--bpreport", body.bpreport]
    if body.detailed:
        cmd += ["--detailed"]

    # Activate conda env
    conda_prefix = shutil.which("conda")
    activate_cmd = f"conda activate {body.conda_env} && " if conda_prefix else ""

    job_id = str(uuid.uuid4())[:8]
    _trim_pp_jobs(settings.repo_root)
    _pp_jobs[job_id] = {
        "id": job_id,
        "type": "compare_cases",
        "status": "queued",
        "cases": body.cases,
        "log": "",
        "output_dir": str(runs_dir / body.cases[0] / "outputs" / "comparisons"),
    }

    shell_cmd = f"{activate_cmd}{subprocess.list2cmdline(cmd)}"
    # Suppress auto-open of generated files (e.g. PPTX) when running headlessly
    no_open_env = {**os.environ, "REEDS_NO_AUTOOPEN": "1"}
    t = threading.Thread(
        target=_run_pp_job,
        args=(job_id, shell_cmd if activate_cmd else cmd, str(settings.repo_root)),
        kwargs={"env": no_open_env, "repo_root": settings.repo_root},
        daemon=True,
    )
    t.start()
    return {"job_id": job_id, "status": "queued"}


@router.post("/postprocess/bokeh-report")
def run_bokeh_report(
    body: PPBokehReportRequest,
    settings: Settings = Depends(get_settings),
):
    """Run a bokehpivot report as a background process."""
    runs_dir = settings.repo_root / "runs"

    case_paths = []
    for case in body.cases:
        if not SAFE_NAME_RE.match(case):
            raise HTTPException(status_code=400, detail=f"Invalid case name: {case}")
        p = runs_dir / case
        if not p.is_dir():
            raise HTTPException(status_code=404, detail=f"Case not found: {case}")
        case_paths.append(str(p))

    if body.report not in BOKEH_REPORTS:
        raise HTTPException(status_code=400, detail=f"Unknown report: {body.report}")

    bp_path = settings.repo_root / "postprocessing" / "bokehpivot"
    report_py = bp_path / "reports" / "templates" / "reeds2" / f"{body.report}.py"
    interface_py = bp_path / "reports" / "interface_report_model.py"

    # Build scenarios CSV
    output_dir = runs_dir / body.cases[0] / "outputs" / "comparisons"
    output_dir.mkdir(parents=True, exist_ok=True)
    bp_outpath = str(output_dir / f"{body.report}-{'diff' if body.diff else 'nodiff'}-multicase")

    bp_colors = ["#1f77b4","#ff7f0e","#2ca02c","#d62728","#9467bd","#8c564b","#e377c2","#7f7f7f","#bcbd22","#17becf"] * 20
    base = body.basecase or body.cases[0]
    # Use display names if provided, otherwise use case folder names
    display_names = body.casenames.split(",") if body.casenames else body.cases
    if len(display_names) != len(body.cases):
        display_names = body.cases
    # Resolve base to its display name so bokeh diff can match it
    base_display = base
    for orig, disp in zip(body.cases, display_names):
        if orig == base:
            base_display = disp
            break
    df_scen = pd.DataFrame({
        "name": display_names,
        "color": bp_colors[:len(body.cases)],
        "path": case_paths,
    })
    scen_csv = str(output_dir / "scenarios.csv")
    df_scen.to_csv(scen_csv, index=False)

    cmd = [
        "python", str(interface_py),
        "ReEDS 2.0", scen_csv, "all",
        "Yes" if body.diff else "No",
        base_display,
        str(report_py), "html,excel", "one",
        bp_outpath, "No",
    ]

    conda_prefix = shutil.which("conda")
    activate_cmd = f"conda activate {body.conda_env} && " if conda_prefix else ""

    job_id = str(uuid.uuid4())[:8]
    _trim_pp_jobs(settings.repo_root)
    _pp_jobs[job_id] = {
        "id": job_id,
        "type": "bokeh_report",
        "status": "queued",
        "cases": body.cases,
        "report": body.report,
        "log": "",
        "output_dir": bp_outpath,
    }

    shell_cmd = f"{activate_cmd}{subprocess.list2cmdline(cmd)}"
    final_cmd = shell_cmd if activate_cmd else cmd
    t = threading.Thread(
        target=_run_pp_job,
        args=(job_id, final_cmd, str(settings.repo_root)),
        kwargs={"repo_root": settings.repo_root},
        daemon=True,
    )
    t.start()
    return {"job_id": job_id, "status": "queued"}


@router.get("/postprocess/jobs")
def list_pp_jobs(settings: Settings = Depends(get_settings)):
    """List all post-processing jobs."""
    _load_pp_jobs(settings.repo_root)
    return {"jobs": list(_pp_jobs.values())}


@router.get("/postprocess/jobs/{job_id}")
def get_pp_job(job_id: str, settings: Settings = Depends(get_settings)):
    """Get status/log of a post-processing job."""
    _load_pp_jobs(settings.repo_root)
    job = _pp_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.delete("/postprocess/jobs/{job_id}")
def delete_pp_job(job_id: str, settings: Settings = Depends(get_settings)):
    """Delete a post-processing job record."""
    _load_pp_jobs(settings.repo_root)
    job = _pp_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.get("status") in ("queued", "running"):
        raise HTTPException(status_code=400, detail="Cannot delete a running job")
    del _pp_jobs[job_id]
    fp = _pp_jobs_dir(settings.repo_root) / f"{job_id}.json"
    if fp.exists():
        fp.unlink()
    return {"ok": True}


@router.get("/postprocess/jobs/{job_id}/outputs")
def list_pp_outputs(job_id: str, settings: Settings = Depends(get_settings)):
    """List output files from a completed PP job."""
    _load_pp_jobs(settings.repo_root)
    job = _pp_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    out_dir = Path(job["output_dir"])
    if not out_dir.is_dir():
        return {"files": []}
    job_started = job.get("started_at", 0)
    job_type = job.get("type", "")
    # Only show file types relevant to each job type
    type_suffixes = {
        "compare_cases": {".pptx"},
        "bokeh_report": {".html"},
    }
    allowed = type_suffixes.get(job_type)
    files = []
    for f in sorted(out_dir.rglob("*")):
        if not f.is_file():
            continue
        if f.stat().st_mtime < job_started:
            continue
        if allowed and f.suffix.lower() not in allowed:
            continue
        rel = str(f.relative_to(settings.repo_root)).replace("\\", "/")
        files.append({
            "name": f.name,
            "rel_path": rel,
            "size": f.stat().st_size,
            "suffix": f.suffix.lower(),
        })
    return {"files": files}


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
    rec = run_manager.get_run(run_id)
    if not rec:
        raise HTTPException(status_code=404, detail="Run not found")
    if rec.get("target") == "hpc":
        ok = run_manager.cancel_hpc_run(settings.repo_root, run_id)
    else:
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
