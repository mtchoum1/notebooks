"""Unit tests for pylock vs manifest downgrade detection."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]


def _load_update_script():
    path = ROOT / "manifests/tools/update_imagestream_annotations_from_pylock.py"
    spec = importlib.util.spec_from_file_location("update_imagestream_annotations_from_pylock", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def upd():
    return _load_update_script()


def test_manifest_version_parses_v_prefix(upd):
    assert str(upd._manifest_version_to_version("v4.5")) == "4.5"
    assert str(upd._manifest_version_to_version("4.5")) == "4.5"


def test_find_pyproject_downgrades_detects_lower_pin(upd):
    from tests.manifests import NotebookMetadata, NotebookType

    meta = NotebookMetadata(
        type=NotebookType.WORKBENCH,
        feature="jupyter",
        scope="minimal",
        os_flavor="ubi9",
        python_flavor="python-3.12",
        accelerator_flavor=None,
    )
    existing = [{"name": "Numpy", "version": "2.4"}]
    new_deps = [{"name": "Numpy", "version": "2.0"}]
    pylock = {"numpy": {"version": "2.0.2"}}
    pnames = frozenset({"numpy"})
    downs = upd._find_pyproject_downgrades(existing, new_deps, pylock, meta, pnames)
    assert len(downs) == 1
    assert downs[0][0] == "Numpy"
    assert "2.0.2" in downs[0][2]


def test_find_pyproject_downgrades_skips_when_not_in_pyproject(upd):
    from tests.manifests import NotebookMetadata, NotebookType

    meta = NotebookMetadata(
        type=NotebookType.WORKBENCH,
        feature="jupyter",
        scope="minimal",
        os_flavor="ubi9",
        python_flavor="python-3.12",
        accelerator_flavor=None,
    )
    existing = [{"name": "Numpy", "version": "2.4"}]
    new_deps = [{"name": "Numpy", "version": "2.0"}]
    pylock = {"numpy": {"version": "2.0.2"}}
    downs = upd._find_pyproject_downgrades(existing, new_deps, pylock, meta, frozenset())
    assert downs == []
