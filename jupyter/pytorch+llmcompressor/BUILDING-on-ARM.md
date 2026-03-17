# Building PyTorch+LLM Compressor images on ARM (e.g. Apple Silicon)

The CUDA notebook and runtime images use **torch/torchvision+cu128**, which only have **x86_64** wheels. On an ARM machine you must build for **linux/amd64** (emulation), which can be slow and sometimes trigger QEMU segfaults.

## What we do to improve stability

- **Lower concurrency** in the image: `UV_CONCURRENT_DOWNLOADS=2` and `UV_CONCURRENT_INSTALLS=1` are set in the Dockerfiles to reduce memory and CPU pressure under QEMU and lower the chance of `qemu: uncaught target signal 11 (Segmentation fault)`.

## What you can do on your ARM device

1. **Force amd64 and give the builder more resources**
   ```bash
   make cuda-jupyter-pytorch-llmcompressor-ubi9-python-3.12 -e BUILD_ARCH=linux/amd64
   ```
   - In Docker Desktop or Podman: increase **memory** (e.g. 8 GB+) and **CPUs** for the engine so the emulated build has enough headroom.

2. **Use a remote x86_64 builder (recommended)**
   - **Docker Buildx** with a remote amd64 builder:
     ```bash
     docker buildx create --name amd64-builder --platform linux/amd64 --use
     docker buildx build --platform linux/amd64 -f jupyter/pytorch+llmcompressor/ubi9-python-3.12/Dockerfile.cuda ...
     ```
   - Or run the same `make` target on **CI** or an **x86_64** machine/VM so the build is native and avoids QEMU entirely.

3. **If you only need to test the stack (no GPU)**  
   A native **CPU-only** image for ARM would require a separate Dockerfile and lock file using PyTorch’s CPU index; that variant is not provided here. For production CUDA use, build on x86_64.

## Summary

| Goal                         | Approach                                      |
|-----------------------------|-----------------------------------------------|
| Build CUDA image on ARM Mac | `BUILD_ARCH=linux/amd64`, more RAM/CPU, retry if QEMU segfaults |
| Reliable CUDA builds         | Build on x86_64 (CI or remote builder)        |
