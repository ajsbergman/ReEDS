"""Environment health checks and one-click fixes for ReEDS."""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import threading
from pathlib import Path

log = logging.getLogger(__name__)

# Track background fix status
_fix_status: dict[str, dict] = {}


def _run(cmd: list[str], timeout: int = 30, **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, **kw)


def _find_conda_python(env_name: str) -> str | None:
    """Find the Python executable path for a conda env."""
    try:
        r = _run(["conda", "env", "list", "--json"])
        if r.returncode != 0:
            return None
        import json
        for p in json.loads(r.stdout).get("envs", []):
            if Path(p).name == env_name:
                py = Path(p) / ("python.exe" if os.name == "nt" else "bin/python")
                return str(py) if py.exists() else None
    except Exception:
        return None
    return None


# ── Individual checks ────────────────────────────────────────────────────────

def check_conda_env(env_name: str) -> dict:
    """Check if conda env exists and has Python."""
    py = _find_conda_python(env_name)
    if py:
        # Get python version
        try:
            r = _run([py, "--version"])
            ver = r.stdout.strip() or r.stderr.strip()
        except Exception:
            ver = "unknown"
        return {"ok": True, "detail": f"{ver} at {py}"}
    return {"ok": False, "detail": f"Conda env '{env_name}' not found or has no Python"}


def check_gams(env_name: str) -> dict:
    """Check if GAMS is accessible."""
    # Check in the conda env or on PATH
    py = _find_conda_python(env_name)
    if py:
        try:
            r = _run([py, "-c", "import shutil; print(shutil.which('gams') or '')"])
            path = r.stdout.strip()
            if path:
                return {"ok": True, "detail": f"Found at {path}"}
        except Exception:
            pass
    # Fallback: check system PATH
    gams_path = shutil.which("gams")
    if gams_path:
        return {"ok": True, "detail": f"Found at {gams_path}"}
    return {"ok": False, "detail": "GAMS not found on PATH. Install GAMS and add to PATH."}


def check_julia(repo_root: Path) -> dict:
    """Check if Julia is accessible."""
    julia_path = shutil.which("julia")
    if not julia_path:
        return {"ok": False, "detail": "Julia not found on PATH. Install Julia and add to PATH."}
    # Check version
    try:
        r = _run(["julia", "--version"])
        ver = r.stdout.strip()
    except Exception:
        ver = "unknown version"
    return {"ok": True, "detail": f"{ver} at {julia_path}"}


def check_manifest(repo_root: Path) -> dict:
    """Check if Manifest.toml exists (Julia/PRAS packages instantiated)."""
    manifest = repo_root / "Manifest.toml"
    if manifest.exists():
        return {"ok": True, "detail": "Manifest.toml found"}
    # If a fix is running in background, show that status
    fs = _fix_status.get("manifest", {})
    if fs.get("running"):
        return {
            "ok": False,
            "detail": "⏳ Julia instantiate running in background... re-check shortly.",
        }
    return {
        "ok": False,
        "detail": "Manifest.toml missing. Julia packages not instantiated.",
        "fixable": True,
    }


def check_remote_files(repo_root: Path) -> dict:
    """Check if remote input files have been downloaded."""
    csv_path = repo_root / "inputs" / "remote_files.csv"
    if not csv_path.exists():
        return {"ok": True, "detail": "No remote_files.csv found (skipping check)"}
    # Just check if a couple of expected directories exist
    plantchar = repo_root / "inputs" / "plant_characteristics"
    if plantchar.exists() and any(plantchar.iterdir()):
        return {"ok": True, "detail": "Input files appear to be present"}
    return {"ok": False, "detail": "Some remote input files may be missing"}


def check_gams_license(repo_root: Path) -> dict:
    """Check if gamslice.txt exists in the repo root."""
    p = repo_root / "gamslice.txt"
    if p.exists():
        # Read first line to show a preview (mask most of it)
        try:
            lines = p.read_text(encoding="utf-8").strip().splitlines()
            n_lines = len(lines)
            preview = f"{n_lines} line(s)"
            if n_lines > 0:
                first = lines[0]
                preview += f", starts with: {first[:20]}{'...' if len(first) > 20 else ''}"
        except Exception:
            preview = "file exists"
        return {"ok": True, "detail": f"gamslice.txt found ({preview})"}
    return {
        "ok": False,
        "detail": "gamslice.txt not found. A GAMS license is needed for HPC runs.",
        "fixable": True,
        "fix_type": "gamslice",
    }


def save_gamslice(repo_root: Path, content: str) -> dict:
    """Save user-provided GAMS license content to gamslice.txt."""
    content = content.strip()
    if not content:
        return {"ok": False, "detail": "License content is empty"}
    p = repo_root / "gamslice.txt"
    try:
        p.write_text(content + "\n", encoding="utf-8")
        return {"ok": True, "detail": f"gamslice.txt saved ({len(content.splitlines())} lines)"}
    except Exception as exc:
        return {"ok": False, "detail": f"Failed to write gamslice.txt: {exc}"}


# ── Aggregate check ──────────────────────────────────────────────────────────

def run_all_checks(repo_root: Path, env_name: str = "reeds2") -> list[dict]:
    """Run all environment checks and return results."""
    checks = [
        {"name": "conda_env", "label": f"Conda Environment ({env_name})",
         **check_conda_env(env_name)},
        {"name": "gams", "label": "GAMS",
         **check_gams(env_name)},
        {"name": "gams_license", "label": "GAMS License (gamslice.txt)",
         **check_gams_license(repo_root)},
        {"name": "julia", "label": "Julia",
         **check_julia(repo_root)},
        {"name": "manifest", "label": "Manifest.toml (PRAS/Julia packages)",
         **check_manifest(repo_root)},
        {"name": "remote_files", "label": "Remote Input Files",
         **check_remote_files(repo_root)},
    ]
    return checks


# ── Fix actions ──────────────────────────────────────────────────────────────

def fix_manifest(repo_root: Path) -> dict:
    """Run `julia --project=. instantiate.jl` to create Manifest.toml."""
    julia_path = shutil.which("julia")
    if not julia_path:
        return {"ok": False, "detail": "Cannot fix: Julia not found on PATH"}

    inst_script = repo_root / "instantiate.jl"
    if not inst_script.exists():
        return {"ok": False, "detail": "Cannot fix: instantiate.jl not found in repo"}

    # If already running, return current status
    if _fix_status.get("manifest", {}).get("running"):
        return {"ok": False, "detail": "Julia instantiate is already running... please wait."}

    # Run in background thread so the HTTP request returns immediately
    _fix_status["manifest"] = {"running": True, "detail": "Julia instantiate started..."}

    def _run_julia():
        try:
            log.info("Starting julia instantiate...")
            r = subprocess.run(
                [julia_path, f"--project={repo_root}", str(inst_script)],
                capture_output=True, text=True, timeout=600,
                cwd=str(repo_root),
            )
            if r.returncode == 0:
                _fix_status["manifest"] = {"running": False, "ok": True,
                                           "detail": "Julia packages instantiated successfully"}
                log.info("Julia instantiate succeeded")
            else:
                _fix_status["manifest"] = {
                    "running": False, "ok": False,
                    "detail": f"Failed (exit {r.returncode}): {r.stderr[-500:]}",
                }
                log.error("Julia instantiate failed: %s", r.stderr[-300:])
        except subprocess.TimeoutExpired:
            _fix_status["manifest"] = {"running": False, "ok": False,
                                       "detail": "Julia instantiate timed out (10 min limit)"}
        except Exception as exc:
            _fix_status["manifest"] = {"running": False, "ok": False,
                                       "detail": f"Error: {exc}"}

    threading.Thread(target=_run_julia, daemon=True).start()
    return {"ok": False, "detail": "Julia instantiate started in background. Re-check in a few minutes."}


def fix_conda_env(env_name: str, repo_root: Path) -> dict:
    """Create conda env from environment.yml if it doesn't exist."""
    env_yml = repo_root / "environment.yml"
    if not env_yml.exists():
        return {"ok": False, "detail": "environment.yml not found in repo root"}

    try:
        r = subprocess.run(
            ["conda", "env", "create", "-n", env_name, "-f", str(env_yml)],
            capture_output=True, text=True, timeout=600,
            cwd=str(repo_root),
        )
        if r.returncode == 0:
            return {"ok": True, "detail": f"Conda env '{env_name}' created successfully"}
        # Maybe it already exists — try update
        if "already exists" in r.stderr:
            return {"ok": True, "detail": f"Conda env '{env_name}' already exists"}
        return {
            "ok": False,
            "detail": f"Failed (exit {r.returncode}): {r.stderr[-500:]}",
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "detail": "Conda env creation timed out (10 min limit)"}
    except Exception as exc:
        return {"ok": False, "detail": f"Error: {exc}"}
