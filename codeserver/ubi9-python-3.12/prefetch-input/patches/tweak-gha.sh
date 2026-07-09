#!/usr/bin/env bash
set -Eeuo pipefail

# tweak-gha.sh — Reduce VS Code build parallelism for GitHub Actions runners.
#
# GitHub Actions runners (ubuntu-26.04) have only 16GB RAM. The VS Code build
# spawns multiple worker processes that each load the full TypeScript project
# via ts.createLanguageService (~2-3GB per worker). With upstream defaults
# (4 mangler workers + cpus/2 transpiler workers + 16GB Node heap), total
# memory exceeds what the runner provides.
#
# Called by apply-patch.sh when GHA_BUILD=true. Expects CWD to be the
# code-server source root (CODESERVER_SOURCE_PREFETCH).
#
# Build output is byte-for-byte identical to upstream; only parallelism changes.
# See: https://github.com/microsoft/vscode/issues/243708 (upstream OOM reports)

echo "tweak-gha.sh: reducing VS Code build parallelism for 16GB GitHub runner"

# Node heap: 16GB -> 8GB (runner only has 16GB total, OS needs some).
# VS Code 1.127+ sets this on the gulp script in lib/vscode/package.json.
sed -i 's/max-old-space-size=16384/max-old-space-size=8192/' \
    lib/vscode/package.json

# Mangler rename workers: 4 -> 2 (each spawns a separate process that loads
# the entire VS Code TS project into memory, ~500-700MB each).
# VS Code 1.127+ ships build/lib as TypeScript (--experimental-strip-types).
sed -i 's/maxWorkers: 4/maxWorkers: 2/' \
    lib/vscode/build/lib/mangle/index.ts
sed -i "s/minWorkers: 'max'/minWorkers: 2/" \
    lib/vscode/build/lib/mangle/index.ts

# Transpiler workers: cap at 2 (default is cpus/2 which can be too many)
sed -i 's/Math\.floor(cpus()\.length \* \.5)/Math.min(2, Math.floor(cpus().length * .5))/' \
    lib/vscode/build/lib/tsb/transpiler.ts

echo "tweak-gha.sh: done"
