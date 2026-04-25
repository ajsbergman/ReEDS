"""ReEDS run manager – launch, monitor, and stop model runs."""
from __future__ import annotations

import json
import logging
import os
import signal
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


class RunStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class RunRecord:
    id: str
    batch_name: str
    cases_suffix: str
    cases: list[str]
    simult_runs: int
    target: str  # "local" or "hpc"
    status: RunStatus
    created_at: float
    pid: int | None = None
    log_tail: str = ""
    finished_at: float | None = None
    error: str | None = None
    extra_args: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["status"] = self.status.value
        return d


# ── In‑memory registry (one per process) ────────────────────────────────────
_runs: dict[str, RunRecord] = {}
_run_lock = threading.Lock()


def _persist_run(repo_root: Path, rec: RunRecord):
    """Save run metadata to a JSON file so the UI can reload after restart."""
    run_dir = repo_root / "reeds_copilot" / "run_history"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / f"{rec.id}.json").write_text(
        json.dumps(rec.to_dict(), indent=2), encoding="utf-8"
    )


def _load_persisted_runs(repo_root: Path):
    """Load previously persisted runs into memory (once on startup)."""
    run_dir = repo_root / "reeds_copilot" / "run_history"
    if not run_dir.exists():
        return
    for p in run_dir.glob("*.json"):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            rid = data["id"]
            if rid not in _runs:
                data["status"] = RunStatus(data["status"])
                _runs[rid] = RunRecord(**data)
        except Exception:
            log.warning("Skipping corrupt run record %s", p.name)


# ── Public API ───────────────────────────────────────────────────────────────

def list_conda_envs() -> list[dict]:
    """Return available conda environments."""
    try:
        result = subprocess.run(
            ["conda", "env", "list", "--json"],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode != 0:
            return []
        import json as _json
        data = _json.loads(result.stdout)
        envs = []
        for p in data.get("envs", []):
            name = Path(p).name
            envs.append({"name": name, "path": p})
        return envs
    except Exception:
        return []

def list_cases_files(repo_root: Path) -> list[dict]:
    """Return available cases_*.csv files with their case names."""
    results = []
    for p in sorted(repo_root.glob("cases*.csv")):
        suffix = p.stem.replace("cases_", "").replace("cases", "")
        # Read first row to get case column names
        try:
            import csv
            with open(p, newline="", encoding="utf-8") as f:
                reader = csv.reader(f)
                header = next(reader, [])
            case_names = [h for h in header[1:] if h.strip()]
        except Exception:
            case_names = []
        results.append({
            "filename": p.name,
            "suffix": suffix,
            "cases": case_names,
        })
    return results


def get_case_details(repo_root: Path, suffix: str) -> dict:
    """Read a cases CSV and return structured switch information."""
    fname = f"cases_{suffix}.csv" if suffix else "cases.csv"
    p = repo_root / fname
    if not p.exists():
        return {"error": f"{fname} not found"}

    import csv
    with open(p, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        rows = list(reader)

    if not rows:
        return {"error": "Empty file"}

    header = rows[0]
    case_names = [h for h in header[1:] if h.strip()]
    switches: list[dict] = []
    for row in rows[1:]:
        if not row or not row[0].strip():
            continue
        name = row[0].strip()
        values = {}
        for i, case in enumerate(case_names):
            val = row[i + 1].strip() if i + 1 < len(row) else ""
            values[case] = val
        switches.append({"switch": name, "values": values})

    return {"filename": fname, "cases": case_names, "switches": switches}


def _find_conda_python(env_name: str) -> str | None:
    """Locate the Python executable for a conda environment (no shell activation needed)."""
    try:
        result = subprocess.run(
            ["conda", "env", "list", "--json"],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode != 0:
            return None
        data = json.loads(result.stdout)
        for p in data.get("envs", []):
            if Path(p).name == env_name:
                if os.name == "nt":
                    py = Path(p) / "python.exe"
                else:
                    py = Path(p) / "bin" / "python"
                if py.exists():
                    return str(py)
    except Exception:
        pass
    return None


def start_local_run(
    repo_root: Path,
    batch_name: str,
    cases_suffix: str,
    cases: list[str] | None = None,
    simult_runs: int = 1,
    conda_env: str = "reeds2",
    overwrite: bool = False,
    extra_args: dict[str, Any] | None = None,
) -> RunRecord:
    """Start a local ReEDS run via runbatch.py."""
    rid = uuid.uuid4().hex[:12]
    rec = RunRecord(
        id=rid,
        batch_name=batch_name,
        cases_suffix=cases_suffix,
        cases=cases or [],
        simult_runs=simult_runs,
        target="local",
        status=RunStatus.QUEUED,
        created_at=time.time(),
        extra_args=extra_args or {},
    )

    with _run_lock:
        _runs[rid] = rec

    # Build the runbatch.py invocation arguments
    py_args = [
        str(repo_root / "runbatch.py"),
        f"--BatchName={batch_name}",
        f"--simult_runs={simult_runs}",
        "--forcelocal",
        "--skip_checks",
    ]
    if cases_suffix:
        py_args.append(f"--cases_suffix={cases_suffix}")
    if cases:
        # --single expects a comma-delimited string of case names
        py_args.append(f"--single={','.join(cases)}")

    # Find the conda env's Python executable so we don't need shell activation
    conda_python = _find_conda_python(conda_env)

    if conda_python:
        # Direct invocation — no shell needed, avoids quoting issues
        cmd = [conda_python] + py_args
    elif os.name == "nt":
        # Fallback: use cmd /c with conda activate
        inner = f"conda activate {conda_env} && python " + subprocess.list2cmdline(py_args)
        cmd = ["cmd", "/c", inner]
    else:
        cmd = ["conda", "run", "--no-capture-output", "-n", conda_env, "python"] + py_args

    # Delete existing run folders if overwrite requested
    if overwrite and cases:
        import shutil as _shutil
        for c in cases:
            d = repo_root / "runs" / f"{batch_name}_{c}"
            if d.is_dir():
                log.info("Overwrite: deleting existing folder %s", d)
                _shutil.rmtree(d)

    # On Windows, force keep_run_terminal=1 so the GAMS cmd window stays open
    # after completion (makes it easy to see errors).  We temporarily append
    # the switch to the user's cases CSV; runbatch merges cases_<suffix>.csv
    # with cases.csv defaults, so a row here overrides the default of 0.
    _cases_file_backup: tuple[Path, str] | None = None
    if os.name == "nt":
        _suffix = cases_suffix
        _cf = repo_root / (f"cases_{_suffix}.csv" if _suffix else "cases.csv")
        if _cf.exists():
            try:
                _orig = _cf.read_text(encoding="utf-8")
                if "keep_run_terminal" not in _orig:
                    # Read header to determine column count
                    first_line = _orig.split("\n", 1)[0]
                    ncols = len(first_line.split(","))
                    # Build row: keep_run_terminal,1,1,1,... (all cases get 1)
                    row = "keep_run_terminal" + ",1" * (ncols - 1)
                    _cf.write_text(_orig.rstrip("\n") + "\n" + row + "\n", encoding="utf-8")
                    _cases_file_backup = (_cf, _orig)
                    log.info("Injected keep_run_terminal=1 into %s", _cf.name)
            except Exception as exc:
                log.warning("Failed to inject keep_run_terminal: %s", exc)

    log.info("Launching local run %s: %s", rid, cmd)

    def _tail_log_file(log_path: Path, n: int = 100) -> str:
        """Read the last n lines of a log file if it exists."""
        if not log_path.exists():
            return ""
        try:
            text = log_path.read_text(encoding="utf-8", errors="replace")
            return "\n".join(text.splitlines()[-n:])
        except Exception:
            return ""

    def _is_run_finished(case_dir: Path) -> bool:
        """A run is finished when report.xlsx exists (same logic as runstatus.py)."""
        return (case_dir / "outputs" / "reeds-report" / "report.xlsx").exists()

    def _is_run_failed(case_dir: Path) -> bool:
        """A run has failed if the folder exists but there's no report.xlsx
        and the process has exited."""
        if not case_dir.is_dir():
            return False
        # Check meta.csv for an 'end' row without a completed report
        meta = case_dir / "meta.csv"
        if meta.exists():
            try:
                lines = meta.read_text(encoding="utf-8", errors="replace").splitlines()
                for line in lines:
                    if line.startswith("0,end,"):
                        return True  # runbatch wrote 'end' but no report.xlsx
            except Exception:
                pass
        return False

    def _build_log_tail(case_dirs: list[Path]) -> str:
        """Build a combined log tail from gamslog.txt and latest lst files."""
        log_parts: list[str] = []
        for cd in case_dirs:
            if not cd.is_dir():
                continue
            glog = cd / "gamslog.txt"
            if glog.exists():
                log_parts.append(
                    f"── {cd.name}/gamslog.txt ──\n"
                    + _tail_log_file(glog, 50)
                )
            # Latest .lst file (GAMS solve progress)
            lstdir = cd / "lstfiles"
            if lstdir.is_dir():
                lst_files = sorted(
                    [f for f in lstdir.glob("*.lst")],
                    key=lambda p: p.stat().st_mtime,
                    reverse=True,
                )
                if lst_files:
                    log_parts.append(
                        f"── {lst_files[0].name} (latest) ──\n"
                        + _tail_log_file(lst_files[0], 30)
                    )
        return "\n".join(log_parts)

    def _run_in_thread():
        try:
            rec.status = RunStatus.RUNNING
            _persist_run(repo_root, rec)

            # Run runbatch.py with its own console window so that
            # `os.system('start /wait cmd /c ...')` inside runbatch can
            # properly open and wait for the GAMS cmd window.
            # CREATE_NEW_CONSOLE gives it a real console session.
            proc = subprocess.Popen(
                cmd,
                cwd=str(repo_root),
                creationflags=subprocess.CREATE_NEW_CONSOLE
                if os.name == "nt"
                else 0,
            )
            rec.pid = proc.pid
            _persist_run(repo_root, rec)

            # Monitor progress by tailing log files from run folder
            case_dirs = [
                repo_root / "runs" / f"{batch_name}_{c}"
                for c in (cases or [])
            ]

            # Phase 1: Wait for runbatch.py to exit
            while proc.poll() is None:
                tail = _build_log_tail(case_dirs)
                if tail:
                    rec.log_tail = tail
                time.sleep(5)

            # Restore cases CSV after runbatch has read it
            if _cases_file_backup is not None:
                try:
                    _cases_file_backup[0].write_text(
                        _cases_file_backup[1], encoding="utf-8"
                    )
                    log.info("Restored %s", _cases_file_backup[0].name)
                except Exception:
                    pass

            # Phase 2: runbatch.py exited, but on Windows the actual GAMS run
            # continues in a separate cmd window launched via
            # `os.system('start /wait cmd /c ...')`.
            # Keep monitoring until GAMS finishes (report.xlsx appears,
            # or gamslog.txt stops being updated for a while).
            if os.name == "nt" and case_dirs:
                log.info("runbatch exited (code %s), monitoring GAMS in background...", proc.returncode)
                stale_count = 0
                last_sizes = {cd: 0 for cd in case_dirs}
                while stale_count < 12:  # 12 x 10s = 2 min of no activity → done
                    time.sleep(10)
                    # Check if all cases have report.xlsx → done
                    if all(_is_run_finished(cd) for cd in case_dirs):
                        break
                    # Check if log files are still being written to
                    any_activity = False
                    for cd in case_dirs:
                        glog = cd / "gamslog.txt"
                        if glog.exists():
                            sz = glog.stat().st_size
                            if sz != last_sizes.get(cd, 0):
                                last_sizes[cd] = sz
                                any_activity = True
                        # Also check lstfiles
                        lstdir = cd / "lstfiles"
                        if lstdir.is_dir():
                            for f in lstdir.glob("*.lst"):
                                sz = f.stat().st_size
                                key = f
                                if sz != last_sizes.get(key, 0):
                                    last_sizes[key] = sz
                                    any_activity = True
                    if any_activity:
                        stale_count = 0
                    else:
                        stale_count += 1
                    # Update displayed log
                    tail = _build_log_tail(case_dirs)
                    if tail:
                        rec.log_tail = tail
                    _persist_run(repo_root, rec)

            # Final state
            rec.finished_at = time.time()
            rec.log_tail = _build_log_tail(case_dirs)

            # Determine final status using runstatus.py logic:
            # finished = report.xlsx exists for ALL cases
            all_finished = all(_is_run_finished(cd) for cd in case_dirs) if case_dirs else False

            if all_finished:
                rec.status = RunStatus.COMPLETED
            else:
                rec.status = RunStatus.FAILED
                failed_cases = [cd.name for cd in case_dirs
                                if not _is_run_finished(cd)]
                rec.error = f"Cases did not produce report.xlsx: {', '.join(failed_cases)}"
        except Exception as exc:
            rec.status = RunStatus.FAILED
            rec.error = str(exc)
            rec.finished_at = time.time()
        finally:
            rec.pid = None
            _persist_run(repo_root, rec)

    t = threading.Thread(target=_run_in_thread, daemon=True)
    t.start()
    return rec


def cancel_run(repo_root: Path, run_id: str) -> bool:
    """Cancel a running process."""
    rec = _runs.get(run_id)
    if not rec or not rec.pid:
        return False
    try:
        if os.name == "nt":
            subprocess.call(
                ["taskkill", "/F", "/T", "/PID", str(rec.pid)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        else:
            os.killpg(os.getpgid(rec.pid), signal.SIGTERM)
        rec.status = RunStatus.CANCELLED
        rec.finished_at = time.time()
        rec.pid = None
        _persist_run(repo_root, rec)
        return True
    except Exception as exc:
        log.warning("Failed to cancel run %s: %s", run_id, exc)
        return False


def cancel_all_local(repo_root: Path) -> int:
    """Cancel all running LOCAL runs. Returns the number of runs cancelled."""
    count = 0
    with _run_lock:
        for rec in _runs.values():
            if rec.status == RunStatus.RUNNING and rec.target == "local" and rec.pid:
                try:
                    if os.name == "nt":
                        subprocess.call(
                            ["taskkill", "/F", "/T", "/PID", str(rec.pid)],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                        )
                    else:
                        os.killpg(os.getpgid(rec.pid), signal.SIGTERM)
                    rec.status = RunStatus.CANCELLED
                    rec.finished_at = time.time()
                    rec.pid = None
                    _persist_run(repo_root, rec)
                    count += 1
                except Exception as exc:
                    log.warning("Failed to cancel run %s: %s", rec.id, exc)
    log.info("cancel_all_local: cancelled %d runs", count)
    return count


def list_runs() -> list[dict]:
    """Return all known runs (newest first)."""
    with _run_lock:
        return [r.to_dict() for r in sorted(_runs.values(), key=lambda r: r.created_at, reverse=True)]


def get_run(run_id: str) -> dict | None:
    rec = _runs.get(run_id)
    return rec.to_dict() if rec else None


def delete_run(repo_root: Path, run_id: str) -> bool:
    """Remove a run record (only if not running)."""
    with _run_lock:
        rec = _runs.get(run_id)
        if not rec:
            return False
        if rec.status == RunStatus.RUNNING:
            return False
        del _runs[run_id]
    p = repo_root / "reeds_copilot" / "run_history" / f"{run_id}.json"
    p.unlink(missing_ok=True)
    return True


def init_run_manager(repo_root: Path):
    """Call once on app startup to reload persisted runs."""
    _load_persisted_runs(repo_root)


def list_run_folders(repo_root: Path) -> list[dict]:
    """Scan {repo}/runs/ directory and return info about each run folder."""
    runs_dir = repo_root / "runs"
    if not runs_dir.is_dir():
        return []
    results = []
    for d in sorted(runs_dir.iterdir(), reverse=True):
        if not d.is_dir():
            continue
        # Check for key files to infer status (same logic as runstatus.py)
        report = d / "outputs" / "reeds-report" / "report.xlsx"
        has_report = report.exists()
        has_outputs = (d / "outputs").is_dir()
        has_gamslog = (d / "gamslog.txt").is_file()
        has_meta = (d / "meta.csv").is_file()
        # Get modification time
        try:
            mtime = d.stat().st_mtime
        except Exception:
            mtime = 0
        results.append({
            "name": d.name,
            "path": str(d),
            "has_report": has_report,
            "has_outputs": has_outputs,
            "has_gamslog": has_gamslog,
            "has_meta": has_meta,
            "modified_at": mtime,
        })
    return results
