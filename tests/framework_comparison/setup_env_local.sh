#!/usr/bin/env bash
# Setup the local Python environment for the framework comparison benchmark.
#
# Usage:
#   ./setup_env_local.sh [--arco-prefix PATH]
#
# Environment variables (all optional):
#   FRAMEWORK_COMPARISON_ARCO_PREFIX   Prefix containing wheels/ and scip/lib/
#
# Example:
#   FRAMEWORK_COMPARISON_ARCO_PREFIX=/opt/arco ./setup_env_local.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

ARCO_PREFIX="${FRAMEWORK_COMPARISON_ARCO_PREFIX:-}"

log()  { printf '[setup-local] %s\n' "$*" >&2; }
die()  { printf '[setup-local] ERROR: %s\n' "$*" >&2; exit 1; }

# --- Parse args ---------------------------------------------------------------
while (($#)); do
  case "$1" in
    --arco-prefix)
      ARCO_PREFIX="${2:?missing value for --arco-prefix}"
      shift 2
      ;;
    -h|--help)
      sed -n '2,/^set -/p' "$0" | grep '^#' | sed 's/^# \?//'
      exit 0
      ;;
    *)
      die "Unknown option: $1"
      ;;
  esac
done

# --- uv sync ------------------------------------------------------------------
log "Syncing Python environment..."
if ! command -v uv >/dev/null 2>&1; then
  die "uv is required. Install from https://github.com/astral-sh/uv"
fi
uv sync --project "${REPO_ROOT}/tests/framework_comparison"

VENV_PYTHON="${REPO_ROOT}/tests/framework_comparison/.venv/bin/python"

# --- Optional Arco wheel install ----------------------------------------------
if [[ -n "${ARCO_PREFIX}" ]]; then
  WHEEL_DIR="${ARCO_PREFIX%/}/wheels"
  if [[ -d "${WHEEL_DIR}" ]]; then
    log "Installing Arco from local wheels: ${WHEEL_DIR}"
    uv pip install \
      --python "${VENV_PYTHON}" \
      --reinstall \
      --no-index \
      --find-links "${WHEEL_DIR}" \
      "arco==0.6.1"
  else
    log "ARCO_PREFIX set but wheels/ not found at ${WHEEL_DIR} — skipping Arco wheel install"
  fi

  SCIP_LIB="${ARCO_PREFIX%/}/scip/lib"
  if [[ -d "${SCIP_LIB}" ]]; then
    log "Prepending SCIP lib to LD_LIBRARY_PATH: ${SCIP_LIB}"
    export LD_LIBRARY_PATH="${SCIP_LIB}:${LD_LIBRARY_PATH:-}"
  fi
fi

log "Environment ready. Python: ${VENV_PYTHON}"
