"""File browsing and preview endpoints."""
from __future__ import annotations

import csv as csv_mod
import hashlib
import io
import logging
import os
import re
import secrets
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import paramiko
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, Field

from ..core.config import Settings, get_settings
from ..models.schemas import FileListResponse, FileEntry, FilePreviewResponse
from ..services.file_inspector import list_directory, preview_file, safe_resolve

router = APIRouter(prefix="/files", tags=["files"])


# Allowed characters in remote HPC paths. Real-world filenames in ReEDS
# outputs include commas (e.g. multi-case PPTX names like
# "results-main_Ref,main_HighDemand.pptx"), spaces, parentheses, plus,
# brackets, colons, equals signs, etc. We allow a permissive character set
# but explicitly forbid path-traversal sequences and shell metacharacters.
_HPC_PATH_RE = re.compile(r'^[a-zA-Z0-9/_\.\-~ ,()+\[\]:=@%]+$')


def _is_safe_hpc_path(path: str) -> bool:
    """Return True when `path` is a syntactically safe remote path.

    Rejects empty input, NUL bytes, parent-dir traversal, and any character
    outside the explicit allow-list.
    """
    if not path or "\x00" in path or ".." in path.split("/"):
        return False
    return bool(_HPC_PATH_RE.match(path))


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


# ── In-browser PowerPoint preview (PPTX → PDF via LibreOffice) ─────────────


def _custom_soffice_config() -> Path:
    """Path to a small config file remembering a user-chosen install dir.

    Stored under the user's home dir so it survives backend restarts and
    is per-user (matches winget's per-user state).
    """
    return Path.home() / ".reeds_copilot" / "soffice_install_dir.txt"


def _read_custom_soffice_dir() -> str | None:
    """Return the user-chosen install dir, or None if not set."""
    cfg = _custom_soffice_config()
    if cfg.is_file():
        try:
            text = cfg.read_text(encoding="utf-8").strip()
            return text or None
        except Exception:
            return None
    return None


def _write_custom_soffice_dir(path: str) -> None:
    """Persist the user-chosen install dir."""
    cfg = _custom_soffice_config()
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text(path, encoding="utf-8")


def _find_soffice() -> str | None:
    """Locate the LibreOffice / soffice executable, if installed."""
    # 1. User-specified install location (from the "Custom location" field).
    custom = _read_custom_soffice_dir()
    if custom:
        for sub in (
            Path(custom) / "program" / "soffice.exe",
            Path(custom) / "soffice.exe",
            Path(custom) / "program" / "soffice",
            Path(custom) / "soffice",
        ):
            if sub.exists():
                return str(sub)
    # 2. PATH lookup.
    for name in ("soffice", "libreoffice"):
        p = shutil.which(name)
        if p:
            return p
    # 3. Standard install locations.
    if sys.platform.startswith("win"):
        for p in (
            r"C:\Program Files\LibreOffice\program\soffice.exe",
            r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
        ):
            if Path(p).exists():
                return p
    return None


# ── LibreOffice auto-install (one-click from the preview iframe) ──────────
#
# When the user opens a .pptx and LibreOffice isn't installed, the iframe
# page shows an "Install LibreOffice" button. The button POSTs to
# /files/install-soffice which spawns the platform-native package manager
# (winget on Windows, brew on macOS, apt on Linux) in a background thread
# and streams progress back via /files/install-soffice-status. This avoids
# making the user copy-paste a command.
_install_state: dict = {
    "status": "idle",   # idle | running | success | error | unsupported
    "log": "",
    "started_at": 0.0,
    "finished_at": 0.0,
    "exit_code": None,
}
_install_lock = threading.Lock()


def _install_soffice_command(location: str | None = None) -> list[str] | None:
    """Return the OS-native install command, or None if unsupported.

    When ``location`` is provided (Windows only), winget installs LibreOffice
    into that directory instead of the default ``C:\\Program Files\\LibreOffice``.
    """
    if sys.platform.startswith("win"):
        if shutil.which("winget"):
            # Note: --silent is intentionally omitted. The LibreOffice MSI
            # frequently fails (exit 1603) when /qn-driven, so we let winget
            # use its default UI which the elevated launcher in
            # _run_install_job will surface to the user.
            cmd = [
                "winget", "install", "--id", "TheDocumentFoundation.LibreOffice",
                "-e", "--accept-package-agreements", "--accept-source-agreements",
            ]
            if location:
                cmd.extend(["--location", location])
            return cmd
        return None
    if sys.platform == "darwin":
        if shutil.which("brew"):
            return ["brew", "install", "--cask", "libreoffice"]
        return None
    if sys.platform.startswith("linux"):
        # apt is the most common; we also check for dnf as a fallback.
        if shutil.which("apt-get"):
            return ["sudo", "-n", "apt-get", "install", "-y", "libreoffice"]
        if shutil.which("dnf"):
            return ["sudo", "-n", "dnf", "install", "-y", "libreoffice"]
        return None
    return None


def _run_install_job(cmd: list[str]) -> None:
    """Background worker that streams `cmd` output into `_install_state`.

    On Windows the actual install needs admin elevation (LibreOffice MSI
    fails with exit 1603 otherwise). We launch a separate elevated PowerShell
    via Start-Process -Verb RunAs, which surfaces a UAC prompt to the user.
    Because the elevated process is detached we can't capture its stdout, so
    we poll for the resulting soffice.exe instead.
    """
    try:
        if sys.platform.startswith("win") and cmd and cmd[0] == "winget":
            # Build the elevated launcher command.
            inner = " ".join(cmd) + ' ; exit $LASTEXITCODE'
            launcher = [
                "powershell", "-NoProfile", "-Command",
                "Start-Process", "powershell", "-Verb", "RunAs",
                "-Wait", "-ArgumentList",
                f"'-NoProfile','-Command','{inner}'",
            ]
            with _install_lock:
                _install_state["log"] += (
                    "\n[note] Launching elevated installer. Please approve\n"
                    "the Windows UAC prompt that appears on your desktop.\n"
                    "The install runs in a separate window and may take\n"
                    "5-10 minutes. This page will refresh automatically\n"
                    "once LibreOffice is detected.\n\n"
                )
            proc = subprocess.Popen(
                launcher,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            # Poll for soffice.exe (max 15 min) since we can't read the
            # elevated process's stdout.
            deadline = time.time() + 900
            while time.time() < deadline:
                if _find_soffice():
                    break
                if proc.poll() is not None:
                    # Launcher process exited; give the installer a few more
                    # seconds in case soffice.exe is still being copied.
                    time.sleep(5)
                    if _find_soffice():
                        break
                    break
                time.sleep(3)
            with _install_lock:
                _install_state["finished_at"] = time.time()
                if _find_soffice():
                    _install_state["status"] = "success"
                    _install_state["exit_code"] = 0
                    _install_state["log"] += "\n[ok] LibreOffice detected.\n"
                else:
                    _install_state["status"] = "error"
                    _install_state["exit_code"] = proc.returncode or 1
                    _install_state["log"] += (
                        "\n[error] Install did not complete (UAC denied or\n"
                        "MSI failed). See manual instructions below.\n"
                    )
            return

        # Non-Windows: stream the package-manager output directly.
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        assert proc.stdout is not None
        for line in proc.stdout:
            with _install_lock:
                # Cap log size so an interactive installer can't OOM us.
                if len(_install_state["log"]) < 100_000:
                    _install_state["log"] += line
        proc.wait(timeout=900)
        with _install_lock:
            _install_state["exit_code"] = proc.returncode
            _install_state["finished_at"] = time.time()
            if proc.returncode == 0 and _find_soffice():
                _install_state["status"] = "success"
            else:
                _install_state["status"] = "error"
    except Exception as exc:
        with _install_lock:
            _install_state["status"] = "error"
            _install_state["log"] += f"\n[exception] {exc}\n"
            _install_state["finished_at"] = time.time()


class InstallSofficeRequest(BaseModel):
    location: str = Field(
        default="",
        description=(
            "Optional custom install directory (Windows only). When empty, "
            "winget installs to the default 'C:\\Program Files\\LibreOffice'."
        ),
    )


@router.get("/soffice-status")
def soffice_status():
    """Return whether LibreOffice is installed and how it could be installed."""
    path = _find_soffice()
    cmd = _install_soffice_command()
    default_dir = (
        r"C:\Program Files\LibreOffice"
        if sys.platform.startswith("win") else
        ("/Applications" if sys.platform == "darwin" else "/usr")
    )
    return {
        "installed": bool(path),
        "path": path,
        "platform": sys.platform,
        "auto_install_available": cmd is not None,
        "install_command": " ".join(cmd) if cmd else None,
        "default_install_dir": default_dir,
        "custom_install_dir": _read_custom_soffice_dir(),
        "supports_custom_location": sys.platform.startswith("win"),
    }


@router.post("/install-soffice")
def install_soffice(req: InstallSofficeRequest | None = None):
    """Kick off a background LibreOffice install via the OS package manager.

    Optional request body: ``{"location": "D:\\Apps\\LibreOffice"}`` to
    install into a custom directory (Windows only).
    """
    if _find_soffice():
        return {"status": "already_installed"}
    location = (req.location.strip() if req and req.location else "") or None
    if location and not sys.platform.startswith("win"):
        return {
            "status": "unsupported",
            "detail": "Custom install location is only supported on Windows.",
        }
    with _install_lock:
        if _install_state["status"] == "running":
            return {"status": "already_running"}
        cmd = _install_soffice_command(location=location)
        if cmd is None:
            _install_state["status"] = "unsupported"
            return {
                "status": "unsupported",
                "detail": (
                    "No supported package manager found "
                    "(winget on Windows, brew on macOS, apt/dnf on Linux). "
                    "Please install LibreOffice manually from libreoffice.org."
                ),
            }
        _install_state.update({
            "status": "running",
            "log": f"$ {' '.join(cmd)}\n",
            "started_at": time.time(),
            "finished_at": 0.0,
            "exit_code": None,
        })
    # Persist the user's chosen location so _find_soffice() can locate it
    # after install (winget doesn't add custom locations to PATH).
    if location:
        try:
            _write_custom_soffice_dir(location)
        except Exception as exc:
            log.warning("Failed to persist custom soffice dir: %s", exc)
    threading.Thread(target=_run_install_job, args=(cmd,), daemon=True).start()
    return {"status": "started", "command": " ".join(cmd)}


# ── Portable install (no admin / no UAC required) ─────────────────────────
#
# `msiexec /a <msi> /qn TARGETDIR=<dir>` is an "administrative install" —
# misnamed; it actually just extracts the MSI's payload to a folder without
# elevating or registering anything system-wide. The extracted soffice.exe
# runs standalone, which gives us a fully portable LibreOffice in any
# user-writable directory. We download the official MSI from The Document
# Foundation, extract it, then point the custom-soffice-dir config at it.

# Pinned LibreOffice version known to work for headless pptx → pdf.
# Bump as new stable releases come out.
_PORTABLE_LO_VERSION = "26.2.3"
_PORTABLE_LO_URL = (
    f"https://download.documentfoundation.org/libreoffice/stable/"
    f"{_PORTABLE_LO_VERSION}/win/x86_64/"
    f"LibreOffice_{_PORTABLE_LO_VERSION}_Win_x86-64.msi"
)


def _default_portable_dir() -> Path:
    """Default location for the no-admin extraction."""
    base = Path(os.environ.get("LOCALAPPDATA", str(Path.home())))
    return base / "reeds_copilot" / "LibreOfficePortable"


def _try_extract_msi_with_7zip(msi_path: Path, target_dir: Path) -> tuple[bool, str]:
    """Fallback extractor: 7-Zip can read MSI files like archives, no admin
    needed, no MSI custom-action restrictions. Returns (ok, log_text).
    """
    candidates = [
        Path(r"C:\Program Files\7-Zip\7z.exe"),
        Path(r"C:\Program Files (x86)\7-Zip\7z.exe"),
    ]
    sevenzip = next((p for p in candidates if p.exists()), None)
    if not sevenzip:
        # Try PATH as a last resort.
        from shutil import which
        found = which("7z")
        if found:
            sevenzip = Path(found)
    if not sevenzip:
        return False, "  7-Zip not found (skip 7z fallback)\n"
    try:
        proc = subprocess.run(
            [str(sevenzip), "x", "-y", f"-o{target_dir}", str(msi_path)],
            capture_output=True, text=True, timeout=600,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        out = (proc.stdout or "") + (proc.stderr or "")
        return proc.returncode == 0, f"  7z exit {proc.returncode}\n{out[-2000:]}\n"
    except Exception as exc:
        return False, f"  7z exception: {exc}\n"


def _run_portable_install_job(target_dir: Path) -> None:
    """Background worker: download MSI, extract it via msiexec /a (no admin)."""
    import urllib.request
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        # Keep the MSI OUTSIDE target_dir — msiexec /a refuses to overwrite
        # the source MSI when TARGETDIR contains it (one cause of 1603).
        download_dir = target_dir.parent / "_msi_download"
        download_dir.mkdir(parents=True, exist_ok=True)
        msi_path = download_dir / f"LibreOffice_{_PORTABLE_LO_VERSION}.msi"
        log_path = download_dir / "msiexec.log"

        with _install_lock:
            _install_state["log"] += (
                f"\n[1/2] Downloading LibreOffice {_PORTABLE_LO_VERSION} "
                f"(~355 MB)\n      from {_PORTABLE_LO_URL}\n      to {msi_path}\n"
            )

        # Skip download if we already have a complete-looking copy (helps
        # retries after a transient extract failure).
        need_download = (
            not msi_path.exists() or msi_path.stat().st_size < 200 * 1024 * 1024
        )
        if need_download:
            last_pct = -1
            def _hook(blocks: int, blocksize: int, total: int) -> None:
                nonlocal last_pct
                if total <= 0:
                    return
                pct = min(100, int(blocks * blocksize * 100 / total))
                if pct != last_pct and pct % 5 == 0:
                    last_pct = pct
                    with _install_lock:
                        _install_state["log"] += f"  download: {pct}%\n"
            urllib.request.urlretrieve(_PORTABLE_LO_URL, str(msi_path), _hook)
        else:
            with _install_lock:
                _install_state["log"] += "  (using cached MSI)\n"

        with _install_lock:
            _install_state["log"] += (
                f"\n[2/2] Extracting MSI to {target_dir} (no admin needed)\n"
                f"  msiexec verbose log: {log_path}\n"
            )

        # /a = administrative install (extract-only, no UAC, no registration)
        # /qn = quiet, no UI; /L*v writes a verbose log so we can diagnose
        # any 1603-style failure.
        proc = subprocess.run(
            ["msiexec", "/a", str(msi_path), "/qn",
             f"TARGETDIR={target_dir}", "/L*v", str(log_path)],
            capture_output=True, text=True, timeout=900,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        with _install_lock:
            _install_state["exit_code"] = proc.returncode
            if proc.stdout:
                _install_state["log"] += proc.stdout
            if proc.stderr:
                _install_state["log"] += proc.stderr
            _install_state["log"] += f"  msiexec exit code: {proc.returncode}\n"

        # Look for soffice.exe; if not found, try 7-Zip fallback.
        found = next(target_dir.rglob("soffice.exe"), None)

        if not found:
            with _install_lock:
                _install_state["log"] += (
                    "  msiexec /a did not produce soffice.exe — "
                    "trying 7-Zip fallback…\n"
                )
                # Surface tail of msiexec log for debugging.
                if log_path.exists():
                    try:
                        tail = log_path.read_text(
                            encoding="utf-16-le", errors="replace"
                        )[-3000:]
                        _install_state["log"] += (
                            "  --- last 3 KB of msiexec log ---\n"
                            + tail + "\n  --- end log ---\n"
                        )
                    except Exception:
                        pass
            ok, fb_log = _try_extract_msi_with_7zip(msi_path, target_dir)
            with _install_lock:
                _install_state["log"] += fb_log
            if ok:
                found = next(target_dir.rglob("soffice.exe"), None)

        # Clean up the downloaded MSI on success to save ~350 MB.
        if found:
            try:
                msi_path.unlink()
                # Remove the download dir if empty.
                try:
                    log_path.unlink()
                except Exception:
                    pass
                download_dir.rmdir()
            except Exception:
                pass

        with _install_lock:
            _install_state["finished_at"] = time.time()
            if found:
                # Persist the parent of "program/soffice.exe".
                install_root = found.parent.parent
                try:
                    _write_custom_soffice_dir(str(install_root))
                except Exception as exc:
                    log.warning("Failed to persist custom dir: %s", exc)
                _install_state["status"] = "success"
                _install_state["log"] += (
                    f"\n[ok] LibreOffice extracted to: {install_root}\n"
                    f"      soffice.exe: {found}\n"
                )
            else:
                _install_state["status"] = "error"
                _install_state["log"] += (
                    f"\n[error] Could not extract LibreOffice to {target_dir}.\n"
                    f"  msiexec /a failed with exit {proc.returncode} and "
                    f"7-Zip fallback was unavailable or also failed.\n"
                    f"  Workarounds:\n"
                    f"   1. Install 7-Zip (https://www.7-zip.org/) and retry — "
                    f"the portable install will use it automatically.\n"
                    f"   2. Use the admin install button instead (requires UAC).\n"
                    f"   3. Manually extract the MSI: open it with 7-Zip, "
                    f"extract to a folder, then point the 'Install location' "
                    f"field above at the folder containing program\\soffice.exe.\n"
                )
    except Exception as exc:
        with _install_lock:
            _install_state["status"] = "error"
            _install_state["log"] += f"\n[exception] {exc}\n"
            _install_state["finished_at"] = time.time()


class InstallSofficePortableRequest(BaseModel):
    location: str = Field(
        default="",
        description=(
            "Optional target directory. Default: "
            "%LOCALAPPDATA%\\reeds_copilot\\LibreOfficePortable"
        ),
    )


@router.post("/install-soffice-portable")
def install_soffice_portable(req: InstallSofficePortableRequest | None = None):
    """No-admin LibreOffice install: download MSI, extract via `msiexec /a`.

    Works on Windows only. The extracted LibreOffice runs standalone from
    the chosen folder — nothing is added to PATH or the Windows registry.
    """
    if not sys.platform.startswith("win"):
        return {
            "status": "unsupported",
            "detail": "Portable install is Windows-only.",
        }
    if _find_soffice():
        return {"status": "already_installed"}
    target = Path((req.location.strip() if req and req.location else "") or
                  str(_default_portable_dir()))
    with _install_lock:
        if _install_state["status"] == "running":
            return {"status": "already_running"}
        _install_state.update({
            "status": "running",
            "log": (
                f"$ msiexec /a LibreOffice.msi /qn TARGETDIR={target}\n"
                f"  (downloading + extracting, no admin / UAC required)\n"
            ),
            "started_at": time.time(),
            "finished_at": 0.0,
            "exit_code": None,
        })
    threading.Thread(
        target=_run_portable_install_job, args=(target,), daemon=True,
    ).start()
    return {"status": "started", "target": str(target)}


@router.get("/install-soffice-status")
def install_soffice_status():
    """Poll endpoint for the install job's progress."""
    with _install_lock:
        state = dict(_install_state)
    # Re-check installed state in case it finished outside our job (e.g. user
    # installed manually during the same session).
    state["installed"] = bool(_find_soffice())
    return state


def _soffice_missing_html(download_url: str | None = None) -> str:
    """HTML page shown inside the preview iframe when LibreOffice is missing.

    JSON 503s render as ugly browser error pages inside an <iframe>; a real
    HTML body lets us explain what's going on and offer a one-click install
    plus a download fallback.
    """
    dl_btn = (
        f'<a class="btn btn-secondary" href="{download_url}" download>⬇ Download the .pptx</a>'
        if download_url else ""
    )
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>PowerPoint preview unavailable</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
          sans-serif; padding: 32px; max-width: 640px; margin: 0 auto;
          color: #222; background: #fff; }}
  h2 {{ margin-top: 0; }}
  code {{ background: #f3f4f6; padding: 2px 6px; border-radius: 4px;
          font-size: 0.9em; }}
  .btn {{ display: inline-block; padding: 8px 16px; background: #2563eb;
          color: #fff; border-radius: 6px; text-decoration: none;
          font-weight: 600; margin: 8px 8px 0 0; cursor: pointer;
          border: none; font-size: 0.95em; }}
  .btn:hover {{ background: #1d4ed8; }}
  .btn:disabled {{ opacity: 0.6; cursor: not-allowed; }}
  .btn-secondary {{ background: #6b7280; }}
  .btn-secondary:hover {{ background: #4b5563; }}
  .hint {{ color: #6b7280; font-size: 0.9em; margin-top: 24px; }}
  #install-log {{ display: none; margin-top: 16px; padding: 12px;
                  background: #0f172a; color: #cbd5e1; border-radius: 6px;
                  font-family: ui-monospace, "Cascadia Code", Consolas,
                  monospace; font-size: 0.8em; max-height: 300px;
                  overflow: auto; white-space: pre-wrap; word-break: break-all; }}
  #install-status {{ margin-top: 16px; font-weight: 600; }}
  .ok {{ color: #16a34a; }}
  .err {{ color: #dc2626; }}
  .running {{ color: #2563eb; }}
  details {{ margin-top: 16px; }}
  summary {{ cursor: pointer; color: #6b7280; font-size: 0.9em; }}
  .field {{ margin: 12px 0 4px 0; }}
  .field label {{ display: block; font-size: 0.85em; color: #374151;
                  font-weight: 600; margin-bottom: 4px; }}
  .field input {{ width: 100%; padding: 8px 10px; border: 1px solid #d1d5db;
                  border-radius: 6px; font-family: ui-monospace, Consolas,
                  monospace; font-size: 0.85em; box-sizing: border-box; }}
  .field input:focus {{ outline: none; border-color: #2563eb;
                        box-shadow: 0 0 0 2px rgba(37, 99, 235, 0.2); }}
  .field .field-hint {{ font-size: 0.75em; color: #6b7280; margin-top: 4px; }}
</style></head>
<body>
  <h2>📊 PowerPoint preview unavailable</h2>
  <p>
    To preview <code>.pptx</code> files in the browser, the backend converts
    them to PDF using <strong>LibreOffice</strong>, but it isn't installed on
    this machine.
  </p>

  <div id="location-field" class="field" style="display:none">
    <label for="install-location">Install location</label>
    <input id="install-location" type="text" placeholder="" autocomplete="off" />
    <div class="field-hint" id="location-hint">
      Default: <code id="default-loc">C:\Program Files\LibreOffice</code>.
      Leave as-is, or type a different folder (e.g. <code>D:\Apps\LibreOffice</code>).
      Requires admin rights either way.
    </div>
  </div>

  <div id="actions">
    <button id="install-btn" class="btn">⚙ Install LibreOffice (admin)</button>
    <button id="install-portable-btn" class="btn" style="display:none"
            title="Downloads LibreOffice and extracts it to a user folder using `msiexec /a`. No UAC prompt, no system changes.">
      📁 Install portable (no admin)
    </button>
    {dl_btn}
  </div>

  <div id="install-status"></div>
  <pre id="install-log"></pre>

  <details>
    <summary>Manual install instructions</summary>
    <ul>
      <li>Windows: <code>winget install TheDocumentFoundation.LibreOffice</code></li>
      <li>macOS: <code>brew install --cask libreoffice</code></li>
      <li>Linux: <code>sudo apt install libreoffice</code></li>
      <li>Or download from <a href="https://www.libreoffice.org/" target="_blank" rel="noreferrer">libreoffice.org</a></li>
    </ul>
    <p class="hint">After installing manually, restart the ReEDS-Copilot
    backend, then reload this preview.</p>
  </details>

<script>
const btn = document.getElementById("install-btn");
const portableBtn = document.getElementById("install-portable-btn");
const statusEl = document.getElementById("install-status");
const logEl = document.getElementById("install-log");
const locField = document.getElementById("location-field");
const locInput = document.getElementById("install-location");
const defaultLocEl = document.getElementById("default-loc");

async function checkStatus() {{
  // Probe whether auto-install is even available on this OS.
  try {{
    const r = await fetch("/api/files/soffice-status");
    const j = await r.json();
    if (!j.auto_install_available) {{
      btn.disabled = true;
      btn.textContent = "Auto-install not available on this OS";
      btn.title = "No supported package manager (winget / brew / apt / dnf) found.";
    }}
    if (j.default_install_dir) {{
      defaultLocEl.textContent = j.default_install_dir;
      locInput.placeholder = j.default_install_dir;
    }}
    if (j.custom_install_dir) {{
      locInput.value = j.custom_install_dir;
    }}
    if (j.supports_custom_location) {{
      locField.style.display = "";
      // Portable install is also Windows-only.
      portableBtn.style.display = "";
    }}
  }} catch (e) {{ /* ignore — button will still try */ }}
}}

function reloadPreview() {{
  // Replace the iframe URL with a cache-busting query to force a fresh
  // request, and show a clear "converting…" message because the first
  // pptx → pdf conversion can take 30+ seconds (LibreOffice cold start).
  document.body.innerHTML =
    '<div style="font-family:system-ui;padding:40px;text-align:center;color:#333">'
    + '<div style="font-size:48px;margin-bottom:12px">\u23f3</div>'
    + '<h2 style="margin:0 0 8px">Converting PowerPoint to PDF\u2026</h2>'
    + '<p style="color:#666;margin:0 0 20px">First-time conversion can take up to a minute while LibreOffice starts up.</p>'
    + '<div class="spinner" style="width:32px;height:32px;border:3px solid #e2e8f0;border-top-color:#3182ce;border-radius:50%;margin:0 auto;animation:spin 1s linear infinite"></div>'
    + '<style>@keyframes spin{{to{{transform:rotate(360deg)}}}}</style>'
    + '</div>';
  const url = new URL(window.location.href);
  url.searchParams.set("_t", Date.now().toString());
  // Use replace() so back-button doesn't return to this loading page.
  window.location.replace(url.toString());
}}

async function pollUntilDone() {{
  while (true) {{
    await new Promise(r => setTimeout(r, 1500));
    let j;
    try {{
      const r = await fetch("/api/files/install-soffice-status");
      j = await r.json();
    }} catch (e) {{ continue; }}
    logEl.textContent = j.log || "";
    logEl.scrollTop = logEl.scrollHeight;
    if (j.status === "success" || j.installed) {{
      statusEl.innerHTML = '<span class="ok">✓ LibreOffice installed!</span> '
        + '<button class="btn" onclick="reloadPreview()">Reload preview</button>';
      btn.disabled = false;
      btn.textContent = "⚙ Install LibreOffice automatically";
      return;
    }}
    if (j.status === "error") {{
      statusEl.innerHTML = '<span class="err">✗ Install failed.</span> '
        + 'See log below or install manually.';
      btn.disabled = false;
      btn.textContent = "⚙ Try install again";
      return;
    }}
    if (j.status === "unsupported") {{
      statusEl.innerHTML = '<span class="err">✗ Auto-install not supported on this OS.</span>';
      btn.disabled = true;
      return;
    }}
  }}
}}

btn.addEventListener("click", async () => {{
  btn.disabled = true;
  if (portableBtn) portableBtn.disabled = true;
  btn.textContent = "Installing… (may take a few minutes)";
  statusEl.innerHTML = '<span class="running">⏳ Running install command…</span>';
  logEl.style.display = "block";
  logEl.textContent = "Starting install…\\n";
  const location = (locInput && locInput.value.trim()) || "";
  try {{
    const r = await fetch("/api/files/install-soffice", {{
      method: "POST",
      headers: {{ "Content-Type": "application/json" }},
      body: JSON.stringify({{ location: location }}),
    }});
    const j = await r.json();
    if (j.status === "already_installed") {{
      statusEl.innerHTML = '<span class="ok">✓ Already installed!</span> '
        + '<button class="btn" onclick="reloadPreview()">Reload preview</button>';
      return;
    }}
    if (j.status === "unsupported") {{
      statusEl.innerHTML = '<span class="err">✗ ' + (j.detail || "Unsupported OS") + '</span>';
      btn.disabled = true;
      return;
    }}
    pollUntilDone();
  }} catch (e) {{
    statusEl.innerHTML = '<span class="err">✗ Could not reach backend: ' + e + '</span>';
    btn.disabled = false;
    if (portableBtn) portableBtn.disabled = false;
    btn.textContent = "⚙ Try install again";
  }}
}});

if (portableBtn) {{
  portableBtn.addEventListener("click", async () => {{
    btn.disabled = true;
    portableBtn.disabled = true;
    portableBtn.textContent = "Downloading + extracting… (~355 MB)";
    statusEl.innerHTML = '<span class="running">⏳ Downloading LibreOffice…</span>';
    logEl.style.display = "block";
    logEl.textContent = "Starting portable install…\\n";
    const location = (locInput && locInput.value.trim()) || "";
    try {{
      const r = await fetch("/api/files/install-soffice-portable", {{
        method: "POST",
        headers: {{ "Content-Type": "application/json" }},
        body: JSON.stringify({{ location: location }}),
      }});
      const j = await r.json();
      if (j.status === "already_installed") {{
        statusEl.innerHTML = '<span class="ok">✓ Already installed!</span> '
          + '<button class="btn" onclick="reloadPreview()">Reload preview</button>';
        return;
      }}
      if (j.status === "unsupported") {{
        statusEl.innerHTML = '<span class="err">✗ ' + (j.detail || "Unsupported OS") + '</span>';
        portableBtn.disabled = true;
        return;
      }}
      pollUntilDone();
    }} catch (e) {{
      statusEl.innerHTML = '<span class="err">✗ Could not reach backend: ' + e + '</span>';
      btn.disabled = false;
      portableBtn.disabled = false;
      portableBtn.textContent = "📁 Install portable (no admin)";
    }}
  }});
}}

checkStatus();
</script>
</body></html>"""


_PPTX_CACHE_DIR = Path(tempfile.gettempdir()) / "reeds_copilot_pptx_cache"


@router.get("/pptx-view")
def pptx_view(
    path: str = Query(..., description="Relative path to a .pptx inside the repo"),
    settings: Settings = Depends(get_settings),
):
    """Convert a .pptx to PDF (cached) and serve it inline so the browser
    can render it natively. Falls back to a 503 if LibreOffice is not
    installed — the frontend should then keep offering the download button.
    """
    try:
        target = safe_resolve(settings.repo_root, path)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    if not target.is_file():
        raise HTTPException(status_code=404, detail=f"Not a file: {path}")
    if target.suffix.lower() != ".pptx":
        raise HTTPException(status_code=400, detail="Only .pptx files are supported")

    soffice = _find_soffice()
    if not soffice:
        return HTMLResponse(content=_soffice_missing_html(), status_code=200)

    # Cache key includes path + mtime + size so a re-generated pptx invalidates.
    st = target.stat()
    key_src = f"{target.resolve()}|{int(st.st_mtime)}|{st.st_size}"
    key = hashlib.sha256(key_src.encode("utf-8")).hexdigest()[:16]
    _PPTX_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    pdf_path = _PPTX_CACHE_DIR / f"{key}.pdf"

    if not pdf_path.exists():
        with tempfile.TemporaryDirectory(prefix="pptx2pdf_") as tmp:
            try:
                proc = subprocess.run(
                    [
                        soffice, "--headless", "--norestore", "--nologo",
                        "--convert-to", "pdf",
                        "--outdir", tmp,
                        str(target),
                    ],
                    capture_output=True, timeout=120,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            except subprocess.TimeoutExpired:
                raise HTTPException(status_code=504, detail="PPTX conversion timed out (>120s)")
            produced = Path(tmp) / (target.stem + ".pdf")
            if not produced.exists():
                stderr = proc.stderr.decode(errors="replace")[:400] if proc.stderr else ""
                log.warning("LibreOffice conversion failed for %s: %s", target, stderr)
                raise HTTPException(
                    status_code=500,
                    detail=f"PPTX conversion failed. {stderr or 'No PDF produced.'}",
                )
            # Move into the cache atomically
            os.replace(str(produced), str(pdf_path))

    return FileResponse(
        path=str(pdf_path),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="{target.stem}.pdf"',
            "Cache-Control": "private, max-age=300",
        },
    )


# ── HPC remote file browsing (via paramiko SSH) ─────────────────────────────

log = logging.getLogger(__name__)
_SAFE_SSH_RE = re.compile(r'^[a-zA-Z0-9._\-]+$')

# Reusable SSH connection cache  {(host, user): paramiko.SSHClient}
_ssh_pool: dict[tuple[str, str], paramiko.SSHClient] = {}
_ssh_lock = threading.Lock()


# ── Session tokens (so the frontend can drop the password after login) ─────
# Maps an opaque random token to the (host, user) pair whose SSH client
# lives in _ssh_pool. Tokens expire after IDLE_TIMEOUT_SECS of inactivity.
_sessions: dict[str, dict] = {}
_session_lock = threading.Lock()
SESSION_IDLE_TIMEOUT_SECS = 30 * 60   # 30 minutes


def _mint_session(host: str, user: str) -> str:
    token = secrets.token_urlsafe(32)
    with _session_lock:
        _sessions[token] = {
            "host": host, "user": user, "last_used": time.time(),
        }
    return token


def _resolve_session(token: str) -> tuple[str, str] | None:
    """Return (host, user) for a valid token, or None if expired/unknown."""
    if not token:
        return None
    with _session_lock:
        entry = _sessions.get(token)
        if entry is None:
            return None
        if time.time() - entry["last_used"] > SESSION_IDLE_TIMEOUT_SECS:
            _sessions.pop(token, None)
            return None
        entry["last_used"] = time.time()
        return (entry["host"], entry["user"])


def _revoke_session(token: str) -> None:
    if not token:
        return
    with _session_lock:
        _sessions.pop(token, None)


def _resolve_creds(
    session_token: str | None,
    host: str | None,
    user: str | None,
    password: str | None,
) -> tuple[str, str, str]:
    """Return (host, user, password) using a session token when available.

    If `session_token` is valid, the cached SSH client in _ssh_pool is reused;
    no password is needed. Otherwise falls back to explicit (host, user, password).
    """
    if session_token:
        resolved = _resolve_session(session_token)
        if resolved is None:
            raise HTTPException(
                status_code=401,
                detail="Session expired. Please reconnect to the HPC.",
            )
        return (resolved[0], resolved[1], "")
    if not host or not user:
        raise HTTPException(
            status_code=400,
            detail="Either session_token or (host, user) must be provided.",
        )
    return (host, user, password or "")


class HpcListRequest(BaseModel):
    host: str = Field(default="", description="HPC login node hostname")
    user: str = Field(default="", description="SSH username")
    path: str = Field(..., description="Absolute path on HPC")
    password: str = Field(default="", description="SSH password (never logged)")
    session_token: str = Field(default="", description="Opaque session token from /hpc/connect")


class HpcPreviewRequest(BaseModel):
    host: str = Field(default="", description="HPC login node hostname")
    user: str = Field(default="", description="SSH username")
    path: str = Field(..., description="Absolute file path on HPC")
    password: str = Field(default="", description="SSH password (never logged)")
    session_token: str = Field(default="", description="Opaque session token from /hpc/connect")
    lines: int = Field(default=200, ge=1, le=5000)
    gdx_symbol: str | None = Field(default=None, description="GDX symbol name to preview")
    h5_dataset: str | None = Field(default=None, description="HDF5 dataset path to preview")


class HpcDisconnectRequest(BaseModel):
    host: str = Field(default="", description="HPC login node hostname")
    user: str = Field(default="", description="SSH username")
    session_token: str = Field(default="", description="Opaque session token from /hpc/connect")


class HpcCasesRequest(BaseModel):
    host: str = Field(default="", description="HPC login node hostname")
    user: str = Field(default="", description="SSH username")
    reeds_path: str = Field(..., description="Absolute path to ReEDS repo on HPC")
    password: str = Field(default="", description="SSH password (never logged)")
    session_token: str = Field(default="", description="Opaque session token from /hpc/connect")


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


# ── HPC remote-file local cache ────────────────────────────────────────────
# Used for binary-format previews (h5/gdx) and inline serving (images, pptx).
# Files are cached under the OS temp dir, keyed by (host, abs path, mtime,
# size). Stale cache entries are simply overwritten on the next download.

_HPC_CACHE_DIR = Path(tempfile.gettempdir()) / "reeds_copilot_hpc_cache"
_HPC_DOWNLOAD_MAX_BYTES = 2 * 1024 * 1024 * 1024  # 2 GB safety cap
_HPC_CACHE_LOCK = threading.Lock()


def _hpc_remote_stat(host: str, user: str, password: str,
                     path: str) -> tuple[int, int]:
    """Return (size, mtime) for a remote file using a single stat call."""
    out = _ssh_exec(
        host, user,
        f'stat --format="%s|%Y" {path} 2>/dev/null',
        password=password, timeout=15,
    ).strip()
    if "|" not in out:
        raise HTTPException(status_code=404, detail=f"Remote file not found: {path}")
    size_s, mtime_s = out.split("|", 1)
    try:
        return int(size_s), int(mtime_s)
    except ValueError:
        raise HTTPException(status_code=502, detail="Bad stat output from HPC")


def _hpc_download_to_cache(host: str, user: str, password: str,
                           remote_path: str) -> Path:
    """Download a remote file to the local cache and return the cached Path.

    The cache key is sha256(host|abs_path|mtime|size)[:16]. If a fresh copy
    already exists it is reused, so repeated previews are instant.
    """
    size, mtime = _hpc_remote_stat(host, user, password, remote_path)
    if size > _HPC_DOWNLOAD_MAX_BYTES:
        raise HTTPException(
            status_code=413,
            detail=(
                f"Remote file is {size / 1024 / 1024:.1f} MB which exceeds the "
                f"{_HPC_DOWNLOAD_MAX_BYTES // 1024 // 1024} MB preview cap."
            ),
        )

    name = remote_path.rsplit("/", 1)[-1]
    key_src = f"{host}|{remote_path}|{mtime}|{size}"
    key = hashlib.sha256(key_src.encode("utf-8")).hexdigest()[:16]
    _HPC_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cached = _HPC_CACHE_DIR / f"{key}_{name}"

    with _HPC_CACHE_LOCK:
        if cached.exists() and cached.stat().st_size == size:
            return cached
        client = _get_ssh_client(host, user, password)
        sftp = client.open_sftp()
        tmp = cached.with_suffix(cached.suffix + ".part")
        try:
            try:
                sftp.get(remote_path, str(tmp))
            finally:
                try:
                    sftp.close()
                except Exception:
                    pass
            os.replace(str(tmp), str(cached))
        except Exception as exc:
            try:
                if tmp.exists():
                    tmp.unlink()
            except Exception:
                pass
            raise HTTPException(
                status_code=502,
                detail=f"SFTP download failed: {exc}",
            )
    return cached


# ── Raw streaming of remote files (used for image previews) ────────────────


@router.get("/hpc/raw")
def hpc_raw(
    path: str = Query(...),
    host: str = Query(""),
    user: str = Query(""),
    session_token: str = Query(""),
    download: int = Query(0, description="If 1, force attachment disposition"),
):
    """Download a remote file to local cache and serve it inline (or as an
    attachment when ``download=1``).

    Used by the HPC Explorer preview pane for images/HTML reports, and by
    the "Download" button to save the original file to the user's machine.
    Authentication uses the same opaque session token the rest of the HPC
    API expects.
    """
    if not _is_safe_hpc_path(path):
        raise HTTPException(status_code=400, detail="Invalid path characters")
    h, u, pw = _resolve_creds(session_token, host, user, "")
    cached = _hpc_download_to_cache(h, u, pw, path)
    suffix = cached.suffix.lower()
    media = MEDIA_TYPES.get(suffix, "application/octet-stream")
    filename = path.rsplit("/", 1)[-1]
    if download:
        # `filename=` makes Starlette emit Content-Disposition: attachment
        return FileResponse(
            path=str(cached),
            media_type="application/octet-stream",
            filename=filename,
        )
    # Inline: do NOT pass filename= (it would force attachment disposition
    # and break iframe rendering of HTML/PDF previews).
    return FileResponse(path=str(cached), media_type=media)


# ── PPTX in-browser preview for HPC files (download → convert → serve) ────


@router.get("/hpc/pptx-view")
def hpc_pptx_view(
    path: str = Query(...),
    host: str = Query(""),
    user: str = Query(""),
    session_token: str = Query(""),
):
    """Download a remote .pptx, convert to PDF via LibreOffice, serve inline."""
    if not _is_safe_hpc_path(path):
        raise HTTPException(status_code=400, detail="Invalid path characters")
    if not path.lower().endswith(".pptx"):
        raise HTTPException(status_code=400, detail="Only .pptx files are supported")

    soffice = _find_soffice()
    if not soffice:
        # Build a download URL for this same remote file so the user can grab
        # the original .pptx even though preview isn't available.
        from urllib.parse import urlencode
        dl = f"/api/files/hpc/raw?{urlencode({'host': host, 'user': user, 'session_token': session_token, 'path': path, 'download': '1'})}"
        return HTMLResponse(content=_soffice_missing_html(dl), status_code=200)

    h, u, pw = _resolve_creds(session_token, host, user, "")
    src = _hpc_download_to_cache(h, u, pw, path)

    st = src.stat()
    key_src = f"{src.resolve()}|{int(st.st_mtime)}|{st.st_size}"
    key = hashlib.sha256(key_src.encode("utf-8")).hexdigest()[:16]
    _PPTX_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    pdf_path = _PPTX_CACHE_DIR / f"hpc_{key}.pdf"

    if not pdf_path.exists():
        with tempfile.TemporaryDirectory(prefix="hpc_pptx2pdf_") as tmp:
            try:
                proc = subprocess.run(
                    [
                        soffice, "--headless", "--norestore", "--nologo",
                        "--convert-to", "pdf",
                        "--outdir", tmp,
                        str(src),
                    ],
                    capture_output=True, timeout=120,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            except subprocess.TimeoutExpired:
                raise HTTPException(status_code=504, detail="PPTX conversion timed out (>120s)")
            produced = Path(tmp) / (src.stem + ".pdf")
            if not produced.exists():
                stderr = proc.stderr.decode(errors="replace")[:400] if proc.stderr else ""
                raise HTTPException(
                    status_code=500,
                    detail=f"PPTX conversion failed. {stderr or 'No PDF produced.'}",
                )
            os.replace(str(produced), str(pdf_path))

    return FileResponse(
        path=str(pdf_path),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="{src.stem}.pdf"',
            "Cache-Control": "private, max-age=300",
        },
    )


@router.post("/hpc/list", response_model=FileListResponse)
def list_hpc_files(req: HpcListRequest):
    """List directory contents on a remote HPC node via SSH."""
    if not _is_safe_hpc_path(req.path):
        raise HTTPException(status_code=400, detail="Invalid path characters")

    host, user, password = _resolve_creds(
        req.session_token, req.host, req.user, req.password)
    remote_cmd = f'ls -lLA --time-style=+%s {req.path} 2>/dev/null'
    out = _ssh_exec(host, user, remote_cmd, password=password)

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
    """Preview a text file on the remote HPC via SSH.

    For binary types we know how to read locally (.h5/.hdf5/.gdx, images,
    .pptx), the file is downloaded once to ``_HPC_CACHE_DIR`` (keyed by
    path|mtime|size) and the existing local preview helper is reused. This
    keeps feature parity with the local Outputs Explorer without requiring
    extra software on the HPC side.
    """
    if not _is_safe_hpc_path(req.path):
        raise HTTPException(status_code=400, detail="Invalid path characters")

    host, user, password = _resolve_creds(
        req.session_token, req.host, req.user, req.password)
    name = req.path.rsplit("/", 1)[-1] if "/" in req.path else req.path
    dot = name.rfind(".")
    ext = name[dot:].lower() if dot > 0 else ""

    image_exts = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".bmp"}
    h5_exts = {".h5", ".hdf5"}
    gdx_exts = {".gdx"}
    other_binary = {".g00", ".xlsx", ".xls", ".zip", ".tar", ".gz",
                    ".pdf", ".pkl", ".parquet"}

    # Rich previews via local cache (h5 / gdx). For images we just confirm
    # the file exists; the frontend renders them through /hpc/raw.
    if ext in h5_exts or ext in gdx_exts:
        try:
            local = _hpc_download_to_cache(host, user, password, req.path)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(
                status_code=502,
                detail=f"Failed to download remote file for preview: {exc}",
            )
        try:
            from ..services.file_inspector import _preview_h5, _preview_gdx
            if ext in h5_exts:
                result = _preview_h5(local, req.path, dataset=req.h5_dataset)
            else:
                result = _preview_gdx(local, req.path, symbol=req.gdx_symbol)
        except Exception as exc:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to read {ext} file: {exc}",
            )
        return FilePreviewResponse(**result)

    if ext in image_exts:
        try:
            out = _ssh_exec(host, user,
                            f'stat --format="%s" {req.path} 2>/dev/null',
                            password=password, timeout=10)
            fsize = int(out.strip())
        except Exception:
            fsize = 0
        return FilePreviewResponse(
            rel_path=req.path, file_type=ext,
            content=None, is_image=True, truncated=False, total_rows=fsize,
        )

    if ext in other_binary:
        try:
            out = _ssh_exec(host, user,
                            f'stat --format="%s" {req.path} 2>/dev/null',
                            password=password, timeout=10)
            fsize = int(out.strip())
        except Exception:
            fsize = 0
        return FilePreviewResponse(
            rel_path=req.path, file_type=ext,
            content=f"[Binary file: {name} ({fsize:,} bytes)]",
            truncated=False,
        )

    if ext == ".csv":
        out = _ssh_exec(host, user,
                        f'head -n {req.lines + 1} {req.path} 2>/dev/null',
                        password=password)
        if not out.strip():
            return FilePreviewResponse(rel_path=req.path, file_type=ext,
                                       content="(empty file)")

        reader = csv_mod.DictReader(io.StringIO(out))
        columns = reader.fieldnames or []
        rows = [dict(row) for i, row in enumerate(reader) if i < req.lines]

        try:
            wc_out = _ssh_exec(host, user,
                               f'wc -l < {req.path} 2>/dev/null',
                               password=password, timeout=10)
            total = int(wc_out.strip()) - 1
        except Exception:
            total = len(rows)

        return FilePreviewResponse(
            rel_path=req.path, file_type=ext,
            columns=list(columns), rows=rows,
            total_rows=total, truncated=(total > len(rows)),
        )

    # Text files
    out = _ssh_exec(host, user,
                    f'head -n {req.lines} {req.path} 2>/dev/null',
                    password=password)

    try:
        wc_out = _ssh_exec(host, user,
                           f'wc -l < {req.path} 2>/dev/null',
                           password=password, timeout=10)
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
    """Close SSH connection, revoke session token, and clear credentials."""
    # Resolve host/user from session_token if provided
    if req.session_token:
        resolved = _resolve_session(req.session_token)
        if resolved is not None:
            host, user = resolved
        else:
            host, user = req.host, req.user
        _revoke_session(req.session_token)
    else:
        host, user = req.host, req.user
    if host and user:
        key = (host, user)
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
    if not _is_safe_hpc_path(req.reeds_path):
        raise HTTPException(status_code=400, detail="Invalid path characters")
    host, user, password = _resolve_creds(
        req.session_token, req.host, req.user, req.password)
    # List all cases*.csv files
    cmd = f'ls -1 {req.reeds_path}/cases*.csv 2>/dev/null'
    out = _ssh_exec(host, user, cmd, password=password, timeout=15)

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
            csv_out = _ssh_exec(host, user, head_cmd,
                                password=password, timeout=15)
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
    host: str = Field(default="", description="HPC login node hostname")
    user: str = Field(default="", description="SSH username")
    password: str = Field(default="", description="SSH password (never logged)")
    session_token: str = Field(default="", description="Opaque session token from /hpc/connect")


class HpcEnvCheckRequest(HpcConnectRequest):
    reeds_path: str = Field(..., description="Absolute path to ReEDS repo on HPC")
    conda_env: str = Field(default="reeds2", description="Conda env name to check")


@router.post("/hpc/connect")
def hpc_connect(req: HpcConnectRequest):
    """Verify SSH login. Returns home dir, suggested ReEDS-repo paths, and a session token.

    The returned `session_token` lets the frontend make subsequent HPC API calls
    without re-sending the password. Tokens expire after 30 min of inactivity.
    """
    if not req.host or not req.user:
        raise HTTPException(status_code=400, detail="host and user are required")
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
    token = _mint_session(req.host, req.user)
    return {
        "ok": True,
        "home": home,
        "hostname": hostname,
        "suggested_paths": candidates[:6],
        "session_token": token,
    }


@router.post("/hpc/conda-envs")
def hpc_conda_envs(req: HpcConnectRequest):
    """Return the list of conda envs available on the HPC for this user."""
    host, user, password = _resolve_creds(
        req.session_token, req.host, req.user, req.password)
    out = _ssh_exec(host, user,
                    "module load anaconda3 2>/dev/null; "
                    "module load conda 2>/dev/null; "
                    "(conda env list 2>/dev/null || ~/.conda/envs/.. 2>/dev/null) | "
                    "grep -v '^#' | awk 'NF>=1 {print $1}'",
                    password=password, timeout=20)
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
    if not _is_safe_hpc_path(req.reeds_path):
        raise HTTPException(status_code=400, detail="Invalid reeds_path characters")
    if not re.match(r'^[a-zA-Z0-9_.\-]+$', req.conda_env):
        raise HTTPException(status_code=400, detail="Invalid conda env name")
    host, user, password = _resolve_creds(
        req.session_token, req.host, req.user, req.password)

    # One combined script — minimizes SSH round-trips. Loads the typical
    # NREL HPC modules (anaconda3 + gams) so the checks reflect what
    # runbatch.py / sbatch jobs will actually see at runtime.
    script = (
        "module load anaconda3 2>/dev/null; module load conda 2>/dev/null; "
        "module load gams 2>/dev/null; "
        f"source activate {req.conda_env} 2>/dev/null || conda activate {req.conda_env} 2>/dev/null; "
        f"echo CONDA_PREFIX=$CONDA_PREFIX; "
        f"echo PYTHON=$(which python 2>/dev/null); "
        "echo GAMS=$(which gams 2>/dev/null); "
        "echo JULIA=$(which julia 2>/dev/null); "
        # GAMS license: a network/site license is fine; check both
        # in-repo gamslice.txt AND env vars used by GAMS.
        f"echo LICENSE_FILE=$([ -f {req.reeds_path}/gamslice.txt ] && echo 1 || echo 0); "
        "echo GAMS_LICENSE_ENV=$GAMSLICE; "
        "echo GAMS_LICENSE_ENV2=$GAMS_LICENSE_FILE; "
        # If gams is on PATH, derive its sysdir and look for gamslice.txt
        # in the standard system location too.
        "GBIN=$(command -v gams 2>/dev/null); "
        "if [ -n \"$GBIN\" ]; then "
        "  GDIR=$(dirname \"$(readlink -f \"$GBIN\" 2>/dev/null || echo $GBIN)\"); "
        "  echo GAMS_SYSLIC=$([ -f \"$GDIR/gamslice.txt\" ] && echo 1 || echo 0); "
        "fi; "
        f"echo REPO=$([ -f {req.reeds_path}/cases.csv ] && [ -f {req.reeds_path}/runbatch.py ] && echo 1 || echo 0); "
        f"echo SLURM=$(which sbatch 2>/dev/null)"
    )
    out = _ssh_exec(host, user, script, password=password, timeout=25)
    info: dict[str, str] = {}
    for line in out.splitlines():
        if "=" in line:
            k, _, v = line.partition("=")
            info[k.strip()] = v.strip()

    # Conda env is "ok" if the prefix points at a directory matching the
    # env name (basename match) — works whether activation set
    # CONDA_DEFAULT_ENV or not.
    conda_prefix = info.get("CONDA_PREFIX", "")
    conda_ok = bool(conda_prefix) and (
        conda_prefix.rstrip("/").endswith("/" + req.conda_env)
        or conda_prefix.rstrip("/").split("/")[-1] == req.conda_env
    )

    # GAMS license: any of the three signals counts (in-repo file,
    # env var pointing at a license, or sysdir gamslice.txt — i.e. a
    # site/network license already configured for this user).
    license_repo = info.get("LICENSE_FILE") == "1"
    license_env = bool(info.get("GAMS_LICENSE_ENV") or info.get("GAMS_LICENSE_ENV2"))
    license_sys = info.get("GAMS_SYSLIC") == "1"
    license_ok = license_repo or license_env or license_sys
    if license_repo:
        license_detail = f"found in repo: {req.reeds_path}/gamslice.txt"
    elif license_env:
        license_detail = (
            f"env var: {info.get('GAMS_LICENSE_ENV') or info.get('GAMS_LICENSE_ENV2')}"
        )
    elif license_sys:
        license_detail = "site license in GAMS sysdir"
    else:
        license_detail = "not found (no gamslice.txt and no GAMS_LICENSE_FILE env)"

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
            "ok": conda_ok,
            "detail": conda_prefix or "not found / activation failed",
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
            "label": "GAMS license",
            "ok": license_ok,
            "detail": license_detail,
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
    host, user, password = _resolve_creds(
        req.session_token, req.host, req.user, req.password)
    out = _ssh_exec(host, user,
                    f"squeue -u {user} -h "
                    "-o '%i|%j|%T|%M|%l|%R' 2>/dev/null",
                    password=password, timeout=15)
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


# ── Run-folder discovery & sync (parity with local Outputs Explorer) ───────


class HpcRunsRequest(BaseModel):
    host: str = Field(default="")
    user: str = Field(default="")
    reeds_path: str = Field(..., description="Absolute path to ReEDS repo on HPC")
    password: str = Field(default="")
    session_token: str = Field(default="")


class HpcSyncRunRequest(BaseModel):
    host: str = Field(default="")
    user: str = Field(default="")
    reeds_path: str = Field(..., description="Absolute path to ReEDS repo on HPC")
    run_name: str = Field(..., description="Folder name under {reeds_path}/runs")
    password: str = Field(default="")
    session_token: str = Field(default="")
    overwrite: bool = Field(default=False, description="Replace existing local copy")


@router.post("/hpc/list-runs")
def list_hpc_runs(req: HpcRunsRequest):
    """List `runs/` folders on the HPC with status flags, mirroring the local
    Outputs Explorer view. Status is inferred from the same marker files used
    by `runstatus.py` (report.xlsx / outputs / gamslog.txt / meta.csv).
    """
    if not _is_safe_hpc_path(req.reeds_path):
        raise HTTPException(status_code=400, detail="Invalid path characters")

    host, user, password = _resolve_creds(
        req.session_token, req.host, req.user, req.password)
    runs_root = req.reeds_path.rstrip("/") + "/runs"

    # One shell pipeline lists every run folder along with the marker files
    # we care about and the folder mtime — much faster than N SFTP stats.
    cmd = (
        f'set -e; cd "{runs_root}" 2>/dev/null || exit 0; '
        'for d in */; do '
        '  d="${d%/}"; '
        '  [ -d "$d" ] || continue; '
        '  mt=$(stat --format=%Y "$d" 2>/dev/null); '
        '  hr=0; ho=0; hg=0; hm=0; '
        '  [ -f "$d/outputs/reeds-report/report.xlsx" ] && hr=1; '
        '  [ -d "$d/outputs" ] && ho=1; '
        '  [ -f "$d/gamslog.txt" ] && hg=1; '
        '  [ -f "$d/meta.csv" ] && hm=1; '
        '  echo "$d|$mt|$hr|$ho|$hg|$hm"; '
        'done'
    )
    try:
        out = _ssh_exec(host, user, cmd, password=password, timeout=30)
    except HTTPException as exc:
        # No runs/ dir yet — return empty list rather than a hard error
        if exc.status_code == 400:
            return []
        raise

    folders = []
    for line in out.splitlines():
        parts = line.strip().split("|")
        if len(parts) != 6:
            continue
        name, mt, hr, ho, hg, hm = parts
        try:
            mtime = int(mt)
        except ValueError:
            mtime = 0
        folders.append({
            "name": name,
            "path": f"{runs_root}/{name}",
            "has_report": hr == "1",
            "has_outputs": ho == "1",
            "has_gamslog": hg == "1",
            "has_meta": hm == "1",
            "modified_at": mtime,
        })
    folders.sort(key=lambda f: f["modified_at"], reverse=True)
    return folders


def _sftp_walk_download(sftp, remote_dir: str, local_dir: Path,
                       progress: dict, max_bytes: int):
    """Recursively mirror a remote directory to a local one via SFTP."""
    local_dir.mkdir(parents=True, exist_ok=True)
    for attr in sftp.listdir_attr(remote_dir):
        rname = attr.filename
        if rname in (".", ".."):
            continue
        rpath = f"{remote_dir}/{rname}"
        lpath = local_dir / rname
        # st_mode bit 0o040000 == directory
        if (attr.st_mode or 0) & 0o170000 == 0o040000:
            _sftp_walk_download(sftp, rpath, lpath, progress, max_bytes)
        else:
            size = attr.st_size or 0
            if progress["bytes"] + size > max_bytes:
                raise HTTPException(
                    status_code=413,
                    detail=(
                        f"Sync exceeds {max_bytes // (1024 * 1024)} MB cap; "
                        f"aborted at {progress['bytes'] // 1024} KB"
                    ),
                )
            sftp.get(rpath, str(lpath))
            progress["bytes"] += size
            progress["files"] += 1


@router.post("/hpc/sync-run")
def sync_hpc_run(
    req: HpcSyncRunRequest,
    settings: Settings = Depends(get_settings),
):
    """Recursively download a remote `runs/<name>/` folder into the local
    `{repo_root}/runs/<name>/` so that the existing Compare and Post-Process
    panels can operate on it. Capped at 5 GB to avoid runaway transfers.
    """
    if not _is_safe_hpc_path(req.reeds_path):
        raise HTTPException(status_code=400, detail="Invalid reeds_path characters")
    if not re.match(r'^[a-zA-Z0-9._\-]+$', req.run_name):
        raise HTTPException(status_code=400, detail="Invalid run_name characters")

    host, user, password = _resolve_creds(
        req.session_token, req.host, req.user, req.password)
    remote = f"{req.reeds_path.rstrip('/')}/runs/{req.run_name}"
    local = settings.repo_root / "runs" / req.run_name

    if local.exists():
        if not req.overwrite:
            return {
                "synced": False,
                "exists": True,
                "local_path": str(local),
                "message": "Local copy already exists; pass overwrite=true to replace.",
            }
        try:
            shutil.rmtree(local)
        except Exception as exc:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to remove existing local copy: {exc}",
            )

    client = _get_ssh_client(host, user, password)
    sftp = client.open_sftp()
    progress = {"files": 0, "bytes": 0}
    try:
        try:
            sftp.stat(remote)
        except IOError:
            raise HTTPException(
                status_code=404,
                detail=f"Remote run folder not found: {remote}",
            )
        try:
            _sftp_walk_download(sftp, remote, local, progress,
                               max_bytes=5 * 1024 * 1024 * 1024)
        except HTTPException:
            # Roll back partial copy on hard cap
            try:
                shutil.rmtree(local, ignore_errors=True)
            except Exception:
                pass
            raise
    finally:
        try:
            sftp.close()
        except Exception:
            pass

    return {
        "synced": True,
        "exists": False,
        "local_path": str(local),
        "files": progress["files"],
        "bytes": progress["bytes"],
        "message": (
            f"Synced {progress['files']} files "
            f"({progress['bytes'] / 1024 / 1024:.1f} MB) to runs/{req.run_name}"
        ),
    }


# ── HPC-native post-processing (run compare_cases.py / bokeh on cluster) ────


class HpcPostProcessRequest(BaseModel):
    host: str = Field(default="")
    user: str = Field(default="")
    password: str = Field(default="")
    session_token: str = Field(default="")
    reeds_path: str = Field(..., description="Absolute path to ReEDS repo on HPC")
    tool: str = Field(..., description="'compare_cases' or 'bokeh_report'")
    cases: list[str] = Field(..., description="Run folder names under {reeds_path}/runs")
    report: str = Field(default="", description="Bokeh report template (bokeh_report only)")
    bash_prefix: str = Field(
        default="module load anaconda3",
        description="Shell setup commands run before the python invocation",
    )
    extra_args: str = Field(default="", description="Extra CLI args appended to the command")
    timeout_seconds: int = Field(default=900, ge=30, le=7200)
    # Optional per-case scenarios CSV overrides for bokeh_report
    # (label and color per case; the run path is derived from the case name).
    scenarios: list[dict] | None = Field(
        default=None,
        description="List of {name, label, color} dicts for bokeh scenarios CSV",
    )


# Same regex used elsewhere in the codebase to keep run names harmless when
# inserted into a remote shell command.
_HPC_SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9_.\-]+$")


@router.post("/hpc/run-postprocess")
def run_hpc_postprocess(req: HpcPostProcessRequest):
    """SSH into the cluster and execute compare_cases.py or a bokeh report.

    Runs synchronously and returns stdout/stderr along with the path of the
    output directory the user can inspect via the HPC file browser.
    """
    host, user, password = _resolve_creds(req.session_token, req.host, req.user, req.password)

    # Validate
    if req.tool not in ("compare_cases", "bokeh_report"):
        raise HTTPException(status_code=400, detail=f"Unsupported tool: {req.tool}")
    if not req.cases:
        raise HTTPException(status_code=400, detail="No cases selected")
    for c in req.cases:
        if not _HPC_SAFE_NAME_RE.match(c):
            raise HTTPException(status_code=400, detail=f"Unsafe case name: {c}")

    reeds_path = req.reeds_path.rstrip("/")
    runs_dir = f"{reeds_path}/runs"
    case_paths = [f"{runs_dir}/{c}" for c in req.cases]
    quoted_cases = " ".join(shlex.quote(p) for p in case_paths)
    output_dir = f"{runs_dir}/{req.cases[0]}/outputs/comparisons"

    if req.tool == "compare_cases":
        py_cmd = (
            f"cd {shlex.quote(reeds_path)}/postprocessing && "
            f"python compare_cases.py {quoted_cases}"
        )
        if req.extra_args:
            py_cmd += " " + req.extra_args
    else:  # bokeh_report
        if not req.report:
            raise HTTPException(status_code=400, detail="report is required for bokeh_report")
        report = req.report
        if not _HPC_SAFE_NAME_RE.match(report):
            raise HTTPException(status_code=400, detail=f"Unsafe report name: {report}")
        bp = f"{reeds_path}/postprocessing/bokehpivot"
        interface = f"{bp}/reports/interface_report_model.py"
        report_py = f"{bp}/reports/templates/reeds2/{report}.py"
        scen_csv = f"{output_dir}/scenarios_hpc.csv"
        out_path = f"{output_dir}/{report}-multicase"
        # Build a scenarios CSV. Each row: <label>,<color>,<full case path>
        # If the caller supplied custom scenarios, use those (label/color);
        # otherwise default to label=name and rotate through a palette.
        default_colors = [
            "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd",
            "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf",
        ] * 10
        csv_lines = ["name,color,path"]
        if req.scenarios:
            scen_by_name = {s.get("name"): s for s in req.scenarios if s.get("name")}
            for i, (name, path) in enumerate(zip(req.cases, case_paths)):
                s = scen_by_name.get(name, {})
                label = str(s.get("label") or name).replace(",", " ")
                color = str(s.get("color") or default_colors[i])
                csv_lines.append(f"{label},{color},{path}")
        else:
            for i, (name, path) in enumerate(zip(req.cases, case_paths)):
                csv_lines.append(f"{name},{default_colors[i]},{path}")
        csv_body = "\n".join(csv_lines)
        py_cmd = (
            f"mkdir -p {shlex.quote(output_dir)} && "
            f"cat > {shlex.quote(scen_csv)} <<'__EOF__'\n{csv_body}\n__EOF__\n"
            f"python {shlex.quote(interface)} 'ReEDS 2.0' "
            f"{shlex.quote(scen_csv)} all No "
            f"{shlex.quote(req.cases[0])} {shlex.quote(report_py)} "
            f"html,excel one {shlex.quote(out_path)} No"
        )
        if req.extra_args:
            py_cmd += " " + req.extra_args

    full_cmd = (
        f"set -e; {req.bash_prefix} && {py_cmd}" if req.bash_prefix.strip()
        else f"set -e; {py_cmd}"
    )

    client = _get_ssh_client(host, user, password)
    try:
        _, stdout, stderr = client.exec_command(full_cmd, timeout=req.timeout_seconds)
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        exit_code = stdout.channel.recv_exit_status()
    except Exception as exc:
        with _ssh_lock:
            _ssh_pool.pop((host, user), None)
        raise HTTPException(status_code=502, detail=f"SSH exec failed: {exc}")

    # Truncate ridiculous output volumes to keep the response lean.
    MAX = 200_000
    if len(out) > MAX:
        out = out[-MAX:]
        out = "[…truncated…]\n" + out
    if len(err) > MAX:
        err = err[-MAX:]
        err = "[…truncated…]\n" + err

    return {
        "exit_code": exit_code,
        "stdout": out,
        "stderr": err,
        "output_dir": output_dir,
        "command": full_cmd,
    }


# ── HPC Compare (direct, mirrors local /runs/compare/*) ────────────────────


class HpcCompareBrowseRequest(BaseModel):
    host: str
    user: str
    password: str = ""
    session_token: str = ""
    reeds_path: str = Field(..., description="HPC ReEDS root path (parent of runs/)")
    cases: list[str] = Field(..., min_length=2, max_length=20)
    subdir: str = Field(default="", description="Subdirectory within each run folder")


class HpcCompareCaseFilesRequest(BaseModel):
    host: str
    user: str
    password: str = ""
    session_token: str = ""
    reeds_path: str
    case: str
    subdir: str = ""


class HpcCompareDataRequest(BaseModel):
    host: str
    user: str
    password: str = ""
    session_token: str = ""
    reeds_path: str
    cases: list[str] = Field(..., min_length=2, max_length=20)
    filename: str = Field(default="")
    filenames: dict[str, str] | None = None
    subdir: str = Field(default="outputs")
    max_rows_per_case: int = Field(default=5000, ge=100, le=50000)


def _hpc_list_dir(host: str, user: str, password: str,
                  remote_dir: str) -> list[dict]:
    """Return [{name, is_dir, size}] for one remote directory via SSH ls."""
    # Use printf-like find to get name|type|size in one round trip.
    cmd = (
        f"cd {shlex.quote(remote_dir)} 2>/dev/null && "
        "find . -mindepth 1 -maxdepth 1 "
        r'-printf "%f|%y|%s\n" 2>/dev/null'
    )
    try:
        out = _ssh_exec(host, user, cmd, password=password, timeout=30)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"SSH ls failed: {exc}")
    skip = {"__pycache__", ".git", "node_modules"}
    entries: list[dict] = []
    for line in out.splitlines():
        parts = line.split("|", 2)
        if len(parts) != 3:
            continue
        name, t, size_s = parts
        if not name or name.startswith(".") or name in skip:
            continue
        is_dir = (t == "d")
        try:
            size = int(size_s) if not is_dir else None
        except ValueError:
            size = None
        entries.append({"name": name, "is_dir": is_dir, "size": size})
    return entries


@router.post("/hpc/compare/common-files")
def hpc_compare_common_files(req: HpcCompareBrowseRequest):
    """List common entries across multiple HPC run-folder subdirs."""
    host, user, password = _resolve_creds(req.session_token, req.host, req.user, req.password)
    for c in req.cases:
        if not _HPC_SAFE_NAME_RE.match(c):
            raise HTTPException(status_code=400, detail=f"Unsafe case name: {c}")
    reeds_path = req.reeds_path.rstrip("/")
    runs_dir = f"{reeds_path}/runs"
    sub = req.subdir.strip("/")

    per_case: list[dict[str, dict]] = []
    for case in req.cases:
        target = f"{runs_dir}/{case}/{sub}" if sub else f"{runs_dir}/{case}"
        listing = _hpc_list_dir(host, user, password, target)
        per_case.append({e["name"]: e for e in listing})

    common = set(per_case[0].keys())
    for pc in per_case[1:]:
        common &= set(pc.keys())

    result = []
    for name in sorted(common):
        info = per_case[0][name]
        result.append({"name": name, "is_dir": info["is_dir"], "size": info["size"]})
    return {"subdir": req.subdir, "entries": result}


@router.post("/hpc/compare/case-files")
def hpc_compare_case_files(req: HpcCompareCaseFilesRequest):
    """List one case's files at a given subdirectory level on the HPC."""
    host, user, password = _resolve_creds(req.session_token, req.host, req.user, req.password)
    if not _HPC_SAFE_NAME_RE.match(req.case):
        raise HTTPException(status_code=400, detail=f"Unsafe case name: {req.case}")
    reeds_path = req.reeds_path.rstrip("/")
    sub = req.subdir.strip("/")
    target = f"{reeds_path}/runs/{req.case}/{sub}" if sub else f"{reeds_path}/runs/{req.case}"
    entries = _hpc_list_dir(host, user, password, target)
    entries.sort(key=lambda e: e["name"].lower())
    return {"case": req.case, "subdir": req.subdir, "entries": entries}


@router.post("/hpc/compare/data")
def hpc_compare_data(req: HpcCompareDataRequest):
    """Compare a file across HPC runs.

    Downloads each case's file via SFTP into the local cache, then runs the
    same comparison logic used by the local Outputs Explorer.
    """
    from .runs import compare_files_core  # local import to avoid circular import

    host, user, password = _resolve_creds(req.session_token, req.host, req.user, req.password)

    case_filenames: dict[str, str] = {}
    if req.filenames:
        for case in req.cases:
            fn = req.filenames.get(case)
            if not fn or not _HPC_SAFE_NAME_RE.match(fn):
                raise HTTPException(status_code=400, detail=f"Invalid filename for {case}")
            case_filenames[case] = fn
    else:
        if not req.filename or not _HPC_SAFE_NAME_RE.match(req.filename):
            raise HTTPException(status_code=400, detail="Invalid filename")
        for case in req.cases:
            case_filenames[case] = req.filename

    for c in req.cases:
        if not _HPC_SAFE_NAME_RE.match(c):
            raise HTTPException(status_code=400, detail=f"Unsafe case name: {c}")

    reeds_path = req.reeds_path.rstrip("/")
    sub = req.subdir.strip("/")
    display_filename = case_filenames[req.cases[0]]

    # Download each case's file to local cache and remember the remote path
    # (used by the image branch to build HPC raw URLs in the response).
    local_paths: dict[str, Path] = {}
    remote_paths: dict[str, str] = {}
    for case in req.cases:
        fn = case_filenames[case]
        rp = f"{reeds_path}/runs/{case}/{sub}/{fn}" if sub else f"{reeds_path}/runs/{case}/{fn}"
        remote_paths[case] = rp
        local_paths[case] = _hpc_download_to_cache(host, user, password, rp)

    # For HPC images, the frontend uses /files/hpc/raw with the remote path.
    def _image_url(case: str, _p: Path) -> str:
        return remote_paths[case]

    return compare_files_core(
        paths=local_paths,
        cases=list(req.cases),
        display_filename=display_filename,
        subdir=req.subdir,
        max_rows_per_case=req.max_rows_per_case,
        image_url_builder=_image_url,
    )
