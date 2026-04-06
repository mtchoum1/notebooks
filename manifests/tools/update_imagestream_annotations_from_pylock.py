#!/usr/bin/env -S uv run --project=../..
"""Refresh ImageStream tag annotations from local pylock.toml (or uv.lock.d/pylock.*.toml).

Updates ``opendatahub.io/notebook-python-dependencies`` and syncs ``opendatahub.io/notebook-software``
entries that are also listed in the dependency array (plus Python), using the same name
normalization and skip rules as ``tests/test_main.py::test_image_pyprojects``.

**Scope:** By default this targets the **recommended** tag (or the only tag). Older tags
describe past releases; refreshing them from the **current** tree lockfile can misrepresent
those images unless the lock matches that release line.

Use ``--lock-git-ref <tag-or-sha>`` with ``--tag-index 1`` (N-1), ``2`` (N-2), etc. to fill
annotations from the pylock file at that git revision (``git show ref:path``). Local lock
choice matches ``tests/test_main.py::test_image_pyprojects`` (sorted ``uv.lock.d/pylock.*.toml``,
else root ``pylock.toml``). For ``git show``, the same paths are tried in order, then
``pylock.toml`` again as a fallback when an older tag never had per-flavor locks under
``uv.lock.d/``. If those paths are missing at the ref, the script also tries the same tree under
``*-python-3.11`` when the image dir is ``*-python-3.12`` (locks often lived only under the
older folder in early tags).

Usage:
    uv run manifests/tools/update_imagestream_annotations_from_pylock.py \\
        --image-dir jupyter/datascience/ubi9-python-3.12
    uv run manifests/tools/update_imagestream_annotations_from_pylock.py --all
    uv run manifests/tools/update_imagestream_annotations_from_pylock.py --check --all
    uv run manifests/tools/update_imagestream_annotations_from_pylock.py --all \\
        --tag-index 1 --lock-git-ref rhoai-3.3
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import packaging.markers
import packaging.version
import tomllib
from ruamel.yaml import YAML

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests.manifests import (  # noqa: E402
    NotebookMetadata,
    NotebookType,
    extract_metadata_from_path,
    get_source_of_truth_filepath,
)

# Mirrors tests/test_main.py (manifest-python-dependencies checks).
_MANIFEST_TO_PYLOCK_TRANSLATION: dict[str, str] = {
    "LLM-Compressor": "llmcompressor",
    "PyTorch": "torch",
    "ROCm-PyTorch": "torch",
    "Sklearn-onnx": "skl2onnx",
    "Nvidia-CUDA-CU12-Bundle": "nvidia-cuda-runtime-cu12",
    "MySQL Connector/Python": "mysql-connector-python",
    "Kafka-Python": "kafka-python-ng",
    "ROCm-TensorFlow": "tensorflow-rocm",
}

_MANIFEST_TO_PYLOCK_CAPITALIZATION: frozenset[str] = frozenset(
    {
        "Accelerate",
        "Boto3",
        "Codeflare-SDK",
        "Datasets",
        "Feast",
        "JupyterLab",
        "Kafka-Python-ng",
        "Kfp",
        "Kubeflow-Training",
        "Matplotlib",
        "Numpy",
        "Odh-Elyra",
        "Pandas",
        "Psycopg",
        "PyMongo",
        "Pyodbc",
        "Scikit-learn",
        "Scipy",
        "TensorFlow",
        "Tensorboard",
        "Torch",
        "Transformers",
        "TrustyAI",
        "TensorFlow-ROCm",
        "MLflow",
    }
)

_WORKBENCH_ONLY_PACKAGES: frozenset[str] = frozenset(
    {
        "Kfp",
        "JupyterLab",
        "Odh-Elyra",
        "Kubeflow-Training",
        "Codeflare-SDK",
    }
)


def _display_name_to_pylock_name(name: str) -> str:
    if name in _MANIFEST_TO_PYLOCK_TRANSLATION:
        return _MANIFEST_TO_PYLOCK_TRANSLATION[name]
    if name in _MANIFEST_TO_PYLOCK_CAPITALIZATION:
        return name.lower()
    return name


def _locked_major_minor(locked_version: str) -> str:
    parsed = packaging.version.Version(locked_version)
    return f"{parsed.major}.{parsed.minor}"


def _skip_dep_update(metadata: NotebookMetadata, name: str) -> bool:
    if name in _WORKBENCH_ONLY_PACKAGES and metadata.type == NotebookType.RUNTIME:
        return True
    # Matches tests/test_main.py: llmcompressor image does not ship codeflare-sdk in pylock.
    if metadata.scope == "pytorch+llmcompressor" and name == "Codeflare-SDK":
        return True
    if (
        metadata.scope == "pytorch+llmcompressor"
        and metadata.type == NotebookType.RUNTIME
        and name == "LLM-Compressor"
    ):
        return True
    if name == "rstudio-server":
        return True
    return False


def _lock_path_candidates(directory: Path) -> list[Path]:
    """Lock paths to try, in order — aligned with ``test_image_pyprojects`` / ``test_main.py``.

    If ``uv.lock.d`` has any ``pylock.*.toml``, only those are used (sorted; first wins for
    local resolution). Root ``pylock.toml`` is not mixed in: it can be a different aggregate
    (e.g. ROCm tree) and would shadow the flavor lock that actually ships in the image.
    """
    lock_dir = directory / "uv.lock.d"
    if lock_dir.is_dir():
        variants = sorted(lock_dir.glob("pylock.*.toml"))
        if variants:
            return variants
    return [directory / "pylock.toml"]


def _resolve_default_lock_path(directory: Path) -> Path:
    for path in _lock_path_candidates(directory):
        if path.is_file():
            return path
    rel_tried = [p.relative_to(ROOT).as_posix() for p in _lock_path_candidates(directory)]
    raise FileNotFoundError(f"No pylock found under {directory.relative_to(ROOT)} (tried: {rel_tried})")


def _load_pylock_path(directory: Path) -> tuple[Path, dict[str, Any]]:
    path = _resolve_default_lock_path(directory)
    doc = tomllib.loads(path.read_text())
    return path, doc


def _lock_paths_to_try_for_git_ref(directory: Path) -> list[Path]:
    """Paths to ``git show`` for a lockfile, in order.

    Candidates are derived from the **current** tree (same as local resolution). Older tags
    often lack the same ``uv.lock.d/pylock.*.toml`` paths; append the image directory
    ``pylock.toml`` so ``--lock-git-ref`` can resolve layouts that only had a root lock.
    """
    candidates = list(_lock_path_candidates(directory))
    root = directory / "pylock.toml"
    if root not in candidates:
        candidates.append(root)
    return candidates


def _git_ref_image_directory_fallbacks(directory: Path) -> list[Path]:
    """Image directories to try with ``git show`` when the ref predates the current folder.

    Many upstream tags only had ``*-python-3.11`` while the repo now uses ``*-python-3.12``.
    """
    ordered: list[Path] = [directory]
    name = directory.name
    if name.endswith("-python-3.12"):
        prev = directory.with_name(name.replace("-python-3.12", "-python-3.11", 1))
        if prev != directory:
            ordered.append(prev)
    return ordered


def _load_pylock_doc_from_git_ref(directory: Path, git_ref: str) -> dict[str, Any]:
    errors: list[str] = []
    for base in _git_ref_image_directory_fallbacks(directory):
        for path in _lock_paths_to_try_for_git_ref(base):
            rel = path.relative_to(ROOT)
            rel_s = rel.as_posix()
            proc = subprocess.run(
                ["git", "show", f"{git_ref}:{rel_s}"],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            if proc.returncode == 0:
                return tomllib.loads(proc.stdout)
            err = proc.stderr.strip() or proc.stdout.strip() or f"exit {proc.returncode}"
            errors.append(f"{git_ref}:{rel_s}: {err}")
    raise RuntimeError("No lockfile at git ref; tried:\n" + "\n".join(errors))


def _pylock_package_map_from_doc(doc: dict[str, Any], python_xy: str) -> dict[str, dict[str, Any]]:
    marker_env = {
        "python_full_version": f"{python_xy}.0",
        "implementation_name": "cpython",
        "sys_platform": "linux",
    }
    packages: dict[str, dict[str, Any]] = {}
    for p in doc.get("packages", []):
        if "marker" in p and not packaging.markers.Marker(p["marker"]).evaluate(marker_env):
            continue
        name = p.get("name")
        if name in packages:
            raise ValueError(f"Duplicate package {name!r} in pylock after marker filtering")
        packages[name] = p
    return packages


def _pylock_package_map(
    directory: Path,
    python_xy: str,
    *,
    lock_doc: dict[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    if lock_doc is not None:
        return _pylock_package_map_from_doc(lock_doc, python_xy)
    _path, doc = _load_pylock_path(directory)
    return _pylock_package_map_from_doc(doc, python_xy)


def _parse_python_xy(directory: Path) -> str:
    try:
        _ubi, _lang, python = directory.name.split("-")
    except ValueError as e:
        raise ValueError(f"Expected directory name like ubi9-python-3.12, got {directory.name!r}") from e
    return python


def _select_tag(
    tags: list[dict[str, Any]],
    *,
    tag_index: int | None,
) -> tuple[int, dict[str, Any]]:
    if tag_index is not None:
        if tag_index < 0 or tag_index >= len(tags):
            raise IndexError(f"tag index {tag_index} out of range (0..{len(tags) - 1})")
        return tag_index, tags[tag_index]
    for i, t in enumerate(tags):
        ann = t.get("annotations") or {}
        if ann.get("opendatahub.io/workbench-image-recommended") == "true":
            return i, t
    if not tags:
        raise ValueError("ImageStream has no tags")
    return 0, tags[0]


def _sync_software_with_deps(
    software: list[dict[str, Any]],
    dep_versions: dict[str, str],
    python_v: str,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for s in software:
        name = s.get("name")
        ver = s.get("version")
        if name == "Python":
            out.append({"name": "Python", "version": python_v})
        elif name in ("R", "code-server", "CUDA", "ROCm"):
            out.append({"name": name, "version": ver})
        elif name in dep_versions:
            out.append({"name": name, "version": dep_versions[name]})
        else:
            out.append(dict(s))
    return out


def _build_new_dependencies(
    existing: list[dict[str, str]],
    pylock_packages: dict[str, dict[str, Any]],
    metadata: NotebookMetadata,
) -> list[dict[str, str]]:
    new_deps: list[dict[str, str]] = []
    for d in existing:
        name = d["name"]
        if _skip_dep_update(metadata, name):
            new_deps.append(dict(d))
            continue
        norm = _display_name_to_pylock_name(name)
        pkg = pylock_packages.get(norm)
        if pkg is None:
            raise KeyError(f"No pylock package for manifest name {name!r} ({norm=})")
        locked = pkg.get("version")
        if locked is None:
            raise KeyError(f"pylock entry for {norm!r} has no version")
        new_deps.append({"name": name, "version": _locked_major_minor(locked)})
    return new_deps


def _json_block_payload(obj: Any) -> str:
    """Serialize JSON for YAML `|`-block annotations.

    Lists of ``{"name": ..., "version": ...}`` objects are written as one compact object per line,
    e.g. ``{"name": "MySQL Connector/Python", "version": "9.4"}``, matching common ImageStream style.
    Other values use pretty-printed JSON.
    """
    if (
        isinstance(obj, list)
        and obj
        and all(isinstance(x, dict) and set(x.keys()) == {"name", "version"} for x in obj)
    ):
        lines: list[str] = ["["]
        for i, x in enumerate(obj):
            sep = ", "  # spaces after commas, like hand-edited manifests
            one = json.dumps(
                {"name": x["name"], "version": x["version"]},
                separators=(sep, ": "),
            )
            suffix = "," if i < len(obj) - 1 else ""
            lines.append(f"  {one}{suffix}")
        lines.append("]")
        return "\n".join(lines) + "\n"
    return json.dumps(obj, indent=2) + "\n"


def _update_imagestream_tag(
    tag: dict[str, Any],
    *,
    new_deps: list[dict[str, str]],
    python_xy: str,
) -> None:
    ann = tag.setdefault("annotations", {})
    python_v = f"v{python_xy}"
    sw = json.loads(ann["opendatahub.io/notebook-software"])
    dep_versions = {d["name"]: d["version"] for d in new_deps}
    new_sw = _sync_software_with_deps(sw, dep_versions, python_v)
    ann["opendatahub.io/notebook-software"] = _json_block_payload(new_sw)
    ann["opendatahub.io/notebook-python-dependencies"] = _json_block_payload(new_deps)


def _load_yaml_documents(path: Path) -> tuple[YAML, list[Any]]:
    y = YAML()
    y.preserve_quotes = True
    y.width = 4096
    with path.open(encoding="utf-8") as f:
        docs = list(y.load_all(f))
    return y, docs


def _save_yaml_documents(yaml: YAML, path: Path, docs: list[Any]) -> None:
    with path.open("w", encoding="utf-8") as f:
        yaml.dump_all(docs, f)


def _find_imagestream_doc(docs: list[Any]) -> tuple[int, Any]:
    for i, doc in enumerate(docs):
        if doc is not None and doc.get("kind") == "ImageStream":
            return i, doc
    raise ValueError("No ImageStream document found")


def update_manifest_file(
    manifest_path: Path,
    directory: Path,
    *,
    tag_index: int | None,
    check_only: bool,
    lock_doc: dict[str, Any] | None = None,
) -> bool | None:
    """Returns True if modified (or would be), False if unchanged, None if skipped.

    ``None`` is returned when ``tag_index`` is set but the ImageStream has fewer tags
    (e.g. ``--tag-index 1`` with a single-tag ODH manifest).
    """
    metadata = extract_metadata_from_path(directory)
    python_xy = _parse_python_xy(directory)
    pylock_packages = _pylock_package_map(directory, python_xy, lock_doc=lock_doc)

    y, docs = _load_yaml_documents(manifest_path)
    _is_idx, doc = _find_imagestream_doc(docs)
    tags = doc["spec"]["tags"]
    if tag_index is not None and not (0 <= tag_index < len(tags)):
        return None
    idx, tag = _select_tag(tags, tag_index=tag_index)
    ann = tag.get("annotations") or {}
    if "opendatahub.io/notebook-python-dependencies" not in ann or "opendatahub.io/notebook-software" not in ann:
        raise ValueError(f"{manifest_path}: selected tag {idx} missing notebook annotation JSON")

    existing_deps = json.loads(ann["opendatahub.io/notebook-python-dependencies"])
    new_deps = _build_new_dependencies(existing_deps, pylock_packages, metadata)

    before_deps = json.dumps(existing_deps, sort_keys=True)
    after_deps = json.dumps(new_deps, sort_keys=True)
    before_sw = ann["opendatahub.io/notebook-software"]
    _update_imagestream_tag(tag, new_deps=new_deps, python_xy=python_xy)
    after_sw = ann["opendatahub.io/notebook-software"]

    changed = before_deps != after_deps or before_sw != after_sw
    if check_only:
        return changed
    if changed:
        _save_yaml_documents(y, manifest_path, docs)
    return changed


def _iter_image_dirs() -> list[Path]:
    out: list[Path] = []
    for pyproject in sorted(ROOT.glob("**/pyproject.toml")):
        d = pyproject.parent
        try:
            _ubi, _lang, _python = d.name.split("-")
        except ValueError:
            continue
        if not (d / "pylock.toml").is_file() and not (d / "uv.lock.d").is_dir():
            continue
        try:
            get_source_of_truth_filepath(ROOT / "manifests" / "odh", extract_metadata_from_path(d))
        except ValueError:
            continue
        out.append(d)
    return out


def _resolve_manifest_paths(directory: Path, odh: bool, rhoai: bool) -> list[Path]:
    paths: list[Path] = []
    meta = extract_metadata_from_path(directory)
    if odh:
        paths.append(get_source_of_truth_filepath(ROOT / "manifests" / "odh", meta))
    if rhoai:
        paths.append(get_source_of_truth_filepath(ROOT / "manifests" / "rhoai", meta))
    return paths


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--image-dir",
        type=Path,
        help="Image directory containing pyproject.toml (e.g. jupyter/datascience/ubi9-python-3.12)",
    )
    p.add_argument("--all", action="store_true", help="Process every image directory with a pylock")
    p.add_argument(
        "--tag-index",
        type=int,
        default=None,
        help=(
            "0-based ImageStream tag index (default: recommended tag, or first tag). "
            "Manifests with fewer tags are skipped (no error)."
        ),
    )
    p.add_argument(
        "--lock-git-ref",
        type=str,
        default=None,
        metavar="REF",
        help="Load pylock via git show REF:<default-lock-path> (requires explicit --tag-index; use for N-1, N-2, …)",
    )
    p.add_argument(
        "--lock-file",
        type=Path,
        default=None,
        help="Use this pylock.toml file instead of the image directory default (for --image-dir only)",
    )
    p.add_argument("--check", action="store_true", help="Exit 1 if any file would change")
    p.add_argument("--odh-only", action="store_true", help="Only update manifests/odh")
    p.add_argument("--rhoai-only", action="store_true", help="Only update manifests/rhoai")
    args = p.parse_args()
    odh = not args.rhoai_only
    rhoai = not args.odh_only
    if args.odh_only and args.rhoai_only:
        p.error("cannot combine --odh-only and --rhoai-only")

    if bool(args.image_dir) == bool(args.all):
        p.error("specify exactly one of --image-dir or --all")

    if args.lock_git_ref and args.tag_index is None:
        p.error("--lock-git-ref requires an explicit --tag-index (e.g. 1 for N-1, 2 for N-2)")
    if args.lock_file and args.all:
        p.error("--lock-file cannot be used with --all")
    if args.lock_file and args.lock_git_ref:
        p.error("cannot combine --lock-file and --lock-git-ref")

    dirs: list[Path]
    if args.all:
        dirs = _iter_image_dirs()
    else:
        assert args.image_dir is not None
        dirs = [(ROOT / args.image_dir).resolve()]

    any_change = False
    for directory in dirs:
        lock_doc: dict[str, Any] | None = None
        if args.lock_git_ref:
            try:
                lock_doc = _load_pylock_doc_from_git_ref(directory, args.lock_git_ref)
            except (OSError, RuntimeError, tomllib.TOMLDecodeError) as e:
                print(f"error {directory.relative_to(ROOT)}: {e}", file=sys.stderr)
                return 1
        elif args.lock_file is not None:
            lf = args.lock_file if args.lock_file.is_absolute() else (ROOT / args.lock_file)
            try:
                lock_doc = tomllib.loads(lf.read_text())
            except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as e:
                print(f"error reading --lock-file {lf}: {e}", file=sys.stderr)
                return 1

        for mf in _resolve_manifest_paths(directory, odh, rhoai):
            if not mf.is_file():
                print(f"skip (missing): {mf.relative_to(ROOT)}", file=sys.stderr)
                continue
            try:
                changed = update_manifest_file(
                    mf,
                    directory,
                    tag_index=args.tag_index,
                    check_only=args.check,
                    lock_doc=lock_doc,
                )
            except (ValueError, KeyError, json.JSONDecodeError) as e:
                print(f"error {mf.relative_to(ROOT)}: {e}", file=sys.stderr)
                return 1
            rel = mf.relative_to(ROOT)
            if changed is None:
                print(
                    f"skip (tag index {args.tag_index} not available; "
                    f"fewer tags in ImageStream): {rel}",
                    file=sys.stderr,
                )
                continue
            if changed:
                any_change = True
                print(f"{'would update' if args.check else 'updated'} {rel}")
            else:
                print(f"unchanged {rel}")

    if args.check and any_change:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
