#!/usr/bin/env bash
set -euo pipefail

readonly SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
readonly VENV_PYTHON="${REPO_ROOT}/tests/framework_comparison/.venv/bin/python"
readonly ARCO_PREFIX="${FRAMEWORK_COMPARISON_ARCO_PREFIX:-}"

log() { printf '[setup-local] %s\n' "$*" >&2; }
die() { printf '[setup-local] ERROR: %s\n' "$*" >&2; exit 1; }

[[ -x "${VENV_PYTHON}" ]] || die "Missing venv python: ${VENV_PYTHON}"

if [[ -n "${ARCO_PREFIX}" ]]; then
  readonly SCIP_LIB="${ARCO_PREFIX%/}/scip/lib"
  if [[ -d "${SCIP_LIB}" ]]; then
    export LD_LIBRARY_PATH="${SCIP_LIB}:${LD_LIBRARY_PATH:-}"
    log "LD_LIBRARY_PATH prepended: ${SCIP_LIB}"
  fi
fi

if (( $# == 0 )); then
  die "No command to execute. Usage: $0 <command> [args...]"
fi

if [[ "$1" == "python" ]]; then
  shift
  log "Running with venv python: ${VENV_PYTHON} $*"
  exec "${VENV_PYTHON}" "$@"
fi

log "Running: $*"
exec "$@"
