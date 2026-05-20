#!/usr/bin/env bash
set -euo pipefail

gams_exe="${1:?gams executable required}"
gms_path="${2:?gms path required}"
lst_path="${3:?lst path required}"
curdir="${4:?curdir required}"

license_arg=""
if [[ -n "${GAMS_LICENSE_FILE:-}" ]]; then
  license_arg="license=${GAMS_LICENSE_FILE}"
elif [[ -n "${GAMS_LICENSE:-}" ]]; then
  license_arg="license=${GAMS_LICENSE}"
fi

if [[ -n "${license_arg}" ]]; then
  exec "${gams_exe}" "${gms_path}" "${license_arg}" lo=0 "o=${lst_path}" "curdir=${curdir}"
else
  exec "${gams_exe}" "${gms_path}" lo=0 "o=${lst_path}" "curdir=${curdir}"
fi
