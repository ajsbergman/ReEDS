"""File browsing and preview endpoints."""
from __future__ import annotations

import csv as csv_mod
import io
import logging
import re
import threading

import paramiko
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

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
    gdx_symbol: str | None = Query(None, description="GDX symbol name to preview"),
    h5_dataset: str | None = Query(None, description="HDF5 dataset path to preview"),
    settings: Settings = Depends(get_settings),
):
    try:
        result = preview_file(
            settings.repo_root, path, settings, full=full,
            gdx_symbol=gdx_symbol, h5_dataset=h5_dataset,
        )
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


IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".svg", ".webp"}
MEDIA_TYPES = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".gif": "image/gif", ".bmp": "image/bmp", ".svg": "image/svg+xml",
    ".webp": "image/webp",
    ".html": "text/html", ".htm": "text/html",
    ".csv": "text/csv", ".json": "application/json",
    ".txt": "text/plain", ".log": "text/plain",
    ".xml": "text/xml", ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


@router.get("/raw")
def raw_file(
    path: str = Query(..., description="Relative path inside the repo"),
    settings: Settings = Depends(get_settings),
):
    """Serve a file inline (e.g. images) with correct Content-Type."""
    try:
        target = safe_resolve(settings.repo_root, path)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    if not target.is_file():
        raise HTTPException(status_code=404, detail=f"Not a file: {path}")
    suffix = target.suffix.lower()
    media = MEDIA_TYPES.get(suffix, "application/octet-stream")
    return FileResponse(path=str(target), media_type=media)


# ── HPC remote file browsing (via paramiko SSH) ─────────────────────────────

log = logging.getLogger(__name__)
_SAFE_SSH_RE = re.compile(r'^[a-zA-Z0-9._\-]+$')

# Reusable SSH connection cache  {(host, user): paramiko.SSHClient}
_ssh_pool: dict[tuple[str, str], paramiko.SSHClient] = {}
_ssh_lock = threading.Lock()


class HpcListRequest(BaseModel):
    host: str = Field(..., description="HPC login node hostname")
    user: str = Field(..., description="SSH username")
    path: str = Field(..., description="Absolute path on HPC")
    password: str = Field(default="", description="SSH password (never logged)")


class HpcPreviewRequest(BaseModel):
    host: str = Field(..., description="HPC login node hostname")
    user: str = Field(..., description="SSH username")
    path: str = Field(..., description="Absolute file path on HPC")
    password: str = Field(default="", description="SSH password (never logged)")
    lines: int = Field(default=200, ge=1, le=5000)


class HpcDisconnectRequest(BaseModel):
    host: str = Field(..., description="HPC login node hostname")
    user: str = Field(..., description="SSH username")


class HpcCasesRequest(BaseModel):
    host: str = Field(..., description="HPC login node hostname")
    user: str = Field(..., description="SSH username")
    reeds_path: str = Field(..., description="Absolute path to ReEDS repo on HPC")
    password: str = Field(default="", description="SSH password (never logged)")


def _get_ssh_client(
    host: str, user: str, password: str = "",
) -> paramiko.SSHClient:
    """Return a connected paramiko SSHClient, reusing if possible."""
    if not _SAFE_SSH_RE.match(host) or not _SAFE_SSH_RE.match(user):
        raise ValueError("Invalid SSH hostname or username")

    key = (host, user)
    with _ssh_lock:
        client = _ssh_pool.get(key)
        # Check if existing connection is still alive
        if client is not None:
            transport = client.get_transport()
            if transport is not None and transport.is_active():
                return client
            # Dead connection — discard
            try:
                client.close()
            except Exception:
                pass
            _ssh_pool.pop(key, None)

        # Build a new connection
        client = paramiko.SSHClient()

        # ── Host-key verification (defense against MITM on first connect) ──
        # Always load the user's existing known_hosts so previously-trusted
        # hosts continue to work. Policy for *unknown* hosts is configurable:
        #   strict  → RejectPolicy (safe default; user must `ssh host` once
        #             from a terminal to record the key)
        #   tofu    → AutoAddPolicy (Trust-On-First-Use; convenient but
        #             vulnerable to MITM on the very first connect)
        try:
            client.load_system_host_keys()
        except Exception:
            pass  # known_hosts file may not exist yet on this machine

        policy_name = (get_settings().ssh_host_key_policy or "strict").lower()
        if policy_name == "tofu":
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        else:
            client.set_missing_host_key_policy(paramiko.RejectPolicy())

        connect_kwargs: dict = dict(
            hostname=host, username=user, timeout=15,
            allow_agent=True, look_for_keys=True,
        )
        if password:
            connect_kwargs["password"] = password

        try:
            client.connect(**connect_kwargs)
        except paramiko.AuthenticationException:
            raise HTTPException(
                status_code=401,
                detail="SSH authentication failed. Check username/password or SSH keys.",
            )
        except paramiko.SSHException as exc:
            # Most commonly: "Server '<host>' not found in known_hosts"
            msg = str(exc)
            if "not found in known_hosts" in msg or "not in known_hosts" in msg:
                raise HTTPException(
                    status_code=495,  # custom: SSL/cert-equivalent error
                    detail=(
                        f"Host key for '{host}' is not in your ~/.ssh/known_hosts. "
                        f"For your safety the connection was refused (defense against "
                        f"man-in-the-middle attacks). Run `ssh {user}@{host}` once from "
                        f"a terminal, accept the host key, then retry. "
                        f"Or set REEDS_COPILOT_SSH_POLICY=tofu to trust-on-first-use "
                        f"(less secure)."
                    ),
                )
            raise HTTPException(status_code=502, detail=f"SSH error: {msg}")
        except Exception as exc:
            raise HTTPException(
                status_code=502,
                detail=f"Cannot connect to {host}: {exc}",
            )

        _ssh_pool[key] = client
        return client


def _ssh_exec(host: str, user: str, command: str,
              password: str = "", timeout: int = 30) -> str:
    """Execute a command via paramiko and return stdout."""
    client = _get_ssh_client(host, user, password)
    try:
        _, stdout, stderr = client.exec_command(command, timeout=timeout)
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
    except Exception as exc:
        # Connection may have died — evict from pool
        with _ssh_lock:
            _ssh_pool.pop((host, user), None)
        raise HTTPException(status_code=502, detail=f"SSH command failed: {exc}")

    exit_code = stdout.channel.recv_exit_status()
    if exit_code != 0 and not out.strip():
        raise HTTPException(
            status_code=400,
            detail=err.strip()[:500] or f"Command failed (exit {exit_code})",
        )
    return out


@router.post("/hpc/list", response_model=FileListResponse)
def list_hpc_files(req: HpcListRequest):
    """List directory contents on a remote HPC node via SSH."""
    if not re.match(r'^[a-zA-Z0-9/_\.\-~]+$', req.path):
        raise HTTPException(status_code=400, detail="Invalid path characters")

    remote_cmd = f'ls -lLA --time-style=+%s {req.path} 2>/dev/null'
    out = _ssh_exec(req.host, req.user, remote_cmd, password=req.password)

    # Parse `ls -lA --time-style=+%s` output
    # drwxr-xr-x 2 user group 4096 1715270400 dirname
    entries = []
    for line in out.strip().splitlines():
        if line.startswith("total ") or not line.strip():
            continue
        parts = line.split(None, 6)
        if len(parts) < 7:
            continue
        perms, _, _, _, size_str, mtime_str, name = parts
        if name.startswith("."):
            continue
        if " -> " in name:
            name = name.split(" -> ")[0]
        is_dir = perms.startswith("d")
        try:
            size = int(size_str) if not is_dir else None
        except ValueError:
            size = None
        try:
            mtime = float(mtime_str)
        except ValueError:
            mtime = 0
        entries.append(FileEntry(
            name=name,
            rel_path=f"{req.path}/{name}",
            is_dir=is_dir,
            size=size,
            modified_at=mtime,
        ))

    return FileListResponse(path=req.path, entries=entries)


@router.post("/hpc/preview", response_model=FilePreviewResponse)
def preview_hpc_file(req: HpcPreviewRequest):
    """Preview a text file on the remote HPC via SSH."""
    if not re.match(r'^[a-zA-Z0-9/_\.\-~]+$', req.path):
        raise HTTPException(status_code=400, detail="Invalid path characters")

    name = req.path.rsplit("/", 1)[-1] if "/" in req.path else req.path
    dot = name.rfind(".")
    ext = name[dot:].lower() if dot > 0 else ""

    image_exts = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".bmp"}
    binary_exts = {".gdx", ".g00", ".xlsx", ".xls", ".zip", ".tar", ".gz",
                   ".pdf", ".pkl", ".h5", ".hdf5", ".parquet"}

    if ext in image_exts or ext in binary_exts:
        try:
            out = _ssh_exec(req.host, req.user,
                            f'stat --format="%s" {req.path} 2>/dev/null',
                            password=req.password, timeout=10)
            fsize = int(out.strip())
        except Exception:
            fsize = 0
        return FilePreviewResponse(
            rel_path=req.path, file_type=ext,
            content=f"[Binary file: {name} ({fsize:,} bytes)]",
            truncated=False, is_image=(ext in image_exts),
        )

    if ext == ".csv":
        out = _ssh_exec(req.host, req.user,
                        f'head -n {req.lines + 1} {req.path} 2>/dev/null',
                        password=req.password)
        if not out.strip():
            return FilePreviewResponse(rel_path=req.path, file_type=ext,
                                       content="(empty file)")

        reader = csv_mod.DictReader(io.StringIO(out))
        columns = reader.fieldnames or []
        rows = [dict(row) for i, row in enumerate(reader) if i < req.lines]

        try:
            wc_out = _ssh_exec(req.host, req.user,
                               f'wc -l < {req.path} 2>/dev/null',
                               password=req.password, timeout=10)
            total = int(wc_out.strip()) - 1
        except Exception:
            total = len(rows)

        return FilePreviewResponse(
            rel_path=req.path, file_type=ext,
            columns=list(columns), rows=rows,
            total_rows=total, truncated=(total > len(rows)),
        )

    # Text files
    out = _ssh_exec(req.host, req.user,
                    f'head -n {req.lines} {req.path} 2>/dev/null',
                    password=req.password)

    try:
        wc_out = _ssh_exec(req.host, req.user,
                           f'wc -l < {req.path} 2>/dev/null',
                           password=req.password, timeout=10)
        total_lines = int(wc_out.strip())
    except Exception:
        total_lines = 0

    return FilePreviewResponse(
        rel_path=req.path, file_type=ext,
        content=out, truncated=(total_lines > req.lines),
        total_rows=total_lines,
    )


@router.post("/hpc/disconnect")
def disconnect_hpc(req: HpcDisconnectRequest):
    """Close SSH connection and clear credentials from memory."""
    key = (req.host, req.user)
    with _ssh_lock:
        client = _ssh_pool.pop(key, None)
        if client is not None:
            try:
                client.close()
            except Exception:
                pass
    return {"disconnected": True}


@router.post("/hpc/disconnect-all")
def disconnect_all_hpc():
    """Close all SSH connections."""
    with _ssh_lock:
        for client in _ssh_pool.values():
            try:
                client.close()
            except Exception:
                pass
        _ssh_pool.clear()
    return {"disconnected": True}


@router.post("/hpc/cases-files")
def list_hpc_cases_files(req: HpcCasesRequest):
    """List cases_*.csv files from the remote ReEDS repo and parse case names."""
    if not re.match(r'^[a-zA-Z0-9/_.\-~]+$', req.reeds_path):
        raise HTTPException(status_code=400, detail="Invalid path characters")    # List all cases*.csv files
    cmd = f'ls -1 {req.reeds_path}/cases*.csv 2>/dev/null'
    out = _ssh_exec(req.host, req.user, cmd, password=req.password, timeout=15)

    results = []
    for fpath in out.strip().splitlines():
        fpath = fpath.strip()
        if not fpath:
            continue
        fname = fpath.rsplit("/", 1)[-1]
        # Extract suffix: cases_small.csv -> "small", cases.csv -> "_default"
        stem = fname.replace(".csv", "")
        if stem == "cases":
            suffix = "_default"
        elif stem.startswith("cases_"):
            suffix = stem[6:]
        else:
            continue

        # Read first lines to parse case names
        head_cmd = f'head -n 200 {fpath} 2>/dev/null'
        try:
            csv_out = _ssh_exec(req.host, req.user, head_cmd,
                                password=req.password, timeout=15)
        except Exception:
            csv_out = ""

        cases = []
        if csv_out.strip():
            reader = csv_mod.DictReader(io.StringIO(csv_out))
            if reader.fieldnames:
                # In ReEDS cases files, column headers ARE the case names.
                # First column is empty (switch names), rest are cases.
                cases = [
                    col for col in reader.fieldnames[1:]
                    if col.strip()
                ]

        results.append({
            "filename": fname,
            "suffix": suffix,
            "cases": cases,
        })

    return results


# ── HPC: connection check, conda envs, env health, slurm queue ────────────────

class HpcConnectRequest(BaseModel):
    host: str = Field(..., description="HPC login node hostname")
    user: str = Field(..., description="SSH username")
    password: str = Field(default="", description="SSH password (never logged)")


class HpcEnvCheckRequest(HpcConnectRequest):
    reeds_path: str = Field(..., description="Absolute path to ReEDS repo on HPC")
    conda_env: str = Field(default="reeds2", description="Conda env name to check")


@router.post("/hpc/connect")
def hpc_connect(req: HpcConnectRequest):
    """Verify SSH login. Returns home dir and a few suggested ReEDS-repo path candidates."""
    out = _ssh_exec(req.host, req.user,
                    "echo HOME=$HOME; echo HOSTNAME=$(hostname);"
                    " for d in $HOME $HOME/* /projects/$USER /scratch/$USER; do"
                    "   if [ -f \"$d/cases.csv\" ] && [ -f \"$d/runbatch.py\" ]; then echo CAND=$d; fi;"
                    "   if [ -d \"$d\" ]; then for sub in $d/ReEDS $d/reeds $d/ReEDS-2.0; do"
                    "     if [ -f \"$sub/cases.csv\" ] && [ -f \"$sub/runbatch.py\" ]; then echo CAND=$sub; fi;"
                    "   done; fi;"
                    " done",
                    password=req.password, timeout=20)
    home = ""
    hostname = ""
    candidates: list[str] = []
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("HOME="):
            home = line[5:]
        elif line.startswith("HOSTNAME="):
            hostname = line[9:]
        elif line.startswith("CAND="):
            cand = line[5:]
            if cand and cand not in candidates:
                candidates.append(cand)
    return {"ok": True, "home": home, "hostname": hostname, "suggested_paths": candidates[:6]}


@router.post("/hpc/conda-envs")
def hpc_conda_envs(req: HpcConnectRequest):
    """Return the list of conda envs available on the HPC for this user."""
    out = _ssh_exec(req.host, req.user,
                    "module load anaconda3 2>/dev/null; "
                    "module load conda 2>/dev/null; "
                    "(conda env list 2>/dev/null || ~/.conda/envs/.. 2>/dev/null) | "
                    "grep -v '^#' | awk 'NF>=1 {print $1}'",
                    password=req.password, timeout=20)
    envs: list[dict] = []
    for line in out.splitlines():
        name = line.strip()
        if not name or name.startswith("#"):
            continue
        envs.append({"name": name, "prefix": ""})
    # Make sure default appears even if module load failed
    if not envs:
        envs = [{"name": "reeds2", "prefix": ""}]
    return envs


@router.post("/hpc/env-check")
def hpc_env_check(req: HpcEnvCheckRequest):
    """Run lightweight environment health checks on the HPC."""
    if not re.match(r'^[a-zA-Z0-9/_.\-~]+$', req.reeds_path):
        raise HTTPException(status_code=400, detail="Invalid reeds_path characters")
    if not re.match(r'^[a-zA-Z0-9_.\-]+$', req.conda_env):
        raise HTTPException(status_code=400, detail="Invalid conda env name")

    # One combined script — minimizes SSH round-trips
    script = (
        "module load anaconda3 2>/dev/null; module load conda 2>/dev/null; "
        f"source activate {req.conda_env} 2>/dev/null || conda activate {req.conda_env} 2>/dev/null; "
        f"echo CONDA_OK=$([ \"$CONDA_DEFAULT_ENV\" = \"{req.conda_env}\" ] && echo 1 || echo 0); "
        f"echo CONDA_PREFIX=$CONDA_PREFIX; "
        f"echo PYTHON=$(which python 2>/dev/null); "
        "echo GAMS=$(which gams 2>/dev/null); "
        "echo JULIA=$(which julia 2>/dev/null); "
        f"echo LICENSE=$([ -f {req.reeds_path}/gamslice.txt ] && echo 1 || echo 0); "
        f"echo REPO=$([ -f {req.reeds_path}/cases.csv ] && [ -f {req.reeds_path}/runbatch.py ] && echo 1 || echo 0); "
        f"echo SLURM=$(which sbatch 2>/dev/null)"
    )
    out = _ssh_exec(req.host, req.user, script, password=req.password, timeout=25)
    info: dict[str, str] = {}
    for line in out.splitlines():
        if "=" in line:
            k, _, v = line.partition("=")
            info[k.strip()] = v.strip()

    checks = [
        {
            "name": "repo",
            "label": "ReEDS repo",
            "ok": info.get("REPO") == "1",
            "detail": req.reeds_path if info.get("REPO") == "1" else "cases.csv or runbatch.py missing",
            "fixable": False,
        },
        {
            "name": "conda_env",
            "label": f"Conda env ({req.conda_env})",
            "ok": info.get("CONDA_OK") == "1",
            "detail": info.get("CONDA_PREFIX") or "not found / activation failed",
            "fixable": False,
        },
        {
            "name": "python",
            "label": "Python",
            "ok": bool(info.get("PYTHON")),
            "detail": info.get("PYTHON") or "not found",
            "fixable": False,
        },
        {
            "name": "gams",
            "label": "GAMS",
            "ok": bool(info.get("GAMS")),
            "detail": info.get("GAMS") or "gams not on PATH (try: module load gams)",
            "fixable": False,
        },
        {
            "name": "gams_license",
            "label": "GAMS license (gamslice.txt)",
            "ok": info.get("LICENSE") == "1",
            "detail": "found in repo" if info.get("LICENSE") == "1" else "missing in repo root",
            "fixable": False,
        },
        {
            "name": "julia",
            "label": "Julia",
            "ok": bool(info.get("JULIA")),
            "detail": info.get("JULIA") or "not found (only needed for some workflows)",
            "fixable": False,
        },
        {
            "name": "slurm",
            "label": "Slurm (sbatch)",
            "ok": bool(info.get("SLURM")),
            "detail": info.get("SLURM") or "sbatch not found",
            "fixable": False,
        },
    ]
    return {"checks": checks}


@router.post("/hpc/squeue")
def hpc_squeue(req: HpcConnectRequest):
    """Return the current Slurm queue for this user."""
    out = _ssh_exec(req.host, req.user,
                    f"squeue -u {req.user} -h "
                    "-o '%i|%j|%T|%M|%l|%R' 2>/dev/null",
                    password=req.password, timeout=15)
    jobs = []
    for line in out.splitlines():
        parts = line.split("|")
        if len(parts) < 6:
            continue
        jobs.append({
            "job_id": parts[0].strip(),
            "name": parts[1].strip(),
            "state": parts[2].strip(),
            "elapsed": parts[3].strip(),
            "limit": parts[4].strip(),
            "reason": parts[5].strip(),
        })
    return {"jobs": jobs}
