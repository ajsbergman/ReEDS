#!/usr/bin/env bash
set -euo pipefail

gams_exe="${1:?gams executable required}"
gms_path="${2:?gms path required}"
lst_path="${3:?lst path required}"
curdir="${4:?curdir required}"

exec "${gams_exe}" "${gms_path}" lo=0 "o=${lst_path}" "curdir=${curdir}"
