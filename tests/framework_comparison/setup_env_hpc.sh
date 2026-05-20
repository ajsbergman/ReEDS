#!/usr/bin/env bash
# Set up Kestrel HPC environment and execute Torc job command.
set -euo pipefail

readonly SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
readonly DEFAULT_MODULES="gams/51.3.0 conda/2024.06.1"
readonly TORC_API_URL_DEFAULT="http://torc.hpc.nrel.gov:8080/torc-service/v1"

log() { printf '[setup-hpc] %s\n' "$*" >&2; }
die() { printf '[setup-hpc] ERROR: %s\n' "$*" >&2; exit 1; }

FRAMEWORK_MODULES="${FRAMEWORK_MODULES:-${DEFAULT_MODULES}}"
FRAMEWORK_MODULES="${FRAMEWORK_MODULES//,/ }"
readonly FRAMEWORK_MODULES
readonly ARCO_PREFIX="${FRAMEWORK_COMPARISON_ARCO_PREFIX:-/scratch/${USER}/arco/latest}"

if [[ -f /etc/profile.d/modules.sh ]]; then
  # shellcheck disable=SC1091
  source /etc/profile.d/modules.sh
fi
if [[ -f /nopt/nrel/apps/env.sh ]]; then
  # shellcheck disable=SC1091
  source /nopt/nrel/apps/env.sh
fi

command -v module >/dev/null 2>&1 || die "'module' command not found"
module purge
for mod in ${FRAMEWORK_MODULES}; do
  log "Loading module: ${mod}"
  module load "${mod}" || die "Failed to load module: ${mod}"
done

readonly SCIP_LIB="${ARCO_PREFIX%/}/scip/lib"
if [[ -d "${SCIP_LIB}" ]]; then
  export LD_LIBRARY_PATH="${SCIP_LIB}:${LD_LIBRARY_PATH:-}"
  log "LD_LIBRARY_PATH prepended: ${SCIP_LIB}"
fi

if [[ -z "${GAMS_EXE:-}" ]] && command -v gams >/dev/null 2>&1; then
  GAMS_EXE="$(command -v gams)"
  export GAMS_EXE
fi

readonly UV_PROJECT_DIR="${FRAMEWORK_UV_PROJECT:-${REPO_ROOT}}"
readonly UV_GROUPS_RAW="${FRAMEWORK_UV_GROUPS:-framework-comparison}"
[[ -f "${UV_PROJECT_DIR}/pyproject.toml" ]] || die "Missing pyproject.toml at ${UV_PROJECT_DIR}. Set FRAMEWORK_UV_PROJECT to the ReEDS project root."

UV_GROUPS_CLEAN="${UV_GROUPS_RAW//,/ }"
readonly UV_GROUPS_CLEAN
readonly UV_SYNC_MARKER="${UV_PROJECT_DIR}/.uv-sync.${UV_GROUPS_CLEAN// /_}.done"

if [[ ! -f "${UV_SYNC_MARKER}" ]]; then
  log "Running one-time uv sync at: ${UV_PROJECT_DIR} (groups: ${UV_GROUPS_CLEAN})"
  UV_GROUP_ARGS=()
  for grp in ${UV_GROUPS_CLEAN}; do
    UV_GROUP_ARGS+=("--group" "${grp}")
  done
  uv sync --project "${UV_PROJECT_DIR}" "${UV_GROUP_ARGS[@]}" || die "uv sync failed"
  touch "${UV_SYNC_MARKER}"
fi

if [[ -x "${UV_PROJECT_DIR}/.venv/bin/python" ]]; then
  export PATH="${UV_PROJECT_DIR}/.venv/bin:${PATH}"
  log "Using project venv python: ${UV_PROJECT_DIR}/.venv/bin/python"
fi

export FRAMEWORK_MODULES
export FRAMEWORK_COMPARISON_ARCO_PREFIX="${ARCO_PREFIX}"
export TORC_API_URL="${TORC_API_URL:-${TORC_API_URL_DEFAULT}}"

if (( $# == 0 )); then
  die "No command to execute. Usage: $0 <command> [args...]"
fi

log "Running: $*"
exec "$@"
