"""access.cgi behavior and optional full-stack checks (podman + codeserver image).

Set CODE_SERVER_KERNELS_IMAGE to a codeserver image (e.g.
``quay.io/opendatahub/workbench-images:codeserver-ubi9-python-3.12-pr-2113``)
to run nginx -t and GET /api/kernels/ against a container with NB_PREFIX.
"""

from __future__ import annotations

import json
import os
import random
import shutil
import socket
import subprocess
import time
from pathlib import Path
from typing import Any

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
ACCESS_CGI_CONTAINER = "/ws/codeserver/ubi9-python-3.12/nginx/api/kernels/access.cgi"
UBI_PYTHON_IMAGE = "registry.access.redhat.com/ubi9/python-312:latest"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.mark.codeserver_stack
def test_access_cgi_outputs_json_with_fake_curl_in_podman() -> None:
    """GNU grep/date via UBI; PATH shadows curl with a fake healthz payload."""
    podman = shutil.which("podman")
    if not podman:
        pytest.skip("podman not available")

    script = rf"""
set -e
mkdir -p /tmp/bin
cat > /tmp/bin/curl << 'EOS'
#!/bin/bash
echo '{{"lastHeartbeat":1715000000123,"status":"alive"}}'
EOS
chmod +x /tmp/bin/curl
PATH=/tmp/bin:$PATH bash '{ACCESS_CGI_CONTAINER}'
"""
    proc = subprocess.run(
        [podman, "run", "--platform", "linux/amd64", "--rm", "-v", f"{PROJECT_ROOT}:/ws:Z", UBI_PYTHON_IMAGE, "bash", "-ec", script],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout
    lines = [ln for ln in proc.stdout.strip().splitlines() if ln.startswith("[{")]
    assert len(lines) == 1
    payload: list[dict[str, Any]] = json.loads(lines[0])
    assert payload[0]["id"] == "code-server"
    assert payload[0]["execution_state"] == "busy"
    assert "last_activity" in payload[0]


@pytest.mark.codeserver_stack
def test_access_cgi_last_heartbeat_zero_outputs_activity_in_podman() -> None:
    """Regression for RHAIENG-4344: millisecond 0 must not yield empty last_activity."""
    podman = shutil.which("podman")
    if not podman:
        pytest.skip("podman not available")

    script = rf"""
set -e
mkdir -p /tmp/bin
cat > /tmp/bin/curl << 'EOS'
#!/bin/bash
echo '{{"lastHeartbeat":0,"status":"alive"}}'
EOS
chmod +x /tmp/bin/curl
PATH=/tmp/bin:$PATH bash '{ACCESS_CGI_CONTAINER}'
"""
    proc = subprocess.run(
        [podman, "run", "--platform", "linux/amd64", "--rm", "-v", f"{PROJECT_ROOT}:/ws:Z", UBI_PYTHON_IMAGE, "bash", "-ec", script],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout
    lines = [ln for ln in proc.stdout.strip().splitlines() if ln.startswith("[{")]
    assert len(lines) == 1
    payload: list[dict[str, Any]] = json.loads(lines[0])
    assert payload[0]["last_activity"], "last_activity must not be empty when lastHeartbeat is 0"
    assert payload[0]["execution_state"] == "busy"


@pytest.mark.codeserver_stack
def test_access_cgi_nb_prefix_healthz_url_in_podman() -> None:
    """When NB_PREFIX is set, curl target includes prefix before codeserver/healthz."""
    podman = shutil.which("podman")
    if not podman:
        pytest.skip("podman not available")

    script = rf"""
set -e
mkdir -p /tmp/bin
cat > /tmp/bin/curl << 'EOS'
#!/bin/bash
if [[ "$*" != *"/notebook/ns/id/codeserver/healthz"* ]]; then
  echo "curl args: $*" >&2
  exit 1
fi
echo '{{"lastHeartbeat":1000,"status":"alive"}}'
EOS
chmod +x /tmp/bin/curl
export NB_PREFIX=/notebook/ns/id
PATH=/tmp/bin:$PATH bash '{ACCESS_CGI_CONTAINER}'
"""
    proc = subprocess.run(
        [podman, "run", "--platform", "linux/amd64", "--rm", "-v", f"{PROJECT_ROOT}:/ws:Z", UBI_PYTHON_IMAGE, "bash", "-ec", script],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout


@pytest.mark.codeserver_stack
def test_optional_codeserver_image_kernels_and_nginx_t() -> None:
    """Requires CODE_SERVER_KERNELS_IMAGE and podman; starts one container briefly."""
    image = os.environ.get("CODE_SERVER_KERNELS_IMAGE")
    podman = shutil.which("podman")
    if not image or not podman:
        pytest.skip("set CODE_SERVER_KERNELS_IMAGE and install podman to run")

    port = _free_port()
    name = f"codeserver-kernels-{random.randint(1000, 9999)}"
    nb_prefix = "/notebook/projectName/notebookId"
    notebook_args = (
        "--ServerApp.port=8888 --ServerApp.token='' --ServerApp.password='' "
        f"--ServerApp.base_url={nb_prefix} --ServerApp.quit_button=False"
    )
    try:
        subprocess.run(
            [
                podman,
                "run",
                "-d",
                "--platform",
                "linux/amd64",
                "--name",
                name,
                "-p",
                f"{port}:8888",
                "-e",
                f"NB_PREFIX={nb_prefix}",
                "-e",
                f"NOTEBOOK_ARGS={notebook_args}",
                image,
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=120,
        )

        deadline = time.monotonic() + 120
        body = ""
        while time.monotonic() < deadline:
            try:
                out = subprocess.run(
                    ["curl", "-sS", f"http://127.0.0.1:{port}/api/kernels/"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                    check=False,
                )
                if out.returncode == 0 and out.stdout.strip().startswith("["):
                    body = out.stdout
                    break
            except (subprocess.TimeoutExpired, OSError):
                pass
            time.sleep(3)
        assert body, "timed out waiting for /api/kernels/"

        parsed = json.loads(body)
        assert isinstance(parsed, list)
        assert parsed[0].get("id") == "code-server"
        assert "execution_state" in parsed[0]
        assert parsed[0].get("last_activity"), "last_activity should be populated for culling"

        subprocess.run(
            [podman, "exec", name, "nginx", "-t"],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
    finally:
        subprocess.run(
            [podman, "rm", "-f", name],
            capture_output=True,
            timeout=60,
            check=False,
        )
