"""Tests for NB-prefix nginx proxy snippet generation (codeserver idle culling)."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
TEMPLATE = (
    PROJECT_ROOT
    / "codeserver/ubi9-python-3.12/nginx/serverconf/proxy.conf.template_nbprefix"
)


def _render_proxy_conf_nbprefix(nb_prefix: str, base_url: str = "_") -> str:
    if not shutil.which("envsubst"):
        pytest.skip("envsubst (gettext) not installed")
    env = os.environ | {"NB_PREFIX": nb_prefix, "BASE_URL": base_url}
    proc = subprocess.run(
        ["envsubst", "${NB_PREFIX},${BASE_URL}"],
        input=TEMPLATE.read_bytes(),
        capture_output=True,
        env=env,
        check=True,
    )
    return proc.stdout.decode()


def test_proxy_conf_nbprefix_substitutes_nb_prefix() -> None:
    nb = "/notebook/projectName/notebookId"
    text = _render_proxy_conf_nbprefix(nb)
    assert nb in text
    assert "${NB_PREFIX}" not in text
    assert "proxy_pass http://localhost:8080;" in text
    assert "location /api/kernels/" in text


def test_proxy_conf_nbprefix_redirects_prefixed_kernels_to_canonical() -> None:
    nb = "/notebook/myproject/myid"
    text = _render_proxy_conf_nbprefix(nb)
    assert f"location = {nb}/api/kernels" in text
    assert "return 302 $custom_scheme://$http_host/api/kernels/;" in text
    assert f"return 302 $custom_scheme://$http_host{nb}/api/kernels/;" not in text


def test_proxy_conf_nbprefix_kernels_has_no_self_redirect() -> None:
    nb = "/notebook/a/b"
    text = _render_proxy_conf_nbprefix(nb)
    assert text.count(f"$http_host{nb}/api/kernels/") == 0
