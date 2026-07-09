# Patches for code-server (v4.127.0) — overlay onto prefetch-input/code-server

This directory is **copied over** the read-only `prefetch-input/code-server` submodule during the build (Dockerfile `COPY`). Files here overwrite the corresponding paths under the code-server source. **Do not modify `prefetch-input/code-server`**; all editable changes belong in this patches tree. The script `apply-patch.sh` (run after the COPY) then patches the @vscode/ripgrep and vsce-sign npm tarballs (ripgrep binary is supplied from the RHOAI Python wheel via `RIPGREP_BINARY_PATH`) and applies `patches/series`.

VS Code 1.127 already ships `@parcel/watcher@^2.5.6` from the npm registry, so the 4.106-era lockfile overlays for `lib/vscode/remote`, `lib/vscode/extensions`, `test`, and `microsoft-authentication` are no longer needed — upstream lockfiles are prefetched via the submodule paths in Tekton.

---

## Overlay files (v4.127.0)

| Path | Why |
|------|-----|
| **custom-packages/** | Registry-only npm deps prefetched before `lib/vscode` postinstall (`@parcel/watcher`, `@emmetio/css-parser`, `@playwright/browser-chromium`). |
| **lib/vscode/package.json** + **package-lock.json** | Adds `overrides.es5-ext → @unes/es5-ext@0.10.64-1` (Nexus quarantine) and pins `@parcel/watcher@2.5.6`. Regenerate lockfile with `npm install --package-lock-only` in `prefetch-input/code-server/lib/vscode` after editing the overlay `package.json`. |
| **lib/vscode/extensions/emmet/** | Replaces `@emmetio/css-parser` git ref with registry `0.4.1` for Cachi2/ProdSec. |
| **lib/vscode/build/gulpfile.reh.ts** | Adds `ppc64` and `s390x` to `BUILD_TARGETS` for native multi-arch hermetic builds. |
| **ci/dev/postinstall.sh** | Runs `install-deps custom-packages` before `lib/vscode` so offline `npm ci` finds prefetched tarballs. |
| **ci/build/build-vscode.sh** | Builds for current CPU arch with system Node; runs upstream 1.127 gulp targets (`compile-copilot-extension-full-build`, `core-ci`, `vscode-reh-web-*-ci`). |
| **ripgrep/postinstall.js** | Copies ripgrep from `RIPGREP_BINARY_PATH` (RHOAI pip wheel) into `@vscode/ripgrep`. |

**Argon2 (no prefetch):** root code-server `argon2` uses node-pre-gyp; `npm_config_argon2_binary_host_mirror` points at hermetic deps or falls back to gcc-toolset-14 source build.

**Regenerating lockfiles:** from repo root, copy overlay `package.json` into the matching submodule tree, run `npm install --package-lock-only --ignore-scripts`, copy `package-lock.json` back to this overlay, then `git restore` the submodule files.
