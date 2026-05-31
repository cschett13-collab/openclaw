#!/usr/bin/env python3
"""
verify_gpu.py — Standalone smoke test that the RTX 5090 is actually usable.

Unlike `llm.invoke("verify the GPU")` (which only returns text), this really:
  1. checks PyTorch sees the GPU and runs a kernel on it (sm_120),
  2. compiles a tiny CUDA program with `nvcc -arch=sm_120` and runs it,
  3. (optional) confirms PyNvVideoCodec imports for GPU video work.

Exit code 0 = all required checks passed. Run after setup_rtx5090.sh.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

CUDA_SRC = r"""
#include <cstdio>
__global__ void add(const float* a, const float* b, float* c, int n) {
    int i = blockIdx.x * blockDim.x + threadIdx.x;
    if (i < n) c[i] = a[i] + b[i];
}
int main() {
    const int n = 1 << 20;            // 1M elements
    size_t bytes = n * sizeof(float);
    float *a, *b, *c;
    cudaMallocManaged(&a, bytes);
    cudaMallocManaged(&b, bytes);
    cudaMallocManaged(&c, bytes);
    for (int i = 0; i < n; ++i) { a[i] = 1.0f; b[i] = 2.0f; }
    int threads = 256, blocks = (n + threads - 1) / threads;
    add<<<blocks, threads>>>(a, b, c, n);
    cudaError_t err = cudaDeviceSynchronize();
    if (err != cudaSuccess) { printf("CUDA error: %s\n", cudaGetErrorString(err)); return 1; }
    bool ok = true;
    for (int i = 0; i < n; ++i) if (c[i] != 3.0f) { ok = false; break; }
    printf("%s\n", ok ? "CUDA vector add OK (1M floats)" : "CUDA result mismatch");
    cudaFree(a); cudaFree(b); cudaFree(c);
    return ok ? 0 : 1;
}
"""


def check_torch() -> bool:
    print("== PyTorch / CUDA ==")
    try:
        import torch
    except ImportError:
        print("  FAIL: torch not installed (run setup_rtx5090.sh).")
        return False
    print(f"  torch {torch.__version__}, cuda build {torch.version.cuda}")
    if not torch.cuda.is_available():
        print("  FAIL: torch.cuda.is_available() == False (driver/WSL passthrough?).")
        return False
    cap = torch.cuda.get_device_capability(0)
    print(f"  device: {torch.cuda.get_device_name(0)}  sm_{cap[0]}{cap[1]}")
    try:
        x = torch.randn(2048, 2048, device="cuda")
        ok = bool((x @ x).sum().isfinite())
        print(f"  matmul on GPU: {'OK' if ok else 'FAIL'}")
        return ok
    except Exception as e:  # noqa: BLE001 - report any kernel-launch failure
        print(f"  FAIL: GPU op raised: {e}")
        return False


def check_nvcc() -> bool:
    print("== Native CUDA (nvcc -arch=sm_120) ==")
    if not shutil.which("nvcc"):
        print("  FAIL: nvcc not on PATH (install CUDA Toolkit 12.8+).")
        return False
    with tempfile.TemporaryDirectory() as d:
        src = Path(d) / "vecadd.cu"
        out = Path(d) / "vecadd"
        src.write_text(CUDA_SRC)
        c = subprocess.run(["nvcc", "-O2", "-arch=sm_120", str(src), "-o", str(out)],
                           capture_output=True, text=True)
        if c.returncode != 0:
            print(f"  FAIL compile:\n{c.stderr.strip()}")
            return False
        r = subprocess.run([str(out)], capture_output=True, text=True, timeout=60)
        print(f"  {r.stdout.strip() or r.stderr.strip()}")
        return r.returncode == 0


def check_video() -> bool:
    print("== Video (PyNvVideoCodec, optional) ==")
    try:
        import PyNvVideoCodec  # noqa: F401
        print("  OK: PyNvVideoCodec importable (NVENC/NVDEC available).")
        return True
    except ImportError:
        print("  skip: PyNvVideoCodec not installed (optional).")
        return True  # optional — never fails the suite


def main() -> int:
    required = [check_torch(), check_nvcc()]
    check_video()
    ok = all(required)
    print("\n" + ("ALL REQUIRED CHECKS PASSED ✅" if ok else "SOME CHECKS FAILED ❌"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
