#!/usr/bin/env bash
set -euo pipefail

# hermeto-fetch-pip.sh — Prefetch Python sdists using Hermeto.
#
# Default is source-only (no `binary` field). `uv` is allowlisted as wheels:
# its published Cargo.lock does not match Cargo.toml, so Hermeto's
# `cargo vendor --locked` rejects the sdist (PackageWithCorruptLockfileRejected).
# Permissive mode is avoided because it regenerates Cargo.lock at prefetch time.
#
# Output is merged into cachi2/output/deps/pip/ for offline
# `uv pip install --no-index --no-binary :all: --only-binary uv`.
#
# generate-env / inject-files record PIP_FIND_LINKS and Cargo vendor paths
# so remaining Rust extensions (cryptography, rpds-py) can compile offline.
#
# Must be run from the repository root.

# shellcheck source-path=SCRIPTDIR
source "$(dirname "$0")/hermeto-common.sh"

COMPONENT_DIR=""
FLAVOR="cpu"

show_help() {
  cat << 'EOF'
Usage: helpers/hermeto-fetch-pip.sh [OPTIONS]

Prefetch Python sdists with Hermeto (wheels only for uv; see script header).

Options:
  --component-dir DIR    Image directory with requirements.<flavor>.txt (required)
  --flavor NAME          Lock flavor (default: cpu)
  --help                 Show this help
EOF
}

error_exit() {
  echo "Error: $1" >&2
  exit 1
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --component-dir) [[ $# -ge 2 ]] || error_exit "--component-dir requires a value"
                     COMPONENT_DIR="$2"; shift 2 ;;
    --flavor)        [[ $# -ge 2 ]] || error_exit "--flavor requires a value"
                     FLAVOR="$2"; shift 2 ;;
    -h|--help)       show_help; exit 0 ;;
    *)               error_exit "Unknown argument: '$1'" ;;
  esac
done

[[ -z "$COMPONENT_DIR" ]] && error_exit "--component-dir is required."
[[ -d "$COMPONENT_DIR" ]] || error_exit "Component directory not found: $COMPONENT_DIR"

REQUIREMENTS_FILE="${COMPONENT_DIR}/requirements.${FLAVOR}.txt"
REQUIREMENTS_BUILD_FILE="${COMPONENT_DIR}/requirements-build.${FLAVOR}.txt"
[[ -f "$REQUIREMENTS_FILE" ]] || error_exit "Missing ${REQUIREMENTS_FILE}"
[[ -f "$REQUIREMENTS_BUILD_FILE" ]] || error_exit "Missing ${REQUIREMENTS_BUILD_FILE}"
[[ -d .git ]] || error_exit "This script must be run from the repository root (no .git found)."
command -v jq >/dev/null || error_exit "jq is required"

# uv: wheel-only. All other packages stay sdist. Arches match Konflux.
HERMETO_JSON=$(jq -n \
  --arg path "$COMPONENT_DIR" \
  --arg req "requirements.${FLAVOR}.txt" \
  --arg build "requirements-build.${FLAVOR}.txt" \
  '{
    type: "pip",
    path: $path,
    requirements_files: [$req],
    requirements_build_files: [$build],
    binary: {
      packages: "uv",
      arch: "x86_64,aarch64,ppc64le,s390x",
      os: "linux",
      py_version: 312
    }
  }')

# Hermeto fetch-deps wipes --output on every run. Stage, then merge pip/.
HERMETO_STAGING=$(mktemp -d)
# Hide local caches from Hermeto's source copy (it shutil.copytree's --source).
CACHI2_HIDE=$(mktemp -d)
VENV_HIDE=$(mktemp -d)
trap 'rm -rf "$HERMETO_STAGING" "$CACHI2_HIDE" "$VENV_HIDE"' EXIT

SOURCE_MOUNTS=(-v "$(pwd):/source:z")
[[ -d cachi2 ]] && SOURCE_MOUNTS+=(-v "$CACHI2_HIDE:/source/cachi2:z")
[[ -d .venv ]] && SOURCE_MOUNTS+=(-v "$VENV_HIDE:/source/.venv:z")

echo "--- Downloading Python sdists via hermeto (binary.packages=uv) ---"
echo "  component : ${COMPONENT_DIR}"
echo "  flavor    : ${FLAVOR}"
podman run --rm \
  "${SOURCE_MOUNTS[@]}" \
  -v "$HERMETO_STAGING:/output:z" \
  "$HERMETO_IMAGE" \
  fetch-deps --source /source --output /output "$HERMETO_JSON"

echo "--- Generating hermeto env for /cachi2/output ---"
podman run --rm \
  -v "$HERMETO_STAGING:/output:z" \
  "$HERMETO_IMAGE" \
  generate-env /output -o /output/cachi2.env --for-output-dir /cachi2/output

echo "--- inject-files (Cargo vendor paths for Rust sdists) ---"
podman run --rm \
  "${SOURCE_MOUNTS[@]}" \
  -v "$HERMETO_STAGING:/output:z" \
  "$HERMETO_IMAGE" \
  inject-files /output --for-output-dir /cachi2/output

if ! test -w "$HERMETO_STAGING/deps/pip" 2>/dev/null; then
  sudo chown -R "$(id -u):$(id -g)" "$HERMETO_STAGING" 2>/dev/null || true
fi

mkdir -p "$HERMETO_OUTPUT/deps/pip"
if [[ -d "$HERMETO_STAGING/deps/pip" ]]; then
  cp -a "$HERMETO_STAGING/deps/pip"/. "$HERMETO_OUTPUT/deps/pip/"
else
  error_exit "Hermeto did not produce deps/pip in ${HERMETO_STAGING}"
fi
# Preserve cargo vendor trees if Hermeto wrote them alongside pip.
if [[ -d "$HERMETO_STAGING/deps/cargo" ]]; then
  mkdir -p "$HERMETO_OUTPUT/deps/cargo"
  cp -a "$HERMETO_STAGING/deps/cargo"/. "$HERMETO_OUTPUT/deps/cargo/"
fi
[[ -f "$HERMETO_STAGING/cachi2.env" ]] && cp -f "$HERMETO_STAGING/cachi2.env" "$HERMETO_OUTPUT/cachi2.env"
[[ -f "$HERMETO_STAGING/bom.json" ]] && cp -f "$HERMETO_STAGING/bom.json" "$HERMETO_OUTPUT/bom.json"
[[ -f "$HERMETO_STAGING/.build-config.json" ]] && cp -f "$HERMETO_STAGING/.build-config.json" "$HERMETO_OUTPUT/.build-config.json"

echo "Finished! Python sdists are in $HERMETO_OUTPUT/deps/pip"
