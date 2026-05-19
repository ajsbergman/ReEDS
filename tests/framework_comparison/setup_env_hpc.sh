#!/usr/bin/env bash
# Set up the Kestrel HPC environment and execute the job command.
#
# For use with Torc invocation_script. Loads Lmod modules, syncs the Python
# environment, prepends SCIP libs, optionally installs the Arco wheel, and
# exports environment variables consumed by run_framework.py.
#
# Usage (as Torc invocation_script):
#   invocation_script: bash setup_env_hpc.sh
#
# Torc will call:
#   bash setup_env_hpc.sh python tests/framework_comparison/run_framework.py ...
#
# Environment variables (all optional):
#   FRAMEWORK_MODULES                  Space- or comma-separated Lmod modules (default: gams/51.3.0 conda/2024.06.1)
#   FRAMEWORK_COMPARISON_ARCO_PREFIX   Prefix containing wheels/ and scip/lib/
#   GAMS_EXE                           Explicit GAMS executable path
#   TORC_API_URL                       Torc API endpoint
set -euo pipefail

readonly SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
readonly DEFAULT_MODULES="gams/51.3.0 conda/2024.06.1"
readonly TORC_API_URL_DEFAULT="http://torc.hpc.nrel.gov:8080/torc-service/v1"

log() { printf '[setup-hpc] %s\n' "$*" >&2; }
die() { printf '[setup-hpc] ERROR: %s\n' "$*" >&2; exit 1; }

# --- Resolve environment config -----------------------------------------------
# Priority: env var FRAMEWORK_MODULES (set by Torc job env override) > default
FRAMEWORK_MODULES="${FRAMEWORK_MODULES:-${DEFAULT_MODULES}}"
FRAMEWORK_MODULES="${FRAMEWORK_MODULES//,/ }"  # normalize comma → space
readonly FRAMEWORK_MODULES

readonly ARCO_PREFIX="${FRAMEWORK_COMPARISON_ARCO_PREFIX:-/scratch/${USER}/arco/latest}"

# --- Lmod setup ---------------------------------------------------------------
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
for mod in ${FRAMEWORK_MODULES}; do
  log "Loading module: ${mod}"
  module load "${mod}" || die "Failed to load module: ${mod}"
done

# --- SCIP shared library (if using Arco) ------------------------------------
readonly SCIP_LIB="${ARCO_PREFIX%/}/scip/lib"
if [[ -d "${SCIP_LIB}" ]]; then
  export LD_LIBRARY_PATH="${SCIP_LIB}:${LD_LIBRARY_PATH:-}"
  log "LD_LIBRARY_PATH prepended: ${SCIP_LIB}"
fi

# --- GAMS executable discovery -----------------------------------------------
if [[ -z "${GAMS_EXE:-}" ]] && command -v gams >/dev/null 2>&1; then
  GAMS_EXE="$(command -v gams)"
  export GAMS_EXE
fi

# --- uv sync + optional Arco wheel ------------------------------------------
log "Syncing Python environment..."
cd "${REPO_ROOT}/tests/framework_comparison"
uv sync || die "uv sync failed"

readonly VENV_PYTHON="${REPO_ROOT}/tests/framework_comparison/.venv/bin/python"
readonly WHEEL_DIR="${ARCO_PREFIX%/}/wheels"

if [[ -d "${WHEEL_DIR}" ]]; then
  log "Installing Arco from local wheels: ${WHEEL_DIR}"
  uv pip install \
    --python "${VENV_PYTHON}" \
    --reinstall \
    --no-index \
    --find-links "${WHEEL_DIR}" \
    "arco==0.6.1" || die "Failed to install Arco wheel"
fi

# --- Export environment variables -------------------------------------------
export FRAMEWORK_MODULES
export FRAMEWORK_COMPARISON_ARCO_PREFIX="${ARCO_PREFIX}"
export TORC_API_URL="${TORC_API_URL:-${TORC_API_URL_DEFAULT}}"

log "HPC environment setup complete"
log "  FRAMEWORK_MODULES=${FRAMEWORK_MODULES}"
log "  ARCO_PREFIX=${ARCO_PREFIX}"
log "  TORC_API_URL=${TORC_API_URL}"
log "  GAMS_EXE=${GAMS_EXE:-<unset>}"
log "  Python: ${VENV_PYTHON}"

# --- Execute the job command -----------------------------------------------
# Torc passes the command as positional arguments after this script.
# Example: bash setup_env_hpc.sh python run_framework.py --module solve_gams ...
if (( $# == 0 )); then
  die "No command to execute. Usage: $0 <command> [args...]"
fi

log "Running: $*"
exec "$@"
