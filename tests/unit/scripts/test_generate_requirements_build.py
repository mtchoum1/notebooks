from __future__ import annotations

import importlib.util
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_MODULE_PATH = _REPO_ROOT / "scripts" / "lockfile-generators" / "helpers" / "generate-requirements-build.py"
_SPEC = importlib.util.spec_from_file_location("generate_requirements_build", _MODULE_PATH)
assert _SPEC is not None
assert _SPEC.loader is not None
helper = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(helper)


def test_parse_pinned_requirements_skips_index_and_hashes(tmp_path: Path) -> None:
    req = tmp_path / "requirements.cpu.txt"
    req.write_text(
        "--index-url https://pypi.org/simple\n"
        "aiohttp==3.14.3 ; python_full_version == '3.12.*' \\\n"
        "    --hash=sha256:abc\n"
        "uv==0.12.5\n"
        "# comment\n",
        encoding="utf-8",
    )
    assert helper.parse_pinned_requirements(req) == [
        ("aiohttp", "3.14.3"),
        ("uv", "0.12.5"),
    ]


def test_absorb_nested_build_backends() -> None:
    def fake_finder(name: str, version: str, **kwargs: object) -> list[str]:
        table = {
            ("rpds-py", "2026.6.3"): ["maturin>=1"],
            ("maturin", "1.14.1"): ["setuptools-rust>=1.11.0", "setuptools>=77"],
        }
        return table.get((name, version), [])

    specs: dict[str, str] = {"setuptools": "setuptools", "wheel": "wheel"}
    queried: set[tuple[str, str]] = set()
    helper.absorb_build_requires([("rpds-py", "2026.6.3")], specs, queried, finder=fake_finder)
    assert "maturin" in specs
    helper.absorb_build_requires([("maturin", "1.14.1")], specs, queried, finder=fake_finder)
    assert "setuptools-rust" in specs
    # Second pass is a no-op (visited set).
    assert helper.absorb_build_requires([("maturin", "1.14.1")], specs, queried, finder=fake_finder) == 0
