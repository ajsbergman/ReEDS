"""Setup wizard API – guided first-run environment configuration."""
from __future__ import annotations

import logging
import os
import platform
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

_IS_WINDOWS = platform.system() == "Windows"

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
            auto_fixable=_IS_WINDOWS,
        )
    task = _task_status.get("conda", {})
    if task.get("running"):
        return SetupStep(
            id="conda", order=1, title="Anaconda / Miniconda",
            description="Conda is the package manager that handles all Python dependencies for ReEDS. Without it, none of the other steps will work.",
            status="running",
            detail="⏳ Downloading and installing Miniconda… This takes 2–5 minutes. Please wait.",
            auto_fixable=_IS_WINDOWS,
        )
    return SetupStep(
        id="conda", order=1, title="Anaconda / Miniconda",
        description="Conda is the package manager that handles all Python dependencies for ReEDS. Without it, none of the other steps will work.",
        status="fail",
        detail="Conda is not installed or not on your system PATH. ReEDS cannot run without it.",
        auto_fixable=_IS_WINDOWS,
        guide_url="https://docs.conda.io/en/latest/miniconda.html",
        guide_steps=[
            "🖱️ Easiest: Click 'Fix it automatically' — this downloads and installs Miniconda for you (Windows only)" if _IS_WINDOWS else "Download Miniconda from https://docs.conda.io/en/latest/miniconda.html",
            "Manual alternative: download Miniconda from https://docs.conda.io/en/latest/miniconda.html",
            "Run the installer — when prompted, CHECK the box 'Add Miniconda to my PATH environment variable'",
            "⚠️ After installing, you MUST close and re-open your terminal (or restart ReEDS-Copilot) for conda to be detected",
            "Verify it works: type  conda --version  in a new terminal — you should see 'conda 24.x.x'",
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
            "If you're at NLR: check the ReEDS Teams channel — there's a shared license file pinned there",
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
            auto_fixable=_IS_WINDOWS,
        )
    task = _task_status.get("julia", {})
    if task.get("running"):
        return SetupStep(
            id="julia", order=5, title="Julia",
            description="Julia powers the PRAS capacity credit calculations in ReEDS (Augur module). Version 1.12+ is required.",
            status="running",
            detail="⏳ Installing Julia via winget… This takes 2–5 minutes.",
            auto_fixable=_IS_WINDOWS,
        )
    return SetupStep(
        id="julia", order=5, title="Julia",
        description="Julia powers the PRAS capacity credit calculations in ReEDS (Augur module). Version 1.12+ is required.",
        status="fail",
        detail=result["detail"],
        auto_fixable=_IS_WINDOWS,
        guide_url="https://julialang.org/downloads/",
        guide_steps=[
            "🖱️ Easiest: Click 'Fix it automatically' — this installs Julia using winget (Windows only)" if _IS_WINDOWS else "Download Julia from https://julialang.org/downloads/",
            "Manual on Windows: open PowerShell and run:  winget install julia -s msstore",
            "Manual download: go to https://julialang.org/downloads/ and pick version 1.12+",
            "On macOS/Linux: run  curl -fsSL https://install.julialang.org | sh  in your terminal",
            "⚠️ After installing, you MUST open a NEW terminal for Julia to be on your PATH",
            "Verify: type  julia --version  — you should see 'julia version 1.12.x'",
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

    if body.step == "conda":
        return _fix_conda()
    elif body.step == "conda_env":
        return _fix_conda_env(repo, env_name)
    elif body.step == "gams_license":
        return env_check.save_gamslice(repo, body.gams_license)
    elif body.step == "julia":
        return _fix_julia()
    elif body.step == "julia_pkgs":
        return _fix_julia_packages(repo)
    else:
        return {"ok": False, "detail": f"No auto-fix available for step '{body.step}'"}


def _fix_conda() -> dict:
    """Download and silently install Miniconda (Windows only)."""
    if not _IS_WINDOWS:
        return {"ok": False, "detail": "Auto-install is only supported on Windows. Please install Miniconda manually."}
    if _task_status.get("conda", {}).get("running"):
        return {"ok": False, "detail": "Miniconda installation is already running. Please wait."}
    if shutil.which("conda"):
        return {"ok": True, "detail": "Conda is already installed."}

    _task_status["conda"] = {"running": True}

    def _do():
        import tempfile
        import urllib.request
        installer_url = "https://repo.anaconda.com/miniconda/Miniconda3-latest-Windows-x86_64.exe"
        installer_path = Path(tempfile.gettempdir()) / "Miniconda3-latest-Windows-x86_64.exe"
        try:
            log.info("Downloading Miniconda from %s …", installer_url)
            urllib.request.urlretrieve(installer_url, str(installer_path))
            log.info("Running Miniconda silent installer …")
            r = subprocess.run(
                [
                    str(installer_path),
                    "/S",               # Silent
                    "/AddToPath=1",     # Add to PATH
                    "/RegisterPython=1",
                ],
                capture_output=True, text=True, timeout=600,
            )
            if r.returncode == 0:
                _task_status["conda"] = {"running": False, "ok": True}
                log.info("Miniconda installed successfully")
            else:
                _task_status["conda"] = {
                    "running": False, "ok": False,
                    "detail": f"Installer exited with code {r.returncode}. {(r.stderr or r.stdout or '')[-300:]}",
                }
        except Exception as exc:
            _task_status["conda"] = {"running": False, "ok": False, "detail": str(exc)[:500]}
        finally:
            try:
                installer_path.unlink(missing_ok=True)
            except Exception:
                pass

    threading.Thread(target=_do, daemon=True).start()
    return {"ok": False, "detail": "Downloading and installing Miniconda… This takes 2–5 minutes. You'll need to restart ReEDS-Copilot after installation for conda to be detected."}


def _fix_julia() -> dict:
    """Install Julia via winget (Windows only)."""
    if not _IS_WINDOWS:
        return {"ok": False, "detail": "Auto-install is only supported on Windows. Please install Julia manually."}
    if _task_status.get("julia", {}).get("running"):
        return {"ok": False, "detail": "Julia installation is already running. Please wait."}

    _task_status["julia"] = {"running": True}

    def _do():
        try:
            log.info("Installing Julia via winget …")
            r = subprocess.run(
                [
                    "winget", "install",
                    "--id", "Julialang.Julia",
                    "--source", "winget",
                    "--accept-package-agreements",
                    "--accept-source-agreements",
                ],
                capture_output=True, text=True, timeout=600,
            )
            output = (r.stdout or "") + (r.stderr or "")
            if r.returncode == 0 or "successfully installed" in output.lower():
                _task_status["julia"] = {"running": False, "ok": True}
                log.info("Julia installed successfully via winget")
            else:
                _task_status["julia"] = {
                    "running": False, "ok": False,
                    "detail": output[-500:] if output else f"winget exited with code {r.returncode}",
                }
        except FileNotFoundError:
            _task_status["julia"] = {
                "running": False, "ok": False,
                "detail": "winget not found. Please install Julia manually from https://julialang.org/downloads/",
            }
        except Exception as exc:
            _task_status["julia"] = {"running": False, "ok": False, "detail": str(exc)[:500]}

    threading.Thread(target=_do, daemon=True).start()
    return {"ok": False, "detail": "Installing Julia via winget… This takes 2–5 minutes. You'll need to restart ReEDS-Copilot after installation for Julia to be detected on PATH."}


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
