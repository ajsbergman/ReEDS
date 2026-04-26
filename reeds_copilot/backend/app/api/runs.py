"""API endpoints for launching and monitoring ReEDS runs."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from ..core.config import Settings, get_settings
from ..services import run_manager
from ..services import env_check

router = APIRouter(prefix="/runs", tags=["runs"])


# ── Request / Response models ────────────────────────────────────────────────

class StartRunRequest(BaseModel):
    batch_name: str = Field(..., min_length=1, max_length=50)
    cases_suffix: str = ""
    cases: list[str] = []
    simult_runs: int = Field(default=1, ge=1, le=32)
    target: Literal["local", "hpc"] = "local"
    conda_env: str = "reeds2"
    overwrite: bool = False


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
        raise HTTPException(status_code=501, detail="HPC runs not yet implemented")

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
    import re
    safe_case = re.compile(r"^[a-zA-Z0-9_\-\.]+$")
    runs_dir = settings.repo_root / "runs"

    for case in cases:
        if not safe_case.match(case):
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
    import re
    safe_case = re.compile(r"^[a-zA-Z0-9_\-\.]+$")
    if not safe_case.match(case):
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
    import re
    safe_name = re.compile(r"^[a-zA-Z0-9_\-\.]+$")

    # Resolve per-case filenames
    case_filenames: dict[str, str] = {}
    if body.filenames:
        for case in body.cases:
            fn = body.filenames.get(case)
            if not fn or not safe_name.match(fn):
                raise HTTPException(status_code=400, detail=f"Invalid filename for {case}")
            case_filenames[case] = fn
    else:
        if not body.filename or not safe_name.match(body.filename):
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

import subprocess, threading, time, uuid

_pp_jobs: dict[str, dict] = {}  # job_id -> {status, type, log, cases, ...}

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
    startyear: int = 2020
    skip_bokehpivot: bool = False
    bpreport: str = "standard_report_reduced"
    detailed: bool = False
    conda_env: str = "reeds2"


class PPBokehReportRequest(BaseModel):
    cases: list[str] = Field(..., min_length=1, max_length=20)
    report: str = "standard_report_reduced"
    diff: bool = True
    basecase: str = ""
    conda_env: str = "reeds2"


def _run_pp_job(job_id: str, cmd: "list[str] | str", cwd: str, env: dict | None = None):
    """Run a post-processing command in background, capturing output."""
    job = _pp_jobs[job_id]
    job["status"] = "running"
    job["started_at"] = time.time()
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
    import re, shutil
    safe = re.compile(r"^[a-zA-Z0-9_\-\.]+$")
    runs_dir = settings.repo_root / "runs"

    case_paths = []
    for case in body.cases:
        if not safe.match(case):
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
    _pp_jobs[job_id] = {
        "id": job_id,
        "type": "compare_cases",
        "status": "queued",
        "cases": body.cases,
        "log": "",
        "output_dir": str(runs_dir / body.cases[0] / "outputs" / "comparisons"),
    }

    shell_cmd = f"{activate_cmd}{subprocess.list2cmdline(cmd)}"
    t = threading.Thread(
        target=_run_pp_job,
        args=(job_id, shell_cmd if activate_cmd else cmd, str(settings.repo_root)),
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
    import re, shutil
    safe = re.compile(r"^[a-zA-Z0-9_\-\.]+$")
    runs_dir = settings.repo_root / "runs"

    case_paths = []
    for case in body.cases:
        if not safe.match(case):
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

    import pandas as _pd
    bp_colors = ["#1f77b4","#ff7f0e","#2ca02c","#d62728","#9467bd","#8c564b","#e377c2","#7f7f7f","#bcbd22","#17becf"] * 20
    base = body.basecase or body.cases[0]
    df_scen = _pd.DataFrame({
        "name": body.cases,
        "color": bp_colors[:len(body.cases)],
        "path": case_paths,
    })
    scen_csv = str(output_dir / "scenarios.csv")
    df_scen.to_csv(scen_csv, index=False)

    cmd = [
        "python", str(interface_py),
        "ReEDS 2.0", scen_csv, "all",
        "Yes" if body.diff else "No",
        base,
        str(report_py), "html,excel", "one",
        bp_outpath, "No",
    ]

    conda_prefix = shutil.which("conda")
    activate_cmd = f"conda activate {body.conda_env} && " if conda_prefix else ""

    job_id = str(uuid.uuid4())[:8]
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
        daemon=True,
    )
    t.start()
    return {"job_id": job_id, "status": "queued"}


@router.get("/postprocess/jobs")
def list_pp_jobs():
    """List all post-processing jobs."""
    return {"jobs": list(_pp_jobs.values())}


@router.get("/postprocess/jobs/{job_id}")
def get_pp_job(job_id: str):
    """Get status/log of a post-processing job."""
    job = _pp_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.get("/postprocess/jobs/{job_id}/outputs")
def list_pp_outputs(job_id: str, settings: Settings = Depends(get_settings)):
    """List output files from a completed PP job."""
    job = _pp_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    out_dir = Path(job["output_dir"])
    if not out_dir.is_dir():
        return {"files": []}
    files = []
    for f in sorted(out_dir.rglob("*")):
        if f.is_file():
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
