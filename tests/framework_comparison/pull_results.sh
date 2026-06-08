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
#   results_file,label,module,solver,size,status,total_s,solve_s,build_s,peak_mb,objective,time_limit,presolve,threads,highs_solver,highs_run_crossover,highs_load_path,xpress_lp_algorithm,allow_nonoptimal,num_variables,num_constraints,num_coefficients,highs_direct_load_path,highs_matrix_build_s,highs_run_s,xpress_matrix_build_s,xpress_run_s,solution_extract_s,fingerprint_s,arco_version,solver_runtime_available,error
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

# --- JSON parser check --------------------------------------------------------
json_python() {
  if command -v python3 >/dev/null 2>&1; then
    printf '%s\n' python3
  elif command -v python >/dev/null 2>&1; then
    printf '%s\n' python
  else
    return 1
  fi
}

check_json_parser() {
  if ! command -v jq >/dev/null 2>&1 && ! json_python >/dev/null; then
    echo "jq or python3 is required to parse JSON results" >&2
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
      s(.peak_mb // .peak_rss_mb),
      s(.objective),
      s(.run_options.time_limit),
      s(.run_options.presolve),
      s(.run_options.threads),
      s(.run_options.highs_solver),
      s(.run_options.highs_run_crossover),
      s(.run_options.highs_load_path),
      s(.run_options.xpress_lp_algorithm),
      s(.run_options.allow_nonoptimal),
      s(.solve_metadata.num_variables),
      s(.solve_metadata.num_constraints),
      s(.solve_metadata.num_coefficients),
      s(.solve_metadata.highs_direct_load_path),
      s(.solve_metadata.highs_matrix_build_s),
      s(.solve_metadata.highs_run_s),
      s(.solve_metadata.xpress_matrix_build_s),
      s(.solve_metadata.xpress_run_s),
      s(.solve_metadata.solution_extract_s),
      s(.solve_metadata.fingerprint_s),
      s(.framework_metadata.arco_version),
      s(.framework_metadata.solver_runtime_info.runtime_available),
      ($error | clean_error)
    ]
  | @csv
'

CSV_HEADER='results_file,label,module,solver,size,status,total_s,solve_s,build_s,peak_mb,objective,time_limit,presolve,threads,highs_solver,highs_run_crossover,highs_load_path,xpress_lp_algorithm,allow_nonoptimal,num_variables,num_constraints,num_coefficients,highs_direct_load_path,highs_matrix_build_s,highs_run_s,xpress_matrix_build_s,xpress_run_s,solution_extract_s,fingerprint_s,arco_version,solver_runtime_available,error'

emit_csv_row() {
  local file="$1"
  local results_file="$2"
  if command -v jq >/dev/null 2>&1; then
    jq -r --arg results_file "${results_file}" "${JQ_SCRIPT}" "${file}"
    return
  fi
  local py
  py="$(json_python)"
  "${py}" - "${file}" "${results_file}" <<'PY'
import csv
import json
import sys

path = sys.argv[1]
results_file = sys.argv[2]
with open(path, encoding="utf-8") as handle:
    payload = json.load(handle)


def get(path: str):
    value = payload
    for part in path.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def stringify(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(value).lower()
    return str(value)


error = stringify(get("error"))
clean_error = " ".join(error.split())[:160].replace(",", ";")
peak_mb = get("peak_mb")
if peak_mb is None:
    peak_mb = get("peak_rss_mb")

row = [
    results_file,
    stringify(get("label")),
    stringify(get("module")),
    stringify(get("solver")),
    stringify(get("size")),
    "failed" if error else "ok",
    stringify(get("total_s")),
    stringify(get("solve_s")),
    stringify(get("build_s")),
    stringify(peak_mb),
    stringify(get("objective")),
    stringify(get("run_options.time_limit")),
    stringify(get("run_options.presolve")),
    stringify(get("run_options.threads")),
    stringify(get("run_options.highs_solver")),
    stringify(get("run_options.highs_run_crossover")),
    stringify(get("run_options.highs_load_path")),
    stringify(get("run_options.xpress_lp_algorithm")),
    stringify(get("run_options.allow_nonoptimal")),
    stringify(get("solve_metadata.num_variables")),
    stringify(get("solve_metadata.num_constraints")),
    stringify(get("solve_metadata.num_coefficients")),
    stringify(get("solve_metadata.highs_direct_load_path")),
    stringify(get("solve_metadata.highs_matrix_build_s")),
    stringify(get("solve_metadata.highs_run_s")),
    stringify(get("solve_metadata.xpress_matrix_build_s")),
    stringify(get("solve_metadata.xpress_run_s")),
    stringify(get("solve_metadata.solution_extract_s")),
    stringify(get("solve_metadata.fingerprint_s")),
    stringify(get("framework_metadata.arco_version")),
    stringify(get("framework_metadata.solver_runtime_info.runtime_available")),
    clean_error,
]
csv.writer(sys.stdout, lineterminator="\n").writerow(row)
PY
}

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
json_python() {
  if command -v python3 >/dev/null 2>&1; then
    printf '%s\n' python3
  elif command -v python >/dev/null 2>&1; then
    printf '%s\n' python
  else
    return 1
  fi
}
check_json_parser() {
  if ! command -v jq >/dev/null 2>&1 && ! json_python >/dev/null; then
    echo "jq or python3 required on remote" >&2
    exit 1
  fi
}
emit_csv_row() {
  local file="$1"
  local results_file="$2"
  if command -v jq >/dev/null 2>&1; then
    jq -r --arg results_file "${results_file}" '
      def s(v): if v == null then "" else (v | tostring) end;
      def clean_error: gsub("\\s+"; " ") | .[0:160] | gsub(","; ";");
      (.error // "" | tostring) as $error
      | [$results_file,s(.label),s(.module),s(.solver),s(.size),
         (if ($error|length)>0 then "failed" else "ok" end),
         s(.total_s),s(.solve_s),s(.build_s),s(.peak_mb // .peak_rss_mb),s(.objective),
         s(.run_options.time_limit),s(.run_options.presolve),s(.run_options.threads),s(.run_options.highs_solver),
         s(.run_options.highs_run_crossover),s(.run_options.highs_load_path),
         s(.run_options.xpress_lp_algorithm),s(.run_options.allow_nonoptimal),
         s(.solve_metadata.num_variables),s(.solve_metadata.num_constraints),s(.solve_metadata.num_coefficients),
         s(.solve_metadata.highs_direct_load_path),s(.solve_metadata.highs_matrix_build_s),s(.solve_metadata.highs_run_s),
         s(.solve_metadata.xpress_matrix_build_s),s(.solve_metadata.xpress_run_s),
         s(.solve_metadata.solution_extract_s),s(.solve_metadata.fingerprint_s),
         s(.framework_metadata.arco_version),s(.framework_metadata.solver_runtime_info.runtime_available),
         ($error|clean_error)]
      | @csv
    ' "${file}"
    return
  fi
  local py
  py="$(json_python)"
  "${py}" - "${file}" "${results_file}" <<'PY'
import csv
import json
import sys

path = sys.argv[1]
results_file = sys.argv[2]
with open(path, encoding="utf-8") as handle:
    payload = json.load(handle)


def get(path: str):
    value = payload
    for part in path.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def stringify(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(value).lower()
    return str(value)


error = stringify(get("error"))
clean_error = " ".join(error.split())[:160].replace(",", ";")
peak_mb = get("peak_mb")
if peak_mb is None:
    peak_mb = get("peak_rss_mb")

row = [
    results_file,
    stringify(get("label")),
    stringify(get("module")),
    stringify(get("solver")),
    stringify(get("size")),
    "failed" if error else "ok",
    stringify(get("total_s")),
    stringify(get("solve_s")),
    stringify(get("build_s")),
    stringify(peak_mb),
    stringify(get("objective")),
    stringify(get("run_options.time_limit")),
    stringify(get("run_options.presolve")),
    stringify(get("run_options.threads")),
    stringify(get("run_options.highs_solver")),
    stringify(get("run_options.highs_run_crossover")),
    stringify(get("run_options.highs_load_path")),
    stringify(get("run_options.xpress_lp_algorithm")),
    stringify(get("run_options.allow_nonoptimal")),
    stringify(get("solve_metadata.num_variables")),
    stringify(get("solve_metadata.num_constraints")),
    stringify(get("solve_metadata.num_coefficients")),
    stringify(get("solve_metadata.highs_direct_load_path")),
    stringify(get("solve_metadata.highs_matrix_build_s")),
    stringify(get("solve_metadata.highs_run_s")),
    stringify(get("solve_metadata.xpress_matrix_build_s")),
    stringify(get("solve_metadata.xpress_run_s")),
    stringify(get("solve_metadata.solution_extract_s")),
    stringify(get("solve_metadata.fingerprint_s")),
    stringify(get("framework_metadata.arco_version")),
    stringify(get("framework_metadata.solver_runtime_info.runtime_available")),
    clean_error,
]
csv.writer(sys.stdout, lineterminator="\n").writerow(row)
PY
}
check_json_parser

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

printf '%s\n' 'results_file,label,module,solver,size,status,total_s,solve_s,build_s,peak_mb,objective,time_limit,presolve,threads,highs_solver,highs_run_crossover,highs_load_path,xpress_lp_algorithm,allow_nonoptimal,num_variables,num_constraints,num_coefficients,highs_direct_load_path,highs_matrix_build_s,highs_run_s,xpress_matrix_build_s,xpress_run_s,solution_extract_s,fingerprint_s,arco_version,solver_runtime_available,error'
for file in "${files[@]}"; do
  emit_csv_row "${file}" "$(basename "${file}")"
done
REMOTE
  exit 0
fi

# =============================================================================
# LOCAL MODE
# =============================================================================
check_json_parser

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
  emit_csv_row "${file}" "$(basename "${file}")"
done
