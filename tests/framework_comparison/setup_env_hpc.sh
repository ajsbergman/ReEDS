#!/usr/bin/env bash
# Set up the Kestrel HPC environment for the framework comparison benchmark.
#
# This script is sourced or executed as the pre-job step by Torc.
# It loads Lmod modules, prepends SCIP libs, optionally installs the Arco
# wheel, and exports environment variables consumed by run_framework.py.
#
# Usage (standalone – for manual inspection):
#   ./setup_env_hpc.sh [--modules "mod1 mod2"] [--arco-prefix PATH]
#
# Usage (Torc pre-job, as exec wrapper):
#   ./setup_env_hpc.sh -- python run_framework.py ...
#
# Environment variables (all optional; flags override):
#   FRAMEWORK_MODULES                  Space- or comma-separated Lmod modules
#   FRAMEWORK_COMPARISON_ARCO_PREFIX   Prefix containing wheels/ and scip/lib/
#   GAMS_EXE                           Explicit GAMS executable path
#   TORC_API_URL                       Torc API endpoint
#
# Default modules: gams/51.3.0 conda/2024.06.1
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

TORC_API_URL_DEFAULT="http://torc.hpc.nrel.gov:8080/torc-service/v1"
DEFAULT_MODULES="gams/51.3.0 conda/2024.06.1"

log()  { printf '[setup-hpc] %s\n' "$*" >&2; }
die()  { printf '[setup-hpc] ERROR: %s\n' "$*" >&2; exit 1; }

# --- Parse args ---------------------------------------------------------------
MODULES_ARG=""
ARCO_PREFIX_ARG=""
REMAINING_ARGS=()

while (($#)); do
  case "$1" in
    --modules)
      MODULES_ARG="${2:?missing value for --modules}"
      shift 2
      ;;
    --arco-prefix)
      ARCO_PREFIX_ARG="${2:?missing value for --arco-prefix}"
      shift 2
      ;;
    -h|--help)
      sed -n '2,/^set -/p' "$0" | grep '^#' | sed 's/^# \?//'
      exit 0
      ;;
    --)
      shift
      REMAINING_ARGS=("$@")
      break
      ;;
    *)
      die "Unknown option: $1"
      ;;
  esac
done

# --- Resolve configuration ----------------------------------------------------
# Priority: flag > FRAMEWORK_COMPARISON_MODULES (legacy) > FRAMEWORK_MODULES > default
RESOLVED_MODULES="${MODULES_ARG:-${FRAMEWORK_COMPARISON_MODULES:-${FRAMEWORK_MODULES:-${DEFAULT_MODULES}}}}"
RESOLVED_MODULES="${RESOLVED_MODULES//,/ }"   # normalise comma → space

ARCO_PREFIX="${ARCO_PREFIX_ARG:-${FRAMEWORK_COMPARISON_ARCO_PREFIX:-/scratch/${USER}/arco/latest}}"

# --- Lmod initialization ------------------------------------------------------
if [[ -f /etc/profile.d/modules.sh ]]; then
  # shellcheck disable=SC1091
  source /etc/profile.d/modules.sh
fi
if [[ -f /nopt/nrel/apps/env.sh ]]; then
  # shellcheck disable=SC1091
  source /nopt/nrel/apps/env.sh
fi

if ! command -v module >/dev/null 2>&1; then
  die "'module' command not found. Is this a Kestrel login/compute node?"
fi

module purge
for mod in ${RESOLVED_MODULES}; do
  log "Loading module: ${mod}"
  module load "${mod}"
done

# --- SCIP shared library ------------------------------------------------------
SCIP_LIB="${ARCO_PREFIX%/}/scip/lib"
if [[ -d "${SCIP_LIB}" ]]; then
  export LD_LIBRARY_PATH="${SCIP_LIB}:${LD_LIBRARY_PATH:-}"
  log "LD_LIBRARY_PATH prepended: ${SCIP_LIB}"
fi

# --- GAMS executable ----------------------------------------------------------
if [[ -z "${GAMS_EXE:-}" ]] && command -v gams >/dev/null 2>&1; then
  GAMS_EXE="$(command -v gams)"
  export GAMS_EXE
fi

# --- uv sync + optional Arco wheel -------------------------------------------
log "Syncing Python environment..."
uv sync --project "${REPO_ROOT}/tests/framework_comparison"

VENV_PYTHON="${REPO_ROOT}/tests/framework_comparison/.venv/bin/python"
WHEEL_DIR="${ARCO_PREFIX%/}/wheels"
if [[ -d "${WHEEL_DIR}" ]]; then
  log "Installing Arco from local wheels: ${WHEEL_DIR}"
  uv pip install \
    --python "${VENV_PYTHON}" \
    --reinstall \
    --no-index \
    --find-links "${WHEEL_DIR}" \
    "arco==0.6.1"
fi

# --- Export canonical variables -----------------------------------------------
export FRAMEWORK_MODULES="${RESOLVED_MODULES}"
export FRAMEWORK_COMPARISON_MODULES="${RESOLVED_MODULES}"
export FRAMEWORK_COMPARISON_ARCO_PREFIX="${ARCO_PREFIX}"
export TORC_API_URL="${TORC_API_URL:-${TORC_API_URL_DEFAULT}}"

# --- Summary ------------------------------------------------------------------
log "HPC environment ready"
log "  FRAMEWORK_MODULES=${FRAMEWORK_MODULES}"
log "  FRAMEWORK_COMPARISON_ARCO_PREFIX=${FRAMEWORK_COMPARISON_ARCO_PREFIX}"
log "  TORC_API_URL=${TORC_API_URL}"
log "  GAMS_EXE=${GAMS_EXE:-<unset>}"
log "  gams binary: $(command -v gams || echo '<missing>')"
log "  python:      ${VENV_PYTHON}"


