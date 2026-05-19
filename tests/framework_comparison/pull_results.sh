#!/usr/bin/env bash
# Pull framework comparison JSON results from a Torc run and emit CSV to stdout.
#
# Works in two modes:
#   local   Read from a local Torc run directory (default when no --host given)
#   remote  SSH to HPC and read from the remote Torc runs directory
#
# Usage:
#   # Local mode – reads the latest run under TORC_RUNS_BASE
#   ./pull_results.sh
#
#   # Override the runs base dir
#   TORC_RUNS_BASE=/scratch/psanchez/torc-runs ./pull_results.sh
#
#   # Remote mode – SSH to Kestrel
#   ./pull_results.sh --host psanchez@kestrel.hpc.nrel.gov
#
#   # Remote mode with custom runs base
#   TORC_RUNS_BASE=/scratch/other/torc-runs \
#     ./pull_results.sh --host psanchez@kestrel.hpc.nrel.gov
#
#   # Explicit run directory (local)
#   ./pull_results.sh --run-dir /scratch/psanchez/torc-runs/framework-matrix-20260519
#
# Options:
#   --host HOST           SSH host for remote mode (triggers remote mode)
#   --runs-base PATH      Torc runs base dir  (default: /scratch/$USER/torc-runs)
#   --results-relpath P   Relative path inside each run to JSON results
#                         (default: src/tests/framework_comparison/torc_output_matrix/framework_results)
#   --run-dir PATH        Explicit run dir (skips auto-detect; local mode only)
#   --json-glob GLOB      JSON file glob (default: *.json)
#   -h, --help            Print this help and exit
#
# Output (CSV to stdout):
#   results_file,label,module,solver,size,status,total_s,solve_s,build_s,objective,error
set -euo pipefail

RUNS_BASE="${TORC_RUNS_BASE:-/scratch/${USER}/torc-runs}"
RESULTS_RELPATH="${TORC_RESULTS_RELPATH:-src/tests/framework_comparison/torc_output_matrix/framework_results}"
JSON_GLOB="${TORC_RESULTS_GLOB:-*.json}"
SSH_HOST=""
RUN_DIR=""

log()  { printf '[pull-results] %s\n' "$*" >&2; }
die()  { printf '[pull-results] ERROR: %s\n' "$*" >&2; exit 1; }

usage() {
  sed -n '2,/^set -/p' "$0" | grep '^#' | sed 's/^# \?//'
}

# --- Parse args ---------------------------------------------------------------
while (($#)); do
  case "$1" in
    --host)
      SSH_HOST="${2:?missing value for --host}"
      shift 2
      ;;
    --runs-base)
      RUNS_BASE="${2:?missing value for --runs-base}"
      shift 2
      ;;
    --results-relpath)
      RESULTS_RELPATH="${2:?missing value for --results-relpath}"
      shift 2
      ;;
    --run-dir)
      RUN_DIR="${2:?missing value for --run-dir}"
      shift 2
      ;;
    --json-glob)
      JSON_GLOB="${2:?missing value for --json-glob}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      die "Unknown option: $1"
      ;;
  esac
done

# --- JQ check -----------------------------------------------------------------
check_jq() {
  if ! command -v jq >/dev/null 2>&1; then
    echo "jq is required to parse JSON results" >&2
    exit 1
  fi
}

# --- JQ extraction logic (inlined for both local and heredoc remote) ----------
JQ_SCRIPT='
  def s(v): if v == null then "" else (v | tostring) end;
  def clean_error: gsub("\\s+"; " ") | .[0:160] | gsub(","; ";");
  (.error // "" | tostring) as $error
  | [
      $results_file,
      s(.label),
      s(.module),
      s(.solver),
      s(.size),
      (if ($error | length) > 0 then "failed" else "ok" end),
      s(.total_s),
      s(.solve_s),
      s(.build_s),
      s(.objective),
      ($error | clean_error)
    ]
  | @csv
'

CSV_HEADER='results_file,label,module,solver,size,status,total_s,solve_s,build_s,objective,error'

# =============================================================================
# REMOTE MODE
# =============================================================================
if [[ -n "${SSH_HOST}" ]]; then
  log "Remote mode: ${SSH_HOST}"
  # shellcheck disable=SC2087
  ssh -o BatchMode=yes "${SSH_HOST}" \
    RUNS_BASE="${RUNS_BASE}" \
    RESULTS_RELPATH="${RESULTS_RELPATH}" \
    JSON_GLOB="${JSON_GLOB}" \
    bash -s <<'REMOTE'
set -euo pipefail
check_jq() { command -v jq >/dev/null 2>&1 || { echo "jq required on remote" >&2; exit 1; }; }
check_jq

latest_run=""
while IFS= read -r run_dir; do
  if [[ -d "${run_dir}/${RESULTS_RELPATH}" ]]; then
    latest_run="${run_dir}"
    break
  fi
done < <(
  find "${RUNS_BASE}" -mindepth 1 -maxdepth 1 -type d -printf '%T@ %p\n' \
    | sort -nr | cut -d' ' -f2-
)

if [[ -z "${latest_run}" ]]; then
  echo "No run found under: ${RUNS_BASE}" >&2; exit 1
fi

results_dir="${latest_run}/${RESULTS_RELPATH}"
echo "RUN=${latest_run}" >&2

shopt -s nullglob
files=("${results_dir}"/${JSON_GLOB})
if (( ${#files[@]} == 0 )); then
  echo "No files matching '${JSON_GLOB}' under: ${results_dir}" >&2; exit 1
fi

printf '%s\n' 'results_file,label,module,solver,size,status,total_s,solve_s,build_s,objective,error'
for file in "${files[@]}"; do
  jq -r --arg results_file "$(basename "${file}")" '
    def s(v): if v == null then "" else (v | tostring) end;
    def clean_error: gsub("\\s+"; " ") | .[0:160] | gsub(","; ";");
    (.error // "" | tostring) as $error
    | [$results_file,s(.label),s(.module),s(.solver),s(.size),
       (if ($error|length)>0 then "failed" else "ok" end),
       s(.total_s),s(.solve_s),s(.build_s),s(.objective),($error|clean_error)]
    | @csv
  ' "${file}"
done
REMOTE
  exit 0
fi

# =============================================================================
# LOCAL MODE
# =============================================================================
check_jq

# Determine results directory
if [[ -n "${RUN_DIR}" ]]; then
  results_dir="${RUN_DIR%/}/${RESULTS_RELPATH}"
  if [[ ! -d "${results_dir}" ]]; then
    # Maybe the user passed the results dir directly
    if [[ -d "${RUN_DIR}" ]]; then
      results_dir="${RUN_DIR}"
    else
      die "Results directory not found: ${results_dir}"
    fi
  fi
  log "Using explicit run dir: ${RUN_DIR}"
else
  latest_run=""
  while IFS= read -r run_dir; do
    if [[ -d "${run_dir}/${RESULTS_RELPATH}" ]]; then
      latest_run="${run_dir}"
      break
    fi
  done < <(
    find "${RUNS_BASE}" -mindepth 1 -maxdepth 1 -type d -printf '%T@ %p\n' \
      2>/dev/null | sort -nr | cut -d' ' -f2-
  )

  if [[ -z "${latest_run}" ]]; then
    die "No run found with '${RESULTS_RELPATH}' under: ${RUNS_BASE}"
  fi
  results_dir="${latest_run}/${RESULTS_RELPATH}"
  log "Latest run: ${latest_run}"
fi

shopt -s nullglob
files=("${results_dir}"/${JSON_GLOB})
if (( ${#files[@]} == 0 )); then
  die "No files matching '${JSON_GLOB}' under: ${results_dir}"
fi

printf '%s\n' "${CSV_HEADER}"
for file in "${files[@]}"; do
  jq -r --arg results_file "$(basename "${file}")" "${JQ_SCRIPT}" "${file}"
done
