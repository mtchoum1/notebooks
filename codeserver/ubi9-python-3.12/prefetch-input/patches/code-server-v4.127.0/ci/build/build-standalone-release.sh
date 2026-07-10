#!/usr/bin/env bash
set -euo pipefail

# Once we have an NPM package, use this script to copy it to a separate
# directory (./release-standalone) and install the dependencies.  This new
# directory can then be packaged as a platform-specific release.
#
# Upstream code-server v4.127 removed the release:standalone npm script, but
# hermetic/Konflux builds still need the release-standalone tree (see
# Dockerfile.konflux.cpu COPY --from=rpm-base .../release-standalone/).

main() {
  cd "$(dirname "${0}")/../.."

  source ./ci/lib.sh

  rsync "$RELEASE_PATH/" "$RELEASE_PATH-standalone"
  RELEASE_PATH+=-standalone

  # Package managers may shim their own "node" wrapper into the PATH, so run
  # node and ask it for its true path.
  local node_path
  node_path="$(node -p process.execPath)"

  mkdir -p "$RELEASE_PATH/bin"
  mkdir -p "$RELEASE_PATH/lib"
  rsync ./ci/build/code-server.sh "$RELEASE_PATH/bin/code-server"
  rsync "$node_path" "$RELEASE_PATH/lib/node"

  chmod 755 "$RELEASE_PATH/lib/node"

  pushd "$RELEASE_PATH"
  # Hermetic builds set KEEP_MODULES=1 so build-release.sh already copied
  # production node_modules.  npm install would re-run postinstall.sh, which
  # hard-requires node v22 while ODH rpm-base uses nodejs:24.
  if [[ "${KEEP_MODULES:-0}" != 1 ]]; then
    npm install --unsafe-perm --omit=dev
  fi
  # Code deletes some files from the extension node_modules directory which
  # leaves broken symlinks in the corresponding .bin directory.  nfpm will fail
  # on these broken symlinks so clean them up.
  rm -fr "./lib/vscode/extensions/node_modules/.bin"
  popd
}

main "$@"
