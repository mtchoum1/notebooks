#!/usr/bin/env python3
"""Refresh commit SHAs in ``commit-latest.env`` and ``commit.env`` from container images.

Reads image references from:

- ``manifests/<variant>/base/params-latest.env`` → writes ``commit-latest.env`` (``-n`` / latest tags)
- ``manifests/<variant>/base/params.env`` → merges into ``commit.env`` (released / N-1 digests)

For each image, runs ``skopeo inspect --config`` and reads the ``vcs-ref`` label (first 7 hex chars).

Pipeline runtime images that only appear under ``params-latest.env`` (no matching row in
``params.env``) keep their existing ``commit.env`` lines unchanged.

When multiple variants are requested (e.g. ``--all``), each variant is processed in turn.
Failure in one variant does not skip the other; the process exits with a non-zero status
if any variant failed.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import pathlib
import re
import sys

import structlog

from ci.logging_config import configure_logging

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent

log = structlog.get_logger()

_PARAM_KEY_RE = re.compile(
    r"""
    ^(.+?)
    (
        -n
      |
        -\d+-\d+
    )
    $
    """,
    re.VERBOSE,
)


def _commit_key(base_key: str, suffix: str) -> str:
    return f"{base_key}-commit{suffix}"


async def get_image_vcs_ref(image_url: str, semaphore: asyncio.Semaphore) -> tuple[str, str | None]:
    """
    Asynchronously inspects a container image's configuration using skopeo
    and extracts the 'vcs-ref' label.

    Args:
        image_url: The full URL of the image to inspect
                   (e.g., 'quay.io/opendatahub/workbench-images@sha256:...').
        semaphore: Limits concurrent skopeo processes.

    Returns:
        A tuple containing the original image_url and the value of the 'vcs-ref'
        label if found, otherwise None.
    """
    # Using 'docker://' prefix is required for skopeo to identify the transport.
    full_image_url = f"docker://{image_url}"

    # Use 'inspect --config' which is much faster as it only fetches the config blob.
    command = [
        "skopeo",
        "inspect",
        "--override-os=linux",
        "--override-arch=amd64",
        "--retry-times=5",
        "--config",
        full_image_url,
    ]

    log.info("Starting config inspection", image_url=image_url)

    stdout, stderr, returncode = None, None, None
    try:
        async with semaphore:
            log.info("Semaphore acquired, starting skopeo inspect", image_url=image_url)
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await process.communicate()
            returncode = process.returncode

        if returncode != 0:
            log.error(
                "Skopeo command failed",
                image_url=image_url,
                returncode=returncode,
                stderr=stderr.decode().strip() if stderr else "",
            )
            return image_url, None

        if not stdout:
            log.error("Skopeo command returned success but stdout was empty", image_url=image_url)
            return image_url, None

        # Decode and parse the JSON output from stdout.
        # The output of 'inspect --config' is the image config JSON directly.
        image_config = json.loads(stdout.decode())
        vcs_ref = image_config.get("config", {}).get("Labels", {}).get("vcs-ref")

        if vcs_ref:
            log.info("Successfully found vcs-ref", image_url=image_url, vcs_ref=vcs_ref)
        else:
            log.warning("vcs-ref label not found", image_url=image_url)

        return image_url, vcs_ref

    except FileNotFoundError:
        log.error("The skopeo command was not found; install skopeo and ensure it is on PATH")
        return image_url, None
    except json.JSONDecodeError:
        log.error("Failed to parse skopeo output as JSON", image_url=image_url)
        if stdout:
            log.debug("Stdout from skopeo", image_url=image_url, stdout=stdout.decode(errors="replace"))
        return image_url, None
    except Exception:
        log.exception("Unexpected error while processing image", image_url=image_url)
        return image_url, None


async def _inspect_pairs(pairs: list[tuple[str, str]]) -> list[tuple[str, str | None]]:
    """
    Orchestrate concurrent inspection of multiple images (param key → digest URL pairs).

    Limits parallelism with a semaphore (same default concurrency as the historical main-branch script).
    """
    semaphore = asyncio.Semaphore(22)  # Limit concurrent skopeo processes
    tasks = [get_image_vcs_ref(url, semaphore) for _, url in pairs]
    results = await asyncio.gather(*tasks)
    return [(pairs[i][0], results[i][1]) for i in range(len(pairs))]


def _parse_env_lines(path: pathlib.Path) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for lineno, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(f"{path}:{lineno}: expected KEY=VALUE")
        k, _, v = line.partition("=")
        pairs.append((k.strip(), v.strip()))
    return pairs


def _write_env(path: pathlib.Path, rows: list[tuple[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wt", encoding="utf-8") as f:
        for key, val in sorted(rows, key=lambda kv: kv[0]):
            print(f"{key}={val}", file=f)


def _load_env_dict(path: pathlib.Path) -> dict[str, str]:
    d: dict[str, str] = {}
    if not path.is_file():
        return d
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        k, _, v = line.partition("=")
        d[k.strip()] = v.strip()
    return d


async def sync_commit_latest(variant: str) -> bool:
    """Refresh ``commit-latest.env`` from ``params-latest.env`` for one manifest variant."""
    base = PROJECT_ROOT / "manifests" / variant / "base"
    params_latest = base / "params-latest.env"
    out_path = base / "commit-latest.env"
    if not params_latest.is_file():
        log.error("Missing params-latest.env", path=str(params_latest))
        return False

    pairs: list[tuple[str, str]] = []
    for key, url in _parse_env_lines(params_latest):
        m = _PARAM_KEY_RE.match(key)
        if not m:
            log.warning("Skipping param key (unrecognized pattern)", key=key)
            continue
        if m.group(2) != "-n":
            log.warning("Expected only -n keys in params-latest.env", key=key)
            continue
        pairs.append((key, url))

    results = await _inspect_pairs([(k, u) for k, u in pairs])
    if any(v is None for _, v in results):
        log.error("Failed to get commit hash for some images", variant=variant)
        return False

    out_rows: list[tuple[str, str]] = []
    for (param_key, _url), vcs in zip(pairs, [r[1] for r in results], strict=True):
        if vcs is None:
            log.error("Unexpected None vcs-ref after validation", key=param_key)
            return False
        m = _PARAM_KEY_RE.match(param_key)
        if not m:
            log.error("Unexpected regex mismatch after validation", key=param_key)
            return False
        ck = _commit_key(m.group(1), m.group(2))
        out_rows.append((ck, vcs[:7]))

    _write_env(out_path, out_rows)
    log.info("Wrote commit-latest.env", path=str(out_path), lines=len(out_rows))
    return True


async def sync_commit_released(variant: str) -> bool:
    """Merge released-image vcs-ref SHAs into ``commit.env`` from ``params.env``."""
    base = PROJECT_ROOT / "manifests" / variant / "base"
    params_env = base / "params.env"
    out_path = base / "commit.env"
    if not params_env.is_file():
        log.warning("No params.env; skipping commit.env refresh", path=str(params_env))
        return True

    existing = _load_env_dict(out_path)
    pairs: list[tuple[str, str]] = []

    for key, url in _parse_env_lines(params_env):
        m = _PARAM_KEY_RE.match(key)
        if not m:
            log.warning("Skipping params.env key", key=key)
            continue
        suffix = m.group(2)
        if suffix == "-n":
            continue
        ck = _commit_key(m.group(1), suffix)
        pairs.append((ck, url))

    if not pairs:
        log.info("No non--n keys in params.env; leaving commit.env unchanged")
        return True

    results = await _inspect_pairs([(k, u) for k, u in pairs])
    if any(v is None for _, v in results):
        log.error("Failed to resolve vcs-ref for one or more released images", variant=variant)
        return False

    for (commit_key, _url), vcs in zip(pairs, [r[1] for r in results], strict=True):
        assert vcs is not None
        existing[commit_key] = vcs[:7]

    out_rows = [(k, existing[k]) for k in sorted(existing)]
    _write_env(out_path, out_rows)
    log.info("Wrote commit.env", path=str(out_path), keys=len(out_rows))
    return True


async def _run_variant(variant: str) -> bool:
    if not await sync_commit_latest(variant):
        return False
    return await sync_commit_released(variant)


async def main_async(variants: list[str]) -> int:
    exit_code = 0
    for v in variants:
        log.info("Syncing variant", variant=v)
        try:
            ok = await _run_variant(v)
        except Exception:
            log.error("Variant sync crashed", variant=v, exc_info=True)
            ok = False
        if not ok:
            log.error("Variant sync failed", variant=v)
            exit_code = 1
    return exit_code


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--variant",
        action="append",
        choices=("odh", "rhoai"),
        dest="variants",
        help="Manifest variant to refresh (repeat or use --all). Default: both.",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Refresh odh and rhoai (same as passing --variant odh --variant rhoai).",
    )
    args = parser.parse_args()
    if args.all:
        variants = ["odh", "rhoai"]
    elif args.variants:
        variants = args.variants
    else:
        variants = ["odh", "rhoai"]

    configure_logging()
    sys.exit(asyncio.run(main_async(variants)))


if __name__ == "__main__":
    main()
