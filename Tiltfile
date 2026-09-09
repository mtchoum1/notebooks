# Local dev loop for the Jupyter minimal notebook image.
#
# Prerequisites:
#   - tilt, k3d, kubectl, gmake, podman (machine running)
#   - hermetic prefetch: cachi2/output/ (see scripts/lockfile-generators/README.md)
#
# Quick start:
#   k3d cluster create tilt-demo --no-lb --servers 1
#   kubectl config use-context k3d-tilt-demo
#   tilt up
#
# On macOS with Podman (no Docker Desktop), tilt demo will not work; use tilt up
# directly against a k3d cluster you create with native k3d instead.

version_settings(constraint='>=0.22.2')

allow_k8s_contexts([
    'k3d-tilt-demo',
    'k3d-tilt-manual-test',
    'docker-desktop',
    'docker-for-desktop',
])

IMAGE_REGISTRY = 'quay.io/mtchoumi-aaet/workbench-images'
IMAGE_TAG = 'jupyter-minimal-ubi9-python-3.12-latest'
IMAGE_REF = IMAGE_REGISTRY + ':' + IMAGE_TAG
K3D_CLUSTER = os.getenv('K3D_CLUSTER', 'tilt-demo')
BUILD_ARCH = os.getenv('BUILD_ARCH', 'linux/arm64')
USE_PREBUILT = os.getenv('TILT_USE_PREBUILT_IMAGE', 'false').lower() in ('1', 'true', 'yes')

build_cmd = '''
set -euo pipefail
MAKE="$(command -v gmake || command -v make)"
$MAKE jupyter-minimal-ubi9-python-3.12 IMAGE_TAG=latest PUSH_IMAGES=yes BUILD_ARCH={build_arch}
podman image exists {image_ref} || {{ echo "Build did not produce {image_ref}"; exit 1; }}
k3d image import {image_ref} -c {cluster}
'''.format(build_arch=BUILD_ARCH, image_ref=IMAGE_REF, cluster=K3D_CLUSTER)

import_cmd = '''
set -euo pipefail
if ! podman image exists {image_ref}; then
  echo "Image {image_ref} not found locally; pulling published minimal image as a bootstrap..."
  podman pull quay.io/mtchoumi-aaet/workbench-images:jupyter-minimal-ubi9-python-3.12-latest
  podman tag quay.io/mtchoumi-aaet/workbench-images:jupyter-minimal-ubi9-python-3.12-latest {image_ref}
fi
k3d image import {image_ref} -c {cluster}
'''.format(image_ref=IMAGE_REF, cluster=K3D_CLUSTER)

local_resource(
    'jupyter-minimal-image',
    cmd=import_cmd if USE_PREBUILT else build_cmd,
    deps=[
        'Makefile',
        'jupyter/minimal/ubi9-python-3.12/',
        'jupyter/utils/',
        'base-images/utils/',
        'prefetch-input/',
        'cachi2/output/',
    ] if not USE_PREBUILT else [],
    auto_init=True,
)

k8s_yaml(kustomize('tilt/k8s'))

k8s_resource(
    'jupyter-minimal-ubi9-python-3-12-notebook',
    port_forwards='8888:8888',
    resource_deps=['jupyter-minimal-image'],
    labels=['notebook'],
)

if config.tilt_subcommand == 'up':
    print("""
\033[32mJupyter minimal notebook dev environment\033[0m

  Cluster context : {ctx}
  k3d cluster     : {cluster}
  Image           : {image}
  JupyterLab      : http://localhost:8888/lab

  Edit files under jupyter/minimal/ubi9-python-3.12/ and Tilt will rebuild the image.
  Set TILT_USE_PREBUILT_IMAGE=true to skip local builds and bootstrap from quay.

  Tear down: tilt down && k3d cluster delete {cluster}
""".format(
        ctx=k8s_context(),
        cluster=K3D_CLUSTER,
        image=IMAGE_REF,
    ))
