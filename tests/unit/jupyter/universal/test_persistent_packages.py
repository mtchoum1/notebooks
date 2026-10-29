"""Unit tests for universal workbench PVC-backed persistent packages."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests import PROJECT_ROOT

_UNIVERSAL = PROJECT_ROOT / "jupyter" / "universal" / "ubi9-python-3.12"
_SETUP = _UNIVERSAL / "setup-persistent-packages.sh"
_HELPER = _UNIVERSAL / "utils" / "odh_workbench_persistent_packages.py"
_PTH = _UNIVERSAL / "utils" / "odh_workbench_persistent_packages.pth"
_UV_SHIM = _UNIVERSAL / "utils" / "odh-uv-shim.sh"
_ENTRYPOINT = _UNIVERSAL / "entrypoint-universal.sh"
_DOCKERFILE = _UNIVERSAL / "Dockerfile.konflux.cpu"


def test_persistent_packages_artifacts_exist() -> None:
    assert _SETUP.is_file()
    assert _HELPER.is_file()
    assert _PTH.is_file()
    assert _UV_SHIM.is_file()
    pth = _PTH.read_text(encoding="utf-8")
    assert "import odh_workbench_persistent_packages" in pth
    shim = _UV_SHIM.read_text(encoding="utf-8")
    assert "--prefix=" in shim
    assert 'pip install|uninstall|sync' in shim or "install | uninstall | sync" in shim


def test_dockerfile_installs_pth_bridge() -> None:
    text = _DOCKERFILE.read_text(encoding="utf-8")
    assert "setup-persistent-packages.sh" in text
    assert "odh_workbench_persistent_packages.pth" in text
    assert "odh_workbench_persistent_packages.py" in text
    assert "odh-uv-shim.sh" in text
    # FIPS: strip uv CLI + package so users can pip-install uv onto the PVC.
    assert "pip uninstall -y uv" in text
    assert "rm -f /opt/app-root/bin/uv /opt/app-root/bin/uvx" in text


def test_entrypoint_sources_setup_in_workbench_mode() -> None:
    text = _ENTRYPOINT.read_text(encoding="utf-8")
    assert "setup-persistent-packages.sh" in text
    assert "source /opt/app-root/bin/utils/setup-persistent-packages.sh" in text


def _source_setup(tmp_path: Path, *, opt_out: bool = False) -> dict[str, str]:
    home = tmp_path / "home"
    home.mkdir()
    # Fake image utils path so the shim install succeeds in unit tests.
    fake_utils = tmp_path / "opt" / "app-root" / "bin" / "utils"
    fake_utils.mkdir(parents=True)
    (fake_utils / "odh-uv-shim.sh").write_text(
        _UV_SHIM.read_text(encoding="utf-8"), encoding="utf-8"
    )
    (fake_utils / "odh-uv-shim.sh").chmod(0o755)
    # Also fake /opt/app-root/uv.toml for merge behavior.
    fake_app_root = tmp_path / "opt" / "app-root"
    (fake_app_root / "uv.toml").write_text(
        'index-url = "https://example.invalid/simple/"\n', encoding="utf-8"
    )
    wrapper = tmp_path / "wrapper.sh"
    opt = "export ODH_PERSISTENT_PACKAGES=0\n" if opt_out else "unset ODH_PERSISTENT_PACKAGES\n"
    wrapper.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        f"{opt}"
        f'export HOME="{home}"\n'
        "unset ODH_PERSISTENT_PACKAGES_ROOT PIP_PREFIX UV_CONFIG_FILE\n"
        # Point the setup script at our fake image paths via bind-style override:
        # rewrite the hard-coded /opt/app-root references for the test.
        f'sed "s|/opt/app-root|{fake_app_root}|g" "{_SETUP}" > "{tmp_path}/setup.sh"\n'
        f'source "{tmp_path}/setup.sh"\n'
        "printf 'root=%s\\n' \"${ODH_PERSISTENT_PACKAGES_ROOT-}\"\n"
        "printf 'pip_prefix=%s\\n' \"${PIP_PREFIX-}\"\n"
        "printf 'uv_config=%s\\n' \"${UV_CONFIG_FILE-}\"\n"
        "case \":$PATH:\" in *\":${ODH_PERSISTENT_PACKAGES_ROOT:-__none__}/bin:\"*) _ph=1 ;; *) _ph=0 ;; esac\n"
        "printf 'path_has_bin=%s\\n' \"${_ph}\"\n"
        "case \":$PATH:\" in *\":${ODH_PERSISTENT_PACKAGES_ROOT:-__none__}/shim:\"*) _sh=1 ;; *) _sh=0 ;; esac\n"
        "printf 'path_has_shim=%s\\n' \"${_sh}\"\n"
        "printf 'lib=%s\\n' \"$([ -d \"${ODH_PERSISTENT_PACKAGES_ROOT:-/}/lib/python3.12/site-packages\" ] && printf 1 || printf 0)\"\n"
        "printf 'lib64=%s\\n' \"$([ -d \"${ODH_PERSISTENT_PACKAGES_ROOT:-/}/lib64/python3.12/site-packages\" ] && printf 1 || printf 0)\"\n"
        "printf 'shim=%s\\n' \"$([ -x \"${ODH_PERSISTENT_PACKAGES_ROOT:-/}/shim/uv\" ] && printf 1 || printf 0)\"\n",
        encoding="utf-8",
    )
    wrapper.chmod(0o755)
    result = subprocess.run(
        ["bash", str(wrapper)],
        check=False,
        capture_output=True,
        text=True,
        env=os.environ.copy(),
    )
    assert result.returncode == 0, result.stderr
    parsed: dict[str, str] = {}
    for line in result.stdout.splitlines():
        key, _, value = line.partition("=")
        parsed[key] = value
    return parsed


def test_setup_exports_prefix_and_creates_site_dirs(tmp_path: Path) -> None:
    out = _source_setup(tmp_path)
    home = tmp_path / "home"
    expected = str(home / ".local-packages")
    assert out["root"] == expected
    assert out["pip_prefix"] == expected
    assert out["uv_config"] == f"{expected}/uv.toml"
    assert out["path_has_bin"] == "1"
    assert out["path_has_shim"] == "1"
    assert out["shim"] == "1"
    assert out["lib"] == "1"
    assert out["lib64"] == "1"
    env_file = home / ".local-packages" / "env.sh"
    assert env_file.is_file()
    env_text = env_file.read_text(encoding="utf-8")
    assert expected in env_text
    assert "PIP_PREFIX" in env_text
    for profile in (home / ".bashrc", home / ".profile"):
        assert profile.is_file()
        assert "odh-persistent-packages" in profile.read_text(encoding="utf-8")
    uv_toml = home / ".local-packages" / "uv.toml"
    assert uv_toml.is_file()
    uv_text = uv_toml.read_text(encoding="utf-8")
    assert "odh-persistent-packages" in uv_text
    assert "[pip]" in uv_text
    assert f'prefix = "{expected}"' in uv_text
    xdg_toml = home / ".config" / "uv" / "uv.toml"
    assert xdg_toml.is_file()
    env_text_full = (home / ".local-packages" / "env.sh").read_text(encoding="utf-8")
    assert "UV_CONFIG_FILE=" in env_text_full
    assert f"{expected}/shim" in env_text_full


def test_setup_opt_out_removes_managed_uv_toml(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    uv_dir = home / ".config" / "uv"
    uv_dir.mkdir(parents=True)
    uv_toml = uv_dir / "uv.toml"
    uv_toml.write_text(
        "# odh-persistent-packages\n[pip]\nprefix = \"/tmp/x\"\n",
        encoding="utf-8",
    )
    pers = home / ".local-packages"
    pers.mkdir()
    pers_toml = pers / "uv.toml"
    pers_toml.write_text(
        "# odh-persistent-packages\n[pip]\nprefix = \"/tmp/x\"\n",
        encoding="utf-8",
    )
    (pers / "shim").mkdir()
    (pers / "shim" / "uv").write_text("#!/bin/sh\n", encoding="utf-8")
    wrapper = tmp_path / "opt_out.sh"
    wrapper.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "export ODH_PERSISTENT_PACKAGES=0\n"
        f'export HOME="{home}"\n'
        f'source "{_SETUP}"\n'
        "printf 'xdg=%s\\n' \"$([ -f \"$HOME/.config/uv/uv.toml\" ] && printf 1 || printf 0)\"\n"
        "printf 'pers=%s\\n' \"$([ -f \"$HOME/.local-packages/uv.toml\" ] && printf 1 || printf 0)\"\n"
        "printf 'shim=%s\\n' \"$([ -e \"$HOME/.local-packages/shim/uv\" ] && printf 1 || printf 0)\"\n",
        encoding="utf-8",
    )
    wrapper.chmod(0o755)
    result = subprocess.run(
        ["bash", str(wrapper)],
        check=True,
        capture_output=True,
        text=True,
        env=os.environ.copy(),
    )
    assert "xdg=0" in result.stdout
    assert "pers=0" in result.stdout
    assert "shim=0" in result.stdout
    assert not uv_toml.exists()
    assert not pers_toml.exists()


def test_uv_shim_injects_prefix(tmp_path: Path) -> None:
    root = tmp_path / "prefix"
    bin_dir = root / "bin"
    bin_dir.mkdir(parents=True)
    # Fake real uv that prints its argv
    real = bin_dir / "uv"
    real.write_text(
        "#!/usr/bin/env bash\nprintf '%s\\n' \"$*\"\n",
        encoding="utf-8",
    )
    real.chmod(0o755)
    shim = tmp_path / "shim-uv"
    shim.write_text(_UV_SHIM.read_text(encoding="utf-8"), encoding="utf-8")
    shim.chmod(0o755)
    result = subprocess.run(
        [str(shim), "pip", "install", "cowsay"],
        check=True,
        capture_output=True,
        text=True,
        env={**os.environ, "ODH_PERSISTENT_PACKAGES_ROOT": str(root), "HOME": str(tmp_path)},
    )
    assert f"--prefix={root}" in result.stdout
    assert "pip install" in result.stdout or result.stdout.startswith("pip")
    # Already has --prefix → do not double-inject
    result2 = subprocess.run(
        [str(shim), "pip", "install", "--prefix=/other", "cowsay"],
        check=True,
        capture_output=True,
        text=True,
        env={**os.environ, "ODH_PERSISTENT_PACKAGES_ROOT": str(root), "HOME": str(tmp_path)},
    )
    assert result2.stdout.strip() == "pip install --prefix=/other cowsay"


def test_setup_profile_exports_reach_login_shell(tmp_path: Path) -> None:
    """JupyterLab terminals are login shells; they must pick up PIP_PREFIX."""
    home = tmp_path / "home"
    home.mkdir()
    bootstrap = tmp_path / "bootstrap.sh"
    bootstrap.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        f'export HOME="{home}"\n'
        "unset ODH_PERSISTENT_PACKAGES_ROOT PIP_PREFIX\n"
        f'source "{_SETUP}"\n',
        encoding="utf-8",
    )
    bootstrap.chmod(0o755)
    subprocess.run(["bash", str(bootstrap)], check=True, env=os.environ.copy())

    # Simulate JupyterLab terminal: login bash reads ~/.profile
    result = subprocess.run(
        [
            "bash",
            "-lc",
            'printf "pip_prefix=%s\\n" "${PIP_PREFIX-}"; '
            'case ":$PATH:" in *":$HOME/.local-packages/bin:"*) _ph=1 ;; *) _ph=0 ;; esac; '
            'printf "path_has_bin=%s\\n" "${_ph}"',
        ],
        check=True,
        capture_output=True,
        text=True,
        env={**os.environ, "HOME": str(home)},
    )
    parsed: dict[str, str] = {}
    for line in result.stdout.splitlines():
        key, _, value = line.partition("=")
        parsed[key] = value
    assert parsed["pip_prefix"] == str(home / ".local-packages")
    assert parsed["path_has_bin"] == "1"


def test_setup_opt_out_skips_exports(tmp_path: Path) -> None:
    out = _source_setup(tmp_path, opt_out=True)
    assert out["root"] == ""
    assert out["pip_prefix"] == ""
    assert out["path_has_bin"] == "0"


def test_setup_respects_root_override(tmp_path: Path) -> None:
    custom = tmp_path / "custom-prefix"
    home = tmp_path / "home"
    home.mkdir()
    wrapper = tmp_path / "override.sh"
    wrapper.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        f'export HOME="{home}"\n'
        f'export ODH_PERSISTENT_PACKAGES_ROOT="{custom}"\n'
        f'source "{_SETUP}"\n'
        "printf '%s\\n' \"${PIP_PREFIX}\"\n",
        encoding="utf-8",
    )
    wrapper.chmod(0o755)
    result = subprocess.run(
        ["bash", str(wrapper)],
        check=True,
        capture_output=True,
        text=True,
    )
    assert result.stdout.strip() == str(custom)
    assert (custom / "bin").is_dir()
    assert (custom / "lib/python3.12/site-packages").is_dir()


def test_helper_adds_existing_site_packages(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    py = f"python{sys.version_info.major}.{sys.version_info.minor}"
    lib = home / ".local-packages" / "lib" / py / "site-packages"
    lib.mkdir(parents=True)

    site = tmp_path / "image-site"
    site.mkdir()
    (site / "odh_workbench_persistent_packages.py").write_text(
        _HELPER.read_text(encoding="utf-8"), encoding="utf-8"
    )

    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("ODH_PERSISTENT_PACKAGES_ROOT", raising=False)
    monkeypatch.delenv("ODH_PERSISTENT_PACKAGES", raising=False)
    monkeypatch.syspath_prepend(str(site))
    sys.modules.pop("odh_workbench_persistent_packages", None)

    import odh_workbench_persistent_packages as bridge

    bridge.enable_persistent_site_packages()
    resolved = {str(Path(p).resolve()) for p in sys.path}
    assert str(lib.resolve()) in resolved
    sys.modules.pop("odh_workbench_persistent_packages", None)


def test_helper_opt_out(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "home"
    py = f"python{sys.version_info.major}.{sys.version_info.minor}"
    lib = home / ".local-packages" / "lib" / py / "site-packages"
    lib.mkdir(parents=True)

    site = tmp_path / "image-site"
    site.mkdir()
    (site / "odh_workbench_persistent_packages.py").write_text(
        _HELPER.read_text(encoding="utf-8"), encoding="utf-8"
    )

    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("ODH_PERSISTENT_PACKAGES", "0")
    monkeypatch.syspath_prepend(str(site))
    sys.modules.pop("odh_workbench_persistent_packages", None)

    import odh_workbench_persistent_packages as bridge

    bridge.enable_persistent_site_packages()
    resolved = {str(Path(p).resolve()) for p in sys.path}
    assert str(lib.resolve()) not in resolved
    sys.modules.pop("odh_workbench_persistent_packages", None)