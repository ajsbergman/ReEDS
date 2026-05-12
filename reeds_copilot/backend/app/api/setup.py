"""Setup wizard API – guided first-run environment configuration."""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import threading
from pathlib import Path

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..core.config import Settings, get_settings
from ..services import env_check

log = logging.getLogger(__name__)
router = APIRouter(prefix="/setup", tags=["setup"])

# ── Background task tracking ──────────────────────────────────────────────────
_task_status: dict[str, dict] = {}


# ── Models ────────────────────────────────────────────────────────────────────
class FixStepRequest(BaseModel):
    step: str
    conda_env: str = "reeds2"
    gams_license: str = ""


class SetupStep(BaseModel):
    id: str
    order: int
    title: str
    description: str
    status: str          # "pass", "fail", "running", "skip"
    detail: str
    auto_fixable: bool
    guide_url: str = ""
    guide_steps: list[str] = []


# ── Step checkers ─────────────────────────────────────────────────────────────

def _check_conda(repo_root: Path) -> SetupStep:
    """Step 1: Is Anaconda/Miniconda installed?"""
    conda_path = shutil.which("conda")
    if conda_path:
        try:
            r = subprocess.run(["conda", "--version"], capture_output=True, text=True, timeout=15)
            ver = r.stdout.strip() or r.stderr.strip()
        except Exception:
            ver = "unknown version"
        return SetupStep(
            id="conda", order=1, title="Anaconda / Miniconda",
            description="Conda is the package manager that handles all Python dependencies for ReEDS. Without it, none of the other steps will work.",
            status="pass", detail=f"✅ {ver} found at {conda_path}",
            auto_fixable=False,
        )
    return SetupStep(
        id="conda", order=1, title="Anaconda / Miniconda",
        description="Conda is the package manager that handles all Python dependencies for ReEDS. Without it, none of the other steps will work.",
        status="fail",
        detail="Conda is not installed or not on your system PATH. ReEDS cannot run without it.",
        auto_fixable=False,
        guide_url="https://docs.anaconda.com/anaconda/install/",
        guide_steps=[
            "Download Miniconda (lightweight, recommended) from https://docs.conda.io/en/latest/miniconda.html — or Anaconda (full) from https://www.anaconda.com/download",
            "Run the installer. When prompted, CHECK the box 'Add to PATH environment variable' — this is critical!",
            "If you're on Windows: after installing, open a NEW Command Prompt or PowerShell window",
            "Verify it works: type `conda --version` in your terminal — you should see something like 'conda 24.x.x'",
            "Come back here and click Re-check All to continue",
        ],
    )


def _check_conda_env(repo_root: Path, env_name: str) -> SetupStep:
    """Step 2: Does the reeds2 conda env exist?"""
    task = _task_status.get("conda_env", {})
    if task.get("running"):
        return SetupStep(
            id="conda_env", order=2, title=f"Conda Environment ({env_name})",
            description="ReEDS needs a dedicated Python environment with ~40 packages (numpy, pandas, GAMS API, etc.). This environment is defined in environment.yml.",
            status="running",
            detail="⏳ Creating environment — installing Python 3.11 and all packages. This typically takes 5–10 minutes. You can leave this page and come back.",
            auto_fixable=True,
        )
    result = env_check.check_conda_env(env_name)
    if result["ok"]:
        return SetupStep(
            id="conda_env", order=2, title=f"Conda Environment ({env_name})",
            description="ReEDS needs a dedicated Python environment with ~40 packages (numpy, pandas, GAMS API, etc.). This environment is defined in environment.yml.",
            status="pass", detail=f"✅ {result['detail']}",
            auto_fixable=True,
        )
    return SetupStep(
        id="conda_env", order=2, title=f"Conda Environment ({env_name})",
        description="ReEDS needs a dedicated Python environment with ~40 packages (numpy, pandas, GAMS API, etc.). This environment is defined in environment.yml.",
        status="fail",
        detail=result["detail"],
        auto_fixable=True,
        guide_steps=[
            f"Easiest: Click 'Fix it automatically' below — this creates the '{env_name}' environment for you",
            f"Manual alternative: open a terminal and run: conda env create -n {env_name} -f environment.yml",
            "This installs Python 3.11 and ~40 packages. Expect 5–10 minutes on a typical connection",
            "After creation, click Re-check to verify",
        ],
    )


def _check_gams(env_name: str) -> SetupStep:
    """Step 3: Is GAMS installed?"""
    result = env_check.check_gams(env_name)
    if result["ok"]:
        return SetupStep(
            id="gams", order=3, title="GAMS",
            description="GAMS (General Algebraic Modeling System) solves the optimization problems at the heart of ReEDS. You need both the software and a valid license.",
            status="pass", detail=f"✅ {result['detail']}",
            auto_fixable=False,
        )
    return SetupStep(
        id="gams", order=3, title="GAMS",
        description="GAMS (General Algebraic Modeling System) solves the optimization problems at the heart of ReEDS. You need both the software and a valid license.",
        status="fail",
        detail=result["detail"],
        auto_fixable=False,
        guide_url="https://www.gams.com/download/",
        guide_steps=[
            "Go to https://www.gams.com/download/ and download the latest version (45+ recommended)",
            "Run the installer. Use the default install path (e.g. C:\\GAMS\\45 on Windows)",
            "⚠️ IMPORTANT: Check the 'Add GAMS directory to PATH' option during install",
            "If you missed it, add GAMS manually: open System Settings → Environment Variables → edit PATH → add your GAMS folder",
            "Verify: open a new terminal and type `gams` — you should see GAMS version info",
            "Click Re-check when done",
        ],
    )


def _check_gams_license(repo_root: Path) -> SetupStep:
    """Step 4: Is gamslice.txt present?"""
    result = env_check.check_gams_license(repo_root)
    if result["ok"]:
        return SetupStep(
            id="gams_license", order=4, title="GAMS License",
            description="GAMS requires a license file (gamslice.txt) in the ReEDS root folder. Without it, GAMS can only solve tiny problems.",
            status="pass", detail=f"✅ {result['detail']}",
            auto_fixable=True,
        )
    return SetupStep(
        id="gams_license", order=4, title="GAMS License",
        description="GAMS requires a license file (gamslice.txt) in the ReEDS root folder. Without it, GAMS can only solve tiny problems.",
        status="fail",
        detail=result["detail"],
        auto_fixable=True,
        guide_steps=[
            "You need a valid GAMS license to run ReEDS at full scale",
            "If you're at NREL: check the ReEDS Teams channel — there's a shared license file pinned there",
            "Otherwise: contact your team lead or GAMS (https://www.gams.com/) for a license",
            "Once you have the license text (multi-line block of numbers/text), paste it into the box below and click 'Save License'",
            "The file will be saved as gamslice.txt in your ReEDS root directory",
        ],
    )


def _check_julia(repo_root: Path) -> SetupStep:
    """Step 5: Is Julia installed?"""
    result = env_check.check_julia(repo_root)
    if result["ok"]:
        return SetupStep(
            id="julia", order=5, title="Julia",
            description="Julia powers the PRAS capacity credit calculations in ReEDS (Augur module). Version 1.12+ is required.",
            status="pass", detail=f"✅ {result['detail']}",
            auto_fixable=False,
        )
    return SetupStep(
        id="julia", order=5, title="Julia",
        description="Julia powers the PRAS capacity credit calculations in ReEDS (Augur module). Version 1.12+ is required.",
        status="fail",
        detail=result["detail"],
        auto_fixable=False,
        guide_url="https://julialang.org/downloads/",
        guide_steps=[
            "Easiest on Windows: open PowerShell and run `winget install julia -s msstore`",
            "Alternative: download the installer from https://julialang.org/downloads/ (pick version 1.12+)",
            "On macOS/Linux: run `curl -fsSL https://install.julialang.org | sh` in your terminal",
            "After installing, verify: open a NEW terminal and type `julia --version` — you should see 'julia version 1.12.x'",
            "If `julia` is not found, you may need to add it to PATH or restart your terminal",
            "Click Re-check when done",
        ],
    )


def _check_julia_packages(repo_root: Path) -> SetupStep:
    """Step 6: Are Julia packages instantiated (Manifest.toml)?"""
    task = _task_status.get("julia_pkgs", {})
    if task.get("running"):
        return SetupStep(
            id="julia_pkgs", order=6, title="Julia Packages (Manifest.toml)",
            description="ReEDS requires a Manifest.toml file listing exact Julia package versions. This is generated by running Pkg.instantiate() which downloads PRAS, CSV, DataFrames, and other dependencies.",
            status="running",
            detail="⏳ Running Pkg.instantiate() — downloading and precompiling Julia packages. This typically takes 5–10 minutes on first run.",
            auto_fixable=True,
        )
    result = env_check.check_manifest(repo_root)
    if result["ok"]:
        return SetupStep(
            id="julia_pkgs", order=6, title="Julia Packages (Manifest.toml)",
            description="ReEDS requires a Manifest.toml file listing exact Julia package versions. This is generated by running Pkg.instantiate() which downloads PRAS, CSV, DataFrames, and other dependencies.",
            status="pass", detail=f"✅ {result['detail']}",
            auto_fixable=True,
        )
    return SetupStep(
        id="julia_pkgs", order=6, title="Julia Packages (Manifest.toml)",
        description="ReEDS requires a Manifest.toml file listing exact Julia package versions. This is generated by running Pkg.instantiate() which downloads PRAS, CSV, DataFrames, and other dependencies.",
        status="fail",
        detail=result["detail"],
        auto_fixable=True,
        guide_steps=[
            "Easiest: Click 'Fix it automatically' — this runs Julia's package manager to generate Manifest.toml",
            "Manual alternative: open a terminal, cd to the ReEDS folder, then run: julia --project=. -e 'import Pkg; Pkg.instantiate()'",
            "This downloads ~20 Julia packages. Expect 5–10 minutes on a typical connection",
            "When done, you should see a Manifest.toml file in the ReEDS root directory",
        ],
    )


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/check-all")
def check_all(
    conda_env: str = "reeds2",
    settings: Settings = Depends(get_settings),
) -> list[SetupStep]:
    """Run all setup checks and return ordered results."""
    env_name = env_check._validate_env_name(conda_env)
    repo = settings.repo_root
    return [
        _check_conda(repo),
        _check_conda_env(repo, env_name),
        _check_gams(env_name),
        _check_gams_license(repo),
        _check_julia(repo),
        _check_julia_packages(repo),
    ]


@router.post("/fix")
def fix_step(
    body: FixStepRequest,
    settings: Settings = Depends(get_settings),
) -> dict:
    """Attempt to auto-fix a failing setup step."""
    repo = settings.repo_root
    env_name = env_check._validate_env_name(body.conda_env)

    if body.step == "conda_env":
        return _fix_conda_env(repo, env_name)
    elif body.step == "gams_license":
        return env_check.save_gamslice(repo, body.gams_license)
    elif body.step == "julia_pkgs":
        return _fix_julia_packages(repo)
    else:
        return {"ok": False, "detail": f"No auto-fix available for step '{body.step}'"}


def _fix_conda_env(repo_root: Path, env_name: str) -> dict:
    """Create the conda env in a background thread."""
    if _task_status.get("conda_env", {}).get("running"):
        return {"ok": False, "detail": "Conda env creation is already running. Please wait."}

    env_yml = repo_root / "environment.yml"
    if not env_yml.exists():
        return {"ok": False, "detail": "environment.yml not found in the ReEDS repo."}

    _task_status["conda_env"] = {"running": True}

    def _do():
        try:
            log.info("Creating conda env '%s' from environment.yml …", env_name)
            r = subprocess.run(
                ["conda", "env", "create", "-n", env_name, "-f", str(env_yml)],
                capture_output=True, text=True, timeout=900,
                cwd=str(repo_root),
            )
            if r.returncode == 0 or "already exists" in (r.stderr or ""):
                _task_status["conda_env"] = {"running": False, "ok": True}
                log.info("Conda env '%s' created successfully", env_name)
            else:
                _task_status["conda_env"] = {
                    "running": False, "ok": False,
                    "detail": (r.stderr or r.stdout or "unknown error")[-500:],
                }
        except subprocess.TimeoutExpired:
            _task_status["conda_env"] = {"running": False, "ok": False, "detail": "Timed out (15 min limit)"}
        except Exception as exc:
            _task_status["conda_env"] = {"running": False, "ok": False, "detail": str(exc)}

    threading.Thread(target=_do, daemon=True).start()
    return {"ok": False, "detail": "Creating conda environment in the background. This may take 5–10 minutes. Click Re-check to see progress."}


def _fix_julia_packages(repo_root: Path) -> dict:
    """Run Julia Pkg.instantiate() in a background thread."""
    if _task_status.get("julia_pkgs", {}).get("running"):
        return {"ok": False, "detail": "Julia package install is already running. Please wait."}

    julia_path = env_check._find_julia_binary(repo_root)
    if not julia_path:
        return {"ok": False, "detail": "Cannot fix: Julia not found. Install Julia first."}

    _task_status["julia_pkgs"] = {"running": True}

    def _do():
        try:
            log.info("Running Julia Pkg.instantiate() for %s …", repo_root)
            julia_code = (
                'ENV["JULIA_SSL_CA_ROOTS_PATH"] = ""; '
                'import Pkg; '
                'try; Pkg.Registry.update(); catch e; @warn "Registry update failed" e; end; '
                'try; Pkg.Registry.add("General"); catch e; @warn "Registry add failed" e; end; '
                'Pkg.instantiate(); '
                'Pkg.add("Random123"); '
                'println("Done")'
            )
            r = subprocess.run(
                [julia_path, f"--project={repo_root}", "-e", julia_code],
                capture_output=True, text=True, timeout=600,
                cwd=str(repo_root),
            )
            manifest = repo_root / "Manifest.toml"
            if manifest.exists():
                _task_status["julia_pkgs"] = {"running": False, "ok": True}
                log.info("Julia packages instantiated successfully")
            else:
                stderr_tail = (r.stderr or r.stdout or "unknown error")[-500:]
                _task_status["julia_pkgs"] = {"running": False, "ok": False, "detail": stderr_tail}
        except subprocess.TimeoutExpired:
            _task_status["julia_pkgs"] = {"running": False, "ok": False, "detail": "Timed out (10 min limit)"}
        except Exception as exc:
            _task_status["julia_pkgs"] = {"running": False, "ok": False, "detail": str(exc)}

    threading.Thread(target=_do, daemon=True).start()
    return {"ok": False, "detail": "Installing Julia packages in the background. This may take 5–10 minutes. Click Re-check to see progress."}
