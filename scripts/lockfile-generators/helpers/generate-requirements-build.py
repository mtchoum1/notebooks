#!/usr/bin/env python3
"""Generate requirements-build.<flavor>.txt from a hashed runtime requirements.txt.

pybuild-deps compile() recurses without a cycle cap and hits RecursionError on
the jupyter/baseline lock (195 packages). This helper uses pybuild-deps'
per-package finder, walks nested PEP 518 build-system.requires with a visited
set, then pins the union with ``uv pip compile --generate-hashes``.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name
from pybuild_deps.finder import find_build_dependencies

REQ_LINE_RE = re.compile(r"^([A-Za-z0-9._-]+)==([^\\\s;]+)")
MAX_EXPAND_ROUNDS = 5

Finder = Callable[..., list[str] | None]


def parse_pinned_requirements(requirements_path: Path) -> list[tuple[str, str]]:
    """Return (name, version) pairs from a hashed requirements.txt."""
    pins: list[tuple[str, str]] = []
    for raw in requirements_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", "--")):
            continue
        match = REQ_LINE_RE.match(line)
        if match:
            pins.append((match.group(1), match.group(2)))
    return pins


def absorb_build_requires(
    pins: list[tuple[str, str]],
    specs: dict[str, str],
    queried: set[tuple[str, str]],
    finder: Finder = find_build_dependencies,
) -> int:
    """Query PEP 518 requires for each pin. Return count of newly added specs."""
    added = 0
    for name, version in pins:
        key = (canonicalize_name(name), version)
        if key in queried:
            continue
        queried.add(key)
        try:
            requires = finder(name, version, raise_setuppy_parsing_exc=False)
        except Exception as exc:
            print(f"  warning: build-deps for {name}=={version}: {exc}", file=sys.stderr)
            continue
        for spec in requires or []:
            try:
                req = Requirement(spec)
            except InvalidRequirement:
                continue
            spec_name = canonicalize_name(req.name)
            if spec_name not in specs:
                specs[spec_name] = spec
                added += 1
    return added


def collect_build_requires(
    pins: list[tuple[str, str]],
    finder: Finder = find_build_dependencies,
) -> dict[str, str]:
    """Collect first-level PEP 518 build-system.requires from pinned sdists."""
    specs: dict[str, str] = {
        "setuptools": "setuptools",
        "wheel": "wheel",
    }
    absorb_build_requires(pins, specs, set(), finder=finder)
    return specs


def compile_build_requirements(specs: list[str], output_path: Path, python_version: str) -> None:
    """Pin collected build-system.requires with uv pip compile --generate-hashes."""
    with tempfile.NamedTemporaryFile("w", suffix=".in", encoding="utf-8", delete=False) as handle:
        handle.write("\n".join(specs) + "\n")
        in_path = Path(handle.name)
    try:
        cmd = [
            "uv",
            "pip",
            "compile",
            "--python",
            python_version,
            "--generate-hashes",
            "--no-annotate",
            "--no-header",
            "-o",
            str(output_path),
            str(in_path),
        ]
        result = subprocess.run(cmd, check=False, capture_output=True, text=True)
        if result.returncode != 0:
            sys.stderr.write(result.stdout)
            sys.stderr.write(result.stderr)
            raise SystemExit(f"uv pip compile failed for {output_path}")
    finally:
        in_path.unlink(missing_ok=True)


def expand_nested_build_requires(
    output_path: Path,
    specs: dict[str, str],
    python_version: str,
    finder: Finder = find_build_dependencies,
) -> None:
    """Recompile until nested build backends (e.g. maturin → setuptools-rust) stabilize."""
    queried: set[tuple[str, str]] = set()
    compile_build_requirements(sorted(specs.values(), key=str.lower), output_path, python_version)
    for round_no in range(1, MAX_EXPAND_ROUNDS + 1):
        build_pins = parse_pinned_requirements(output_path)
        backend_pins = [(name, version) for name, version in build_pins if canonicalize_name(name) in specs]
        added = absorb_build_requires(backend_pins, specs, queried, finder=finder)
        if added == 0:
            return
        print(f"  Nested build-backends round {round_no}: +{added} specs")
        compile_build_requirements(sorted(specs.values(), key=str.lower), output_path, python_version)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("requirements_txt", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--python", default="3.12", help="Target Python for uv pip compile")
    args = parser.parse_args(argv)

    pins = parse_pinned_requirements(args.requirements_txt)
    print(f"  Collecting PEP 518 build-system.requires from {len(pins)} packages...")
    specs = collect_build_requires(pins)
    print(f"  Compiling {len(specs)} build-backend specs → {args.output}")
    expand_nested_build_requires(args.output, specs, args.python)
    print(f"  Generated {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
