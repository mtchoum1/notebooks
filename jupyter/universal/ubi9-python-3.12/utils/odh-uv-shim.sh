#!/usr/bin/env bash
# Wrap the real `uv` binary so mutating `uv pip` commands always install into
# the PVC-backed persistent prefix. Plain `uv.toml` [pip].prefix is not enough
# alone because the image sets UV_CONFIG_FILE=/opt/app-root/uv.toml (which
# disables user-config discovery) and VIRTUAL_ENV=/opt/app-root.
#
# Installed as $ODH_PERSISTENT_PACKAGES_ROOT/shim/uv (ahead of .../bin on PATH).
set -euo pipefail

ROOT="${ODH_PERSISTENT_PACKAGES_ROOT:-${HOME}/.local-packages}"
REAL_UV="${ROOT}/bin/uv"

if [ ! -x "${REAL_UV}" ]; then
  echo "odh-uv-shim: uv not found at ${REAL_UV}." >&2
  echo "Install it onto the PVC first:  pip install uv" >&2
  exit 127
fi

_has_flag() {
  # True if argv already contains --prefix/--target (with or without =value).
  local arg
  for arg in "$@"; do
    case "${arg}" in
      --prefix | --prefix=* | --target | --target=*) return 0 ;;
    esac
  done
  return 1
}

# uv pip install|uninstall|sync → force --prefix unless user already chose one.
if [ "${1-}" = "pip" ]; then
  case "${2-}" in
    install | uninstall | sync)
      subcmd="${2}"
      shift 2
      if _has_flag "$@"; then
        exec "${REAL_UV}" pip "${subcmd}" "$@"
      fi
      exec "${REAL_UV}" pip "${subcmd}" --prefix="${ROOT}" "$@"
      ;;
  esac
fi

exec "${REAL_UV}" "$@"
