#!/usr/bin/env python3
"""Return whether ``git diff HEAD`` is only ephemeral UV / pylock metadata.

``make refresh-lock-files`` rewrites the UV header comment on every run with a
fresh ``--exclude-newer=…`` timestamp.  When the solver output is otherwise
unchanged, the renewal workflow would open a noisy PR touching many files.

Exit codes (for use from bash ``if ./uv run python …; then``):

- ``0`` — every changed file differs from ``HEAD`` only after normalizing
  ephemeral fields (skip opening a PR; caller may ``git restore``).
- ``1`` — at least one changed file has substantive edits, or git/diff error.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# UV embeds ``--exclude-newer`` in the second-line ``uv pip compile`` header comment.
_EXCLUDE_NEWER_RE = re.compile(r"--exclude-newer(?:=\s*|\s+)(\S+)")
# Future / alternate pylock headers (e.g. PEP 751 style metadata).
_CREATED_AT_RE = re.compile(
    r"^created-at\s*=\s*(?:\"[^\"]*\"|'[^']*'|[^\s#]+)\s*$",
    flags=re.MULTILINE,
)

_PLACEHOLDER = "<ephemeral-lockfile-metadata>"


def normalize_ephemeral_lockfile_text(content: str) -> str:
    """Strip volatile timestamps from lockfile text for equality checks."""
    s = _EXCLUDE_NEWER_RE.sub(f"--exclude-newer={_PLACEHOLDER}", content)
    s = _CREATED_AT_RE.sub(f'created-at = "{_PLACEHOLDER}"', s)
    return s


def _git_output(args: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def _changed_paths_vs_head(cwd: Path) -> list[str] | None:
    p = _git_output(["diff", "--name-only", "-z", "HEAD"], cwd=cwd)
    if p.returncode != 0:
        return None
    names = [n for n in p.stdout.split("\0") if n]
    return names


def _is_binary_change(cwd: Path, path: str) -> bool:
    p = _git_output(["diff", "--numstat", "HEAD", "--", path], cwd=cwd)
    if p.returncode != 0 or not p.stdout.strip():
        return False
    first = p.stdout.splitlines()[0].split("\t", 1)[0]
    return first == "-"


def _blob_at_head(cwd: Path, path: str) -> bytes | None:
    p = subprocess.run(
        ["git", "show", f"HEAD:{path}"],
        cwd=cwd,
        check=False,
        capture_output=True,
    )
    if p.returncode != 0:
        return None
    return p.stdout


def diff_vs_head_is_metadata_only(*, repo_root: Path) -> bool | None:
    """``True`` if every worktree change vs ``HEAD`` is metadata-only, ``False`` if substantive.

    Returns ``None`` if git failed or a path could not be read.
    """
    paths = _changed_paths_vs_head(repo_root)
    if paths is None:
        return None
    if not paths:
        return True

    for path in paths:
        if _is_binary_change(repo_root, path):
            return False
        head_bytes = _blob_at_head(repo_root, path)
        if head_bytes is None:
            return False
        work_path = repo_root / path
        if not work_path.is_file():
            return False
        try:
            head_text = head_bytes.decode("utf-8")
            work_text = work_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return False

        if normalize_ephemeral_lockfile_text(head_text) != normalize_ephemeral_lockfile_text(work_text):
            return False
    return True


def main() -> int:
    result = diff_vs_head_is_metadata_only(repo_root=ROOT)
    if result is None:
        print("lockfile_renewal_diff_is_metadata_only: git diff failed", file=sys.stderr)
        return 1
    if result:
        print("lockfile_renewal_diff_is_metadata_only: only ephemeral metadata changed")
        return 0
    print("lockfile_renewal_diff_is_metadata_only: substantive changes detected")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
