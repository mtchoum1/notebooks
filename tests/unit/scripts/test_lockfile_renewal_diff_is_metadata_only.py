"""Tests for scripts/ci/lockfile_renewal_diff_is_metadata_only.py."""

from __future__ import annotations

import subprocess
import textwrap
from pathlib import Path

import pytest

import scripts.ci.lockfile_renewal_diff_is_metadata_only as md


def test_normalize_exclude_newer_equals() -> None:
    a = "# x\n#    uv pip compile --exclude-newer=2025-01-01T00:00:00Z --end\nlock-version=1\n"
    b = "# x\n#    uv pip compile --exclude-newer=2026-02-02T12:00:00Z --end\nlock-version=1\n"
    assert md.normalize_ephemeral_lockfile_text(a) == md.normalize_ephemeral_lockfile_text(b)


def test_normalize_exclude_newer_space_form() -> None:
    a = "#    uv pip compile pyproject.toml --exclude-newer 2025-06-01T12:30:45Z --quiet\n"
    b = "#    uv pip compile pyproject.toml --exclude-newer 2099-01-01T00:00:00Z --quiet\n"
    assert md.normalize_ephemeral_lockfile_text(a) == md.normalize_ephemeral_lockfile_text(b)


def test_normalize_created_at_line() -> None:
    a = '[lock]\ncreated-at = "2025-01-01T00:00:00Z"\nname = "x"\n'
    b = '[lock]\ncreated-at = "2026-06-06T06:06:06Z"\nname = "x"\n'
    assert md.normalize_ephemeral_lockfile_text(a) == md.normalize_ephemeral_lockfile_text(b)


def test_normalize_does_not_hide_version_bump() -> None:
    a = '#    uv pip compile --exclude-newer=2025-01-01T00:00:00Z\n[[packages]]\nname = "foo"\nversion = "1.0"\n'
    b = '#    uv pip compile --exclude-newer=2026-02-02T12:00:00Z\n[[packages]]\nname = "foo"\nversion = "2.0"\n'
    assert md.normalize_ephemeral_lockfile_text(a) != md.normalize_ephemeral_lockfile_text(b)


def test_diff_vs_head_git_repo(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-b", "main"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@e.st"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path, check=True, capture_output=True)

    body = textwrap.dedent(
        """\
        # h
        #    uv pip compile --exclude-newer=2025-01-01T00:00:00Z x
        lock-version = "1.0"
        [[packages]]
        name = "x"
        version = "1"
        """
    )
    (tmp_path / "pylock.toml").write_text(body, encoding="utf-8")
    subprocess.run(["git", "add", "pylock.toml"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, check=True, capture_output=True)

    body2 = body.replace("2025-01-01T00:00:00Z", "2099-12-31T23:59:59Z")
    (tmp_path / "pylock.toml").write_text(body2, encoding="utf-8")
    assert md.diff_vs_head_is_metadata_only(repo_root=tmp_path) is True

    body3 = body2.replace('version = "1"', 'version = "2"')
    (tmp_path / "pylock.toml").write_text(body3, encoding="utf-8")
    assert md.diff_vs_head_is_metadata_only(repo_root=tmp_path) is False


def test_diff_vs_head_clean_tree(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-b", "main"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@e.st"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / "f").write_text("x", encoding="utf-8")
    subprocess.run(["git", "add", "f"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, check=True, capture_output=True)
    assert md.diff_vs_head_is_metadata_only(repo_root=tmp_path) is True


@pytest.mark.parametrize(
    ("main_code", "expected"),
    [
        pytest.param(0, 0, id="metadata-only"),
        pytest.param(1, 1, id="substantive"),
    ],
)
def test_main_exit_code(monkeypatch: pytest.MonkeyPatch, main_code: int, expected: int) -> None:
    monkeypatch.setattr(md, "diff_vs_head_is_metadata_only", lambda repo_root: main_code == 0)
    monkeypatch.setattr(md, "ROOT", Path("/tmp"))
    assert md.main() == expected
