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

import re
_SAFE_ENV_NAME = re.compile(r'^[a-zA-Z0-9_][a-zA-Z0-9_.\\-]{0,63}$')


def _validate_env_name(name: str) -> str:
    """Validate conda env name to prevent command injection."""
    if not _SAFE_ENV_NAME.match(name):
        raise ValueError(f"Invalid conda environment name: {name!r}")
    return name


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


def _find_julia_binary(repo_root: Path | None = None) -> str | None:
    """Find a Julia binary, preferring a juliaup-managed version that matches Project.toml."""
    required_ver: str | None = None
    if repo_root:
        project_toml = repo_root / "Project.toml"
        if project_toml.exists():
            import re
            m = re.search(r'julia\s*=\s*"([^"]+)"', project_toml.read_text(encoding="utf-8"))
            if m:
                required_ver = m.group(1).lstrip("=").strip()
    # Check juliaup-managed installs
    if required_ver:
        home = Path.home()
        juliaup_dir = home / ".julia" / "juliaup"
        if juliaup_dir.exists():
            for d in juliaup_dir.iterdir():
                if d.is_dir() and required_ver in d.name:
                    candidate = d / "bin" / ("julia.exe" if os.name == "nt" else "julia")
                    if candidate.exists():
                        return str(candidate)
    # Fallback to PATH
    return shutil.which("julia")


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
    julia_path = _find_julia_binary(repo_root)
    if not julia_path:
        return {"ok": False, "detail": "Julia not found on PATH. Install Julia and add to PATH."}
    # Check version
    try:
        r = _run([julia_path, "--version"])
        ver = r.stdout.strip()
    except Exception:
        ver = "unknown version"
    detail = f"{ver} at {julia_path}"
    compat = _check_julia_compat(repo_root)
    if compat:
        return {"ok": False, "detail": f"{detail} — {compat}"}
    return {"ok": True, "detail": detail}


def _check_julia_compat(repo_root: Path) -> str:
    """Check if installed Julia version matches Project.toml compat."""
    project_toml = repo_root / "Project.toml"
    if not project_toml.exists():
        return ""
    try:
        content = project_toml.read_text(encoding="utf-8")
        import re
        m = re.search(r'julia\s*=\s*"([^"]+)"', content)
        if not m:
            return ""
        required = m.group(1)
        julia_bin = _find_julia_binary(repo_root) or "julia"
        r = _run([julia_bin, "--version"])
        installed = r.stdout.strip().replace("julia version ", "")
        # Simple check: if required starts with "=" it's an exact match
        req_ver = required.lstrip("=").strip()
        if installed != req_ver:
            return f"⚠️ Project.toml requires Julia {required}, but you have {installed}. Install Julia {req_ver}."
    except Exception:
        pass
    return ""


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
    # If a fix just completed with error, show it
    if fs and not fs.get("running") and not fs.get("ok") and fs.get("detail"):
        return {
            "ok": False,
            "detail": fs["detail"],
            "fixable": True,
        }
    # Check Julia version compatibility with Project.toml
    compat_detail = _check_julia_compat(repo_root)
    detail = "Manifest.toml missing. Julia packages not instantiated."
    if compat_detail:
        detail += f" ({compat_detail})"
    return {
        "ok": False,
        "detail": detail,
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
    env_name = _validate_env_name(env_name)
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
    """Run Julia Pkg.instantiate() to create Manifest.toml."""
    julia_path = _find_julia_binary(repo_root)
    if not julia_path:
        return {"ok": False, "detail": "Cannot fix: Julia not found on PATH"}

    # If already running, return current status
    if _fix_status.get("manifest", {}).get("running"):
        return {"ok": False, "detail": "Julia instantiate is already running... please wait."}

    # Run in background thread so the HTTP request returns immediately
    _fix_status["manifest"] = {"running": True, "detail": "Julia instantiate started..."}

    def _run_julia():
        try:
            log.info("Starting julia instantiate for %s ...", repo_root)
            # Step 1: Pkg.instantiate() to generate Manifest.toml
            # We avoid running instantiate.jl directly because its
            # Pkg.Registry.update() can fail due to SSL/permission issues.
            # Instead, run the commands step-by-step with error handling.
            julia_code = (
                'ENV["JULIA_SSL_CA_ROOTS_PATH"] = ""; '
                'import Pkg; '
                'try; Pkg.Registry.update(); catch e; @warn "Registry update failed" e; end; '
                'try; Pkg.Registry.add("General"); catch e; @warn "Registry add failed" e; end; '
                'Pkg.instantiate(); '
                'println("Manifest.toml created successfully")'
            )
            r = subprocess.run(
                [julia_path, f"--project={repo_root}", "-e", julia_code],
                capture_output=True, text=True, timeout=600,
                cwd=str(repo_root),
            )
            manifest = repo_root / "Manifest.toml"
            if manifest.exists():
                _fix_status["manifest"] = {"running": False, "ok": True,
                                           "detail": "Julia packages instantiated successfully"}
                log.info("Julia instantiate succeeded")
            elif r.returncode == 0:
                # Command succeeded but maybe Manifest not created?
                _fix_status["manifest"] = {"running": False, "ok": False,
                                           "detail": f"Command finished but Manifest.toml still missing. stdout: {r.stdout[-300:]}"}
            else:
                stderr_tail = (r.stderr or r.stdout or "unknown error")[-500:]
                _fix_status["manifest"] = {
                    "running": False, "ok": False,
                    "detail": f"Failed (exit {r.returncode}): {stderr_tail}",
                }
                log.error("Julia instantiate failed: %s", stderr_tail)
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
