#!/usr/bin/env bash
set -euo pipefail

# Builds vscode into lib/vscode/out-vscode.
# [ODH PATCH] Build for current architecture (like che-code) so we can use
# system Node (/usr/bin/node) instead of prefetched node tarballs.
#
# Phased usage (Dockerfile splits RUN steps to release memory between gulp tasks):
#   prepare  — patch product.json for code-server branding
#   copilot  — compile-copilot-extension-full-build (includes prepare if needed)
#   core     — gulp core-ci (extensions + esbuild reh-web bundle)
#   package  — vscode-reh-web-*-min-ci, bin scripts, validation
#   all      — default; run every phase in one process (npm run build:vscode)

# MINIFY controls whether a minified version of vscode is built.
MINIFY=${MINIFY-true}

fix-bin-script() {
  local script="lib/vscode-reh-web-$VSCODE_TARGET/bin/$1"
  sed -i.bak "s/@@VERSION@@/$(vscode_version)/g" "$script"
  sed -i.bak "s/@@COMMIT@@/$BUILD_SOURCEVERSION/g" "$script"
  sed -i.bak "s/@@APPNAME@@/code-server/g" "$script"

  # Fix Node path on Darwin and Linux.
  # We do not want expansion here; this text should make it to the file as-is.
  # shellcheck disable=SC2016
  sed -i.bak 's/^ROOT=\(.*\)$/VSROOT=\1\nROOT="$(dirname "$(dirname "$VSROOT")")"/g' "$script"
  sed -i.bak 's/ROOT\/out/VSROOT\/out/g' "$script"
  # We do not want expansion here; this text should make it to the file as-is.
  # shellcheck disable=SC2016
  sed -i.bak 's/$ROOT\/node/${NODE_EXEC_PATH:-$ROOT\/lib\/node}/g' "$script"

  # Fix Node path on Windows.
  sed -i.bak 's/^set ROOT_DIR=\(.*\)$/set ROOT_DIR=%~dp0..\\..\\..\\..\r\nset VSROOT_DIR=\1/g' "$script"
  sed -i.bak 's/%ROOT_DIR%\\out/%VSROOT_DIR%\\out/g' "$script"

  chmod +x "$script"
  rm "$script.bak"
}

copy-bin-script() {
  cp "lib/vscode/resources/server/bin/$1" "lib/vscode-reh-web-$VSCODE_TARGET/bin/$1"
  fix-bin-script "$1"
}

setup_build_env() {
  cd "$(dirname "${0}")/../.."

  source ./ci/lib.sh

  # Build for current arch (like che-code): use native gulp task and system Node.
  # gulpfile.reh.ts overlay adds ppc64/s390x to BUILD_TARGETS.
  export NODE_ARCH
  NODE_ARCH=$(node -p "process.arch")
  GULP_ARCH="${NODE_ARCH}"
  case "${NODE_ARCH}" in
    armv7l) GULP_ARCH="armhf" ;;
    ppc64le) GULP_ARCH="ppc64" ;;
  esac
  export VSCODE_TARGET="linux-${GULP_ARCH}"
  export VSCODE_REH_DIR="lib/vscode-reh-web-linux-${NODE_ARCH}"
  echo "Building VS Code for linux-${NODE_ARCH} (gulp task: ${VSCODE_TARGET})"

  # Set the commit Code will embed into the product.json.  We need to do this
  # since Code tries to get the commit from the `.git` directory which will fail
  # as it is a submodule.
  #
  # Also, we use code-server's commit rather than VS Code's otherwise it would
  # not update when only our patch files change, and that will cause caching
  # issues where the browser keeps using outdated code.
  export BUILD_SOURCEVERSION
  BUILD_SOURCEVERSION=$(git rev-parse HEAD)

  if [[ ! ${VERSION-} ]]; then
    echo "VERSION not set. Please set before running this script:" >&2
    echo "VERSION='0.0.0' npm run build:vscode" >&2
    exit 1
  fi
}

prepare_product_json() {
  pushd lib/vscode

  # Add the date, our name, links, enable telemetry (this just makes telemetry
  # available; telemetry can still be disabled by flag or setting), and
  # configure trusted extensions (since some, like github.copilot-chat, never
  # ask to be trusted and this is the only way to get auth working).
  #
  # This needs to be done before building as Code will read this file and embed
  # it into the client-side code.
  git checkout product.json             # Reset in case the script exited early.
  cp product.json product.original.json # Since jq has no inline edit.
  jq --slurp '.[0] * .[1]' product.original.json <(
    cat << EOF
  {
    "enableTelemetry": true,
    "quality": "stable",
    "codeServerVersion": "$VERSION",
    "nameShort": "code-server",
    "nameLong": "code-server",
    "applicationName": "code-server",
    "dataFolderName": ".code-server",
    "win32MutexName": "codeserver",
    "licenseUrl": "https://github.com/coder/code-server/blob/main/LICENSE",
    "win32DirName": "code-server",
    "win32NameVersion": "code-server",
    "win32AppUserModelId": "coder.code.server",
    "win32ShellNameShort": "c&ode-server",
    "darwinBundleIdentifier": "com.coder.code.server",
    "linuxIconName": "com.coder.code.server",
    "reportIssueUrl": "https://github.com/coder/code-server/issues/new",
    "documentationUrl": "https://go.microsoft.com/fwlink/?LinkID=533484#vscode",
    "keyboardShortcutsUrlMac": "https://go.microsoft.com/fwlink/?linkid=832143",
    "keyboardShortcutsUrlLinux": "https://go.microsoft.com/fwlink/?linkid=832144",
    "keyboardShortcutsUrlWin": "https://go.microsoft.com/fwlink/?linkid=832145",
    "introductoryVideosUrl": "https://go.microsoft.com/fwlink/?linkid=832146",
    "tipsAndTricksUrl": "https://go.microsoft.com/fwlink/?linkid=852118",
    "newsletterSignupUrl": "https://www.research.net/r/vsc-newsletter",
    "linkProtectionTrustedDomains": [
      "https://open-vsx.org"
    ],
    "trustedExtensionAuthAccess": [
      "vscode.git", "vscode.github",
      "github.vscode-pull-request-github",
      "github.copilot", "github.copilot-chat"
    ],
    "aiConfig": {
      "ariaKey": "code-server"
    }
  }
EOF
  ) > product.json

  popd
}

build_copilot() {
  pushd lib/vscode
  VSCODE_QUALITY=stable npm run gulp compile-copilot-extension-full-build
  popd
}

build_core() {
  pushd lib/vscode
  npm run gulp core-ci
  popd
}

fix_gulp_arch_output() {
  # If gulp uses a different arch name (e.g. armv7l -> armhf, ppc64le -> ppc64),
  # move output to NODE_ARCH dir expected by release-standalone.
  if [[ "${GULP_ARCH}" != "${NODE_ARCH}" ]]; then
    rm -rf "lib/vscode-reh-web-linux-${NODE_ARCH}"
    mv "lib/vscode-reh-web-linux-${GULP_ARCH}" "lib/vscode-reh-web-linux-${NODE_ARCH}"
    export VSCODE_TARGET="linux-${NODE_ARCH}"
  fi
}

build_package() {
  pushd lib/vscode
  npm run gulp "vscode-reh-web-$VSCODE_TARGET${MINIFY:+-min}-ci"
  popd

  fix_gulp_arch_output

  # Reset so if you develop after building you will not be stuck with the wrong
  # commit (the dev client will use `oss-dev` but the dev server will still use
  # product.json which will have `stable-$commit`).
  pushd lib/vscode
  git checkout product.json
  popd
}

install_bin_scripts() {
  # Set vars and fix paths.
  case $OS in
    windows)
      fix-bin-script remote-cli/code.cmd
      fix-bin-script helpers/browser.cmd
      ;;
    *)
      fix-bin-script remote-cli/code-server
      fix-bin-script helpers/browser.sh
      ;;
  esac

  # Include bin scripts for other platforms so we can use the right one in the
  # NPM post-install.

  # These provide a `code-server` command in the integrated terminal to open
  # files in the current instance.
  copy-bin-script remote-cli/code-darwin.sh
  copy-bin-script remote-cli/code-linux.sh
  copy-bin-script remote-cli/code.cmd

  # These provide a way for terminal applications to open browser windows.
  copy-bin-script helpers/browser-darwin.sh
  copy-bin-script helpers/browser-linux.sh
  copy-bin-script helpers/browser.cmd
}

validate_build() {
  pushd "${VSCODE_REH_DIR}"
  # Make sure Code took the version we set in the environment variable.  Not
  # having a version will break display languages.
  if ! jq -e .commit product.json; then
    echo "'commit' is missing from product.json" >&2
    exit 1
  fi
  popd
}

run_phase() {
  local phase="${1:-all}"

  case "${phase}" in
    prepare)
      prepare_product_json
      ;;
    copilot)
      if [[ ! -f lib/vscode/product.original.json ]]; then
        prepare_product_json
      fi
      build_copilot
      ;;
    core)
      build_core
      ;;
    package)
      build_package
      install_bin_scripts
      validate_build
      ;;
    all)
      prepare_product_json
      build_copilot
      build_core
      build_package
      install_bin_scripts
      validate_build
      ;;
    *)
      echo "Unknown build-vscode phase: ${phase}" >&2
      echo "Expected: prepare, copilot, core, package, or all" >&2
      exit 1
      ;;
  esac
}

main() {
  setup_build_env
  run_phase "${1:-all}"
}

main "$@"
