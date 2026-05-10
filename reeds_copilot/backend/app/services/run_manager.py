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
import re
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_SAFE_ENV_NAME = re.compile(r'^[a-zA-Z0-9_][a-zA-Z0-9_.\\-]{0,63}$')


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
    slurm_job_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["status"] = self.status.value
        # Never expose password in API responses
        if "extra_args" in d and "hpc_password" in d.get("extra_args", {}):
            d["extra_args"] = {
                k: v for k, v in d["extra_args"].items()
                if k != "hpc_password"
            }
        return d


# ── In‑memory registry (one per process) ────────────────────────────────────
_runs: dict[str, RunRecord] = {}
_run_lock = threading.Lock()


def _persist_run(repo_root: Path, rec: RunRecord):
    """Save run metadata to a JSON file so the UI can reload after restart.
    SECURITY: Never persist passwords/secrets to disk."""
    run_dir = repo_root / "reeds_copilot" / "run_history"
    run_dir.mkdir(parents=True, exist_ok=True)
    data = rec.to_dict()
    # Strip any sensitive fields before writing to disk
    if "extra_args" in data:
        data["extra_args"] = {
            k: v for k, v in data["extra_args"].items()
            if k != "hpc_password"
        }
    (run_dir / f"{rec.id}.json").write_text(
        json.dumps(data, indent=2), encoding="utf-8"
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
                # Ensure backwards compatibility with records before HPC support
                data.setdefault("slurm_job_ids", [])
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
    if not _SAFE_ENV_NAME.match(conda_env):
        raise ValueError(f"Invalid conda environment name: {conda_env!r}")
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

    # On Windows we MUST use `conda activate` so that the environment is
    # inherited by child cmd windows that runbatch.py opens via
    # `os.system('start /wait cmd /k call_*.bat')`.
    # Using the direct python.exe path only activates it for runbatch itself,
    # not for the spawned GAMS run windows.
    if os.name == "nt":
        args_str = subprocess.list2cmdline(py_args)
        inner = f"conda activate {conda_env} && python {args_str}"
        cmd = ["cmd", "/c", inner]
    else:
        conda_python = _find_conda_python(conda_env)
        if conda_python:
            cmd = [conda_python] + py_args
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

            # Phase 2: runbatch.py exited, but on Windows the actual GAMS run
            # continues in a separate cmd window launched via
            # `os.system('start /wait cmd /c ...')`.
            # Keep monitoring until GAMS finishes (report.xlsx appears,
            # or gamslog.txt stops being updated for a while).
            if os.name == "nt" and case_dirs:
                log.info("runbatch exited (code %s), monitoring GAMS in background...", proc.returncode)
                stale_count = 0
                last_sizes = {cd: 0 for cd in case_dirs}
                last_check_time = time.time()
                while stale_count < 36:  # 36 x 10s = 6 min of no activity → done
                    time.sleep(10)

                    # Detect system sleep: if the wall-clock jump is much larger
                    # than 10s, the machine was asleep – reset stale counter.
                    now = time.time()
                    elapsed = now - last_check_time
                    last_check_time = now
                    if elapsed > 30:  # slept for > 30s → ignore this cycle
                        log.info("Detected system sleep (%.0fs gap), resetting stale counter", elapsed)
                        stale_count = 0
                        continue

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


# ── HPC / Slurm support (via SSH / paramiko) ─────────────────────────────────

import paramiko

_SAFE_SSH_RE = re.compile(r'^[a-zA-Z0-9._\-]+$')

# Reuse the SSH connection pool from the files module so the file browser and
# run manager share authenticated sessions.
from ..api.files import _get_ssh_client, _ssh_pool, _ssh_lock


def _ssh_run(
    hpc_host: str,
    hpc_user: str,
    command: str,
    timeout: int = 60,
    password: str = "",
) -> subprocess.CompletedProcess:
    """Run a command on a remote HPC node via paramiko.

    Returns a subprocess.CompletedProcess-like object for backwards compat.
    Supports password auth via the shared paramiko connection pool.
    """
    if not _SAFE_SSH_RE.match(hpc_host):
        raise ValueError(f"Invalid SSH hostname: {hpc_host!r}")
    if not _SAFE_SSH_RE.match(hpc_user):
        raise ValueError(f"Invalid SSH username: {hpc_user!r}")

    client = _get_ssh_client(hpc_host, hpc_user, password)
    try:
        _, stdout, stderr = client.exec_command(command, timeout=timeout)
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        rc = stdout.channel.recv_exit_status()
    except Exception as exc:
        # Connection may have died — evict from pool
        with _ssh_lock:
            _ssh_pool.pop((hpc_host, hpc_user), None)
        raise exc

    return subprocess.CompletedProcess(
        args=command, returncode=rc, stdout=out, stderr=err,
    )


def _check_ssh_connection(hpc_host: str, hpc_user: str, password: str = "") -> bool:
    """Verify we can SSH to the login node."""
    try:
        proc = _ssh_run(hpc_host, hpc_user, "echo OK", timeout=20, password=password)
        return proc.returncode == 0 and "OK" in proc.stdout
    except Exception:
        return False


def _parse_slurm_job_ids(output: str) -> list[str]:
    """Extract Slurm job IDs from sbatch output.
    sbatch typically prints 'Submitted batch job 12345'."""
    ids = []
    for line in output.splitlines():
        m = re.search(r'Submitted batch job\s+(\d+)', line)
        if m:
            ids.append(m.group(1))
    return ids


def _query_slurm_status_ssh(
    hpc_host: str, hpc_user: str, job_ids: list[str],
    password: str = "",
) -> dict[str, str]:
    """Query sacct/squeue via SSH for job states. Returns {job_id: state}."""
    if not job_ids:
        return {}
    result = {}
    try:
        proc = _ssh_run(
            hpc_host, hpc_user,
            f"sacct -j {','.join(job_ids)} --format=JobID,State --noheader --parsable2",
            timeout=30, password=password,
        )
        if proc.returncode == 0:
            for line in proc.stdout.strip().splitlines():
                parts = line.split("|")
                if len(parts) >= 2:
                    jid = parts[0].strip()
                    state = parts[1].strip()
                    if "." not in jid and jid in job_ids:
                        result[jid] = state
    except Exception:
        pass

    missing = [j for j in job_ids if j not in result]
    if missing:
        try:
            proc = _ssh_run(
                hpc_host, hpc_user,
                f"squeue -j {','.join(missing)} --format='%i %T' --noheader",
                timeout=30, password=password,
            )
            if proc.returncode == 0:
                for line in proc.stdout.strip().splitlines():
                    parts = line.split()
                    if len(parts) >= 2:
                        result[parts[0]] = parts[1]
        except Exception:
            pass

    return result


def _tail_slurm_logs_ssh(
    hpc_host: str, hpc_user: str,
    hpc_reeds_path: str, batch_name: str, cases: list[str],
    n: int = 50, password: str = "",
) -> str:
    """Read recent slurm-*.out and gamslog.txt via SSH."""
    # Build a remote shell command that tails the relevant log files
    runs_dir = f"{hpc_reeds_path}/runs"
    cmd_parts = []

    # Per-case logs
    for c in cases:
        case_dir = f"{runs_dir}/{batch_name}_{c}"
        cmd_parts.append(
            f'for f in $(ls -t {case_dir}/slurm-*.out 2>/dev/null | head -1); do '
            f'echo "── {batch_name}_{c}/$(basename $f) ──"; tail -n {n} "$f"; done'
        )
        cmd_parts.append(
            f'if [ -f {case_dir}/gamslog.txt ]; then '
            f'echo "── {batch_name}_{c}/gamslog.txt ──"; '
            f'tail -n {n} {case_dir}/gamslog.txt; fi'
        )

    # Batch-level logs
    cmd_parts.append(
        f'for f in $(ls -t {runs_dir}/{batch_name}/slurm-*.out 2>/dev/null | head -2); do '
        f'echo "── $(basename $f) ──"; tail -n {n} "$f"; done'
    )

    remote_cmd = " ; ".join(cmd_parts)
    try:
        proc = _ssh_run(hpc_host, hpc_user, remote_cmd, timeout=30, password=password)
        return proc.stdout if proc.returncode == 0 else ""
    except Exception:
        return ""


def start_hpc_run(
    repo_root: Path,
    batch_name: str,
    cases_suffix: str,
    cases: list[str] | None = None,
    simult_runs: int = 1,
    conda_env: str = "reeds2",
    overwrite: bool = False,
    hpc_host: str = "",
    hpc_user: str = "",
    hpc_password: str = "",
    hpc_reeds_path: str = "",
    slurm_account: str = "",
    slurm_walltime: str = "2-00:00:00",
    slurm_partition: str = "",
    slurm_memory: str = "246000",
    slurm_mail_user: str = "",
    slurm_mail_type: str = "",
    extra_args: dict[str, Any] | None = None,
) -> RunRecord:
    """Submit a ReEDS run to Slurm on a remote HPC cluster via SSH."""
    if not hpc_host or not hpc_user:
        raise RuntimeError("HPC host and username are required for HPC runs.")
    if not hpc_reeds_path:
        raise RuntimeError("Remote ReEDS path on the HPC is required.")

    # Validate SSH connectivity
    if not _check_ssh_connection(hpc_host, hpc_user, password=hpc_password):
        raise RuntimeError(
            f"Cannot SSH to {hpc_user}@{hpc_host}. "
            "Ensure SSH keys are configured and the login node is reachable."
        )

    if not _SAFE_ENV_NAME.match(conda_env):
        raise ValueError(f"Invalid conda environment name: {conda_env!r}")

    rid = uuid.uuid4().hex[:12]
    hpc_extra = {
        "hpc_host": hpc_host,
        "hpc_user": hpc_user,
        "hpc_password": hpc_password,
        "hpc_reeds_path": hpc_reeds_path,
        "slurm_account": slurm_account,
        "slurm_walltime": slurm_walltime,
        "slurm_partition": slurm_partition,
        "slurm_memory": slurm_memory,
        "slurm_mail_user": slurm_mail_user,
        "slurm_mail_type": slurm_mail_type,
        **(extra_args or {}),
    }
    rec = RunRecord(
        id=rid,
        batch_name=batch_name,
        cases_suffix=cases_suffix,
        cases=cases or [],
        simult_runs=simult_runs,
        target="hpc",
        status=RunStatus.QUEUED,
        created_at=time.time(),
        extra_args=hpc_extra,
    )

    with _run_lock:
        _runs[rid] = rec
    _persist_run(repo_root, rec)

    # Build the remote runbatch.py command
    cases_str = ",".join(cases) if cases else ""
    suffix_arg = f"--cases_suffix={cases_suffix}" if cases_suffix else ""
    single_arg = f"--single={cases_str}" if cases_str else ""

    # Build sed commands to patch srun_template.sh on the remote
    sed_parts = []
    if slurm_account:
        sed_parts.append(f"sed -i 's/^#SBATCH --account=.*/#SBATCH --account={slurm_account}/' srun_template.sh")
    if slurm_walltime:
        sed_parts.append(f"sed -i 's/^#SBATCH --time=.*/#SBATCH --time={slurm_walltime}/' srun_template.sh")
    if slurm_memory:
        sed_parts.append(f"sed -i 's/^#SBATCH --mem=.*/#SBATCH --mem={slurm_memory}/' srun_template.sh")
    if slurm_partition:
        sed_parts.append(
            f"sed -i '/#SBATCH --account=/a #SBATCH --partition={slurm_partition}' srun_template.sh"
        )
    if slurm_mail_user:
        sed_parts.append(
            f"sed -i '/#SBATCH --account=/a #SBATCH --mail-user={slurm_mail_user}' srun_template.sh"
        )
    if slurm_mail_type:
        sed_parts.append(
            f"sed -i '/#SBATCH --account=/a #SBATCH --mail-type={slurm_mail_type}' srun_template.sh"
        )

    # Delete old run folders if overwrite
    overwrite_cmds = []
    if overwrite and cases:
        for c in cases:
            overwrite_cmds.append(f"rm -rf {hpc_reeds_path}/runs/{batch_name}_{c}")

    # Full remote command
    remote_parts = [
        f"cd {hpc_reeds_path}",
        # Back up and patch srun_template
        "cp srun_template.sh srun_template.sh.bak",
        *sed_parts,
        *overwrite_cmds,
        # Load HPC modules and activate conda
        "module load gams",
        "module load anaconda3",
        f"conda activate {conda_env}",
        f"REEDS_USE_SLURM=1 python runbatch.py "
        f"--BatchName={batch_name} "
        f"--simult_runs={simult_runs} "
        f"--skip_checks "
        f"{suffix_arg} {single_arg}".strip(),
        # Restore srun_template
        "mv srun_template.sh.bak srun_template.sh",
    ]
    remote_cmd = " && ".join(remote_parts)

    log.info("Launching HPC run %s via SSH to %s@%s", rid, hpc_user, hpc_host)

    def _run_hpc_thread():
        try:
            rec.status = RunStatus.RUNNING
            _persist_run(repo_root, rec)

            # Submit via SSH (runbatch.py will internally call sbatch)
            proc = _ssh_run(hpc_host, hpc_user, remote_cmd, timeout=600,
                            password=hpc_password)

            combined_output = (proc.stdout or "") + "\n" + (proc.stderr or "")
            job_ids = _parse_slurm_job_ids(combined_output)

            if proc.returncode != 0 and not job_ids:
                rec.status = RunStatus.FAILED
                rec.error = (
                    f"Remote runbatch.py exited with code {proc.returncode}:\n"
                    + combined_output[-2000:]
                )
                rec.finished_at = time.time()
                _persist_run(repo_root, rec)
                return

            rec.slurm_job_ids = job_ids
            if job_ids:
                rec.log_tail = f"Submitted Slurm jobs: {', '.join(job_ids)}\n"
            else:
                rec.log_tail = "runbatch.py completed on HPC. Monitoring Slurm output...\n"
            _persist_run(repo_root, rec)

            # Monitor via SSH
            _monitor_slurm_jobs_ssh(repo_root, rec, hpc_host, hpc_user, hpc_reeds_path,
                                    password=hpc_password)

        except subprocess.TimeoutExpired:
            rec.status = RunStatus.FAILED
            rec.error = "SSH command timed out during HPC submission (10 min limit)"
            rec.finished_at = time.time()
        except Exception as exc:
            rec.status = RunStatus.FAILED
            rec.error = str(exc)
            rec.finished_at = time.time()
        finally:
            _persist_run(repo_root, rec)

    t = threading.Thread(target=_run_hpc_thread, daemon=True)
    t.start()
    return rec


def _check_report_exists_ssh(
    hpc_host: str, hpc_user: str,
    hpc_reeds_path: str, batch_name: str, cases: list[str],
    password: str = "",
) -> tuple[bool, list[str]]:
    """Check via SSH whether report.xlsx exists for all cases.
    Returns (all_done, list_of_missing_case_names)."""
    checks = []
    for c in cases:
        checks.append(
            f'[ -f {hpc_reeds_path}/runs/{batch_name}_{c}/outputs/reeds-report/report.xlsx ] '
            f'&& echo "OK:{c}" || echo "MISSING:{c}"'
        )
    try:
        proc = _ssh_run(hpc_host, hpc_user, " ; ".join(checks), timeout=30,
                        password=password)
        missing = []
        for line in proc.stdout.splitlines():
            if line.startswith("MISSING:"):
                missing.append(line.split(":", 1)[1])
        return len(missing) == 0, missing
    except Exception:
        return False, list(cases)


def _monitor_slurm_jobs_ssh(
    repo_root: Path, rec: RunRecord,
    hpc_host: str, hpc_user: str, hpc_reeds_path: str,
    password: str = "",
):
    """Poll Slurm via SSH and read remote logs until all jobs complete."""
    max_poll_time = 72 * 3600  # 72h
    start_time = time.time()
    poll_interval = 30

    while (time.time() - start_time) < max_poll_time:
        time.sleep(poll_interval)

        # Check report.xlsx on remote
        all_done, missing = _check_report_exists_ssh(
            hpc_host, hpc_user, hpc_reeds_path, rec.batch_name, rec.cases,
            password=password,
        )
        if all_done and rec.cases:
            rec.status = RunStatus.COMPLETED
            rec.finished_at = time.time()
            rec.log_tail = _tail_slurm_logs_ssh(
                hpc_host, hpc_user, hpc_reeds_path, rec.batch_name, rec.cases,
                password=password,
            )
            _persist_run(repo_root, rec)
            return

        # Check Slurm job statuses
        if rec.slurm_job_ids:
            statuses = _query_slurm_status_ssh(hpc_host, hpc_user, rec.slurm_job_ids,
                                               password=password)
            status_lines = [f"  Job {jid}: {st}" for jid, st in statuses.items()]
            log_tail = _tail_slurm_logs_ssh(
                hpc_host, hpc_user, hpc_reeds_path, rec.batch_name, rec.cases,
                password=password,
            )
            rec.log_tail = (
                "── Slurm Job Status ──\n"
                + "\n".join(status_lines)
                + "\n\n" + log_tail
            )

            terminal = {"COMPLETED", "FAILED", "CANCELLED", "TIMEOUT",
                        "OUT_OF_MEMORY", "NODE_FAIL", "PREEMPTED"}
            active = {"PENDING", "RUNNING", "CONFIGURING", "COMPLETING",
                      "SUSPENDED", "REQUEUED"}

            all_states = set(statuses.values())
            if all_states and not all_states.intersection(active):
                rec.finished_at = time.time()
                if all(s == "COMPLETED" for s in statuses.values()):
                    all_done2, missing2 = _check_report_exists_ssh(
                        hpc_host, hpc_user, hpc_reeds_path, rec.batch_name, rec.cases,
                        password=password,
                    )
                    if all_done2:
                        rec.status = RunStatus.COMPLETED
                    else:
                        rec.status = RunStatus.FAILED
                        rec.error = f"Slurm jobs completed but no report.xlsx: {', '.join(missing2)}"
                else:
                    rec.status = RunStatus.FAILED
                    failed_jobs = {jid: st for jid, st in statuses.items() if st != "COMPLETED"}
                    rec.error = f"Slurm jobs failed: {failed_jobs}"
                _persist_run(repo_root, rec)
                return
        else:
            rec.log_tail = _tail_slurm_logs_ssh(
                hpc_host, hpc_user, hpc_reeds_path, rec.batch_name, rec.cases,
                password=password,
            )

        _persist_run(repo_root, rec)

    rec.status = RunStatus.FAILED
    rec.error = "Monitoring timed out after 72 hours"
    rec.finished_at = time.time()
    _persist_run(repo_root, rec)


def cancel_hpc_run(repo_root: Path, run_id: str) -> bool:
    """Cancel Slurm jobs via SSH + scancel."""
    rec = _runs.get(run_id)
    if not rec:
        return False
    hpc_host = rec.extra_args.get("hpc_host", "")
    hpc_user = rec.extra_args.get("hpc_user", "")
    hpc_password = rec.extra_args.get("hpc_password", "")
    if not hpc_host or not hpc_user:
        return False
    cancelled = False
    for jid in rec.slurm_job_ids:
        try:
            _ssh_run(hpc_host, hpc_user, f"scancel {jid}", timeout=30,
                     password=hpc_password)
            cancelled = True
        except Exception as exc:
            log.warning("Failed to scancel job %s: %s", jid, exc)
    if cancelled or not rec.slurm_job_ids:
        rec.status = RunStatus.CANCELLED
        rec.finished_at = time.time()
        _persist_run(repo_root, rec)
    return cancelled


def cancel_run(repo_root: Path, run_id: str) -> bool:
    """Cancel a running local process."""
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
    """Call once on app startup to reload persisted runs.
    
    Runs that were 'running' or 'queued' when the backend last exited are
    re-evaluated: if their report.xlsx exists they are marked completed,
    otherwise marked failed (the monitoring thread is gone).
    """
    _load_persisted_runs(repo_root)
    # Fix stale 'running'/'queued' records from a previous backend session
    with _run_lock:
        for rec in _runs.values():
            if rec.status in (RunStatus.RUNNING, RunStatus.QUEUED):
                # Check if the run actually finished while backend was down
                case_dirs = [
                    repo_root / "runs" / f"{rec.batch_name}_{c}"
                    for c in rec.cases
                ]
                all_done = all(
                    (cd / "outputs" / "reeds-report" / "report.xlsx").exists()
                    for cd in case_dirs
                ) if case_dirs else False
                if all_done:
                    rec.status = RunStatus.COMPLETED
                    rec.finished_at = rec.finished_at or time.time()
                    log.info("Run %s completed while backend was down", rec.id)
                else:
                    rec.status = RunStatus.FAILED
                    rec.error = "Backend was restarted while this run was in progress. Check GAMS console."
                    rec.finished_at = rec.finished_at or time.time()
                    log.warning("Run %s marked failed (stale running state)", rec.id)
                rec.pid = None
                _persist_run(repo_root, rec)


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
