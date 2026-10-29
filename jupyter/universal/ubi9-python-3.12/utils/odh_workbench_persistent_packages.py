"""Bridge PVC-backed pip --prefix installs into the default workbench interpreter.

Imported from ``odh_workbench_persistent_packages.pth`` in the image
site-packages. Packages land under ``$HOME/.local-packages`` (PVC); the image
``/opt/app-root`` tree stays read-mostly / ephemeral.

Image site-packages stay ahead on ``sys.path`` (``addsitedir`` appends) so a
user install cannot shadow Jupyter or other image-critical packages. Use a
nested venv when you need different versions of image-provided libraries.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from site import addsitedir


def _persistent_root() -> Path:
    override = os.environ.get("ODH_PERSISTENT_PACKAGES_ROOT")
    if override:
        return Path(override)
    home = os.environ.get("HOME", "/opt/app-root/src")
    return Path(home) / ".local-packages"


def enable_persistent_site_packages() -> None:
    if os.environ.get("ODH_PERSISTENT_PACKAGES", "1") == "0":
        return

    root = _persistent_root()
    py = f"python{sys.version_info.major}.{sys.version_info.minor}"
    for sub in ("lib", "lib64"):
        site_packages = root / sub / py / "site-packages"
        # setup-persistent-packages.sh creates these dirs at workbench start so
        # the first pip install is importable without a kernel restart. Skip if
        # missing so image build / runtime pods do not write under $HOME.
        if site_packages.is_dir():
            addsitedir(str(site_packages))


enable_persistent_site_packages()
