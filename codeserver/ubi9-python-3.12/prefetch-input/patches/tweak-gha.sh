#!/usr/bin/env bash
set -Eeuo pipefail

# tweak-gha.sh — Reduce VS Code build memory use for GitHub Actions runners.
#
# GitHub Actions runners (ubuntu-26.04) have only 16GB RAM. The VS Code build
# spawns multiple worker processes that each load the full TypeScript project
# via ts.createLanguageService (~2-3GB per worker). With upstream defaults
# (4 mangler workers + cpus/2 transpiler workers + 16GB Node heap), total
# memory exceeds what the runner provides.
#
# VS Code 1.127 core-ci typechecks the full tree, then runs three esbuild minify
# targets in parallel (desktop, server, server-web). code-server only ships
# reh-web, so the desktop and server bundles are dropped here.
#
# Called by apply-patch.sh when GHA_BUILD=true. Expects CWD to be the
# code-server source root (CODESERVER_SOURCE_PREFETCH).
#
# Build output matches upstream reh-web artifacts; only parallelism and unused
# bundle targets change. See: https://github.com/microsoft/vscode/issues/243708
#
# shellcheck disable=SC2016

echo "tweak-gha.sh: reducing VS Code build memory use for 16GB GitHub runner"

GULPFILE=lib/vscode/build/gulpfile.vscode.ts

# Node heap: 16GB -> 8GB (runner only has 16GB total, OS needs some).
# VS Code 1.127+ sets this on the gulp script in lib/vscode/package.json.
sed -i 's/max-old-space-size=16384/max-old-space-size=8192/' \
    lib/vscode/package.json

# Mangler rename workers: 4 -> 1 (each spawns a separate process that loads
# the entire VS Code TS project into memory, ~500-700MB each).
# VS Code 1.127+ ships build/lib as TypeScript (--experimental-strip-types).
sed -i 's/maxWorkers: 4/maxWorkers: 1/' \
    lib/vscode/build/lib/mangle/index.ts
sed -i "s/minWorkers: 'max'/minWorkers: 1/" \
    lib/vscode/build/lib/mangle/index.ts

# Transpiler workers: cap at 1 (default is cpus/2 which can be too many)
sed -i 's/Math\.floor(cpus()\.length \* \.5)/Math.min(1, Math.floor(cpus().length * .5))/' \
    lib/vscode/build/lib/tsb/transpiler.ts

# core-ci: drop tsgo-typecheck (validation only; no shipping artifacts).
sed -i '/Type-check with tsgo (no emit)/d' "$GULPFILE"
sed -i "/task.define('tsgo-typecheck'/d" "$GULPFILE"

# core-ci: code-server ships reh-web only — drop desktop and server esbuild bundles.
sed -i "/task.define('esbuild-vscode-min'/d" "$GULPFILE"
sed -i "/task.define('esbuild-vscode-reh-min'/d" "$GULPFILE"
sed -i '/Then bundle for shipping/,/esbuild-vscode-reh-web-min/ s/^[[:space:]]*task\.parallel($//' \
    "$GULPFILE"
# Remove the closing paren left over from the former task.parallel(...) wrapper.
sed -i '/esbuild-vscode-reh-web-min/{n;/^[[:space:]]*)[[:space:]]*$/d;}' "$GULPFILE"

echo "tweak-gha.sh: done"
