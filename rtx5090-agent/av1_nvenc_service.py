#!/usr/bin/env python3
"""
av1_nvenc_service.py — Real-time AV1 encoding on the RTX 5090's NVENC engine,
with measured throughput and before/after GPU telemetry.

This is the "first real task" deliverable: not a claim that it's fast, but a
harness that MEASURES it. It encodes frames to AV1 via PyNvVideoCodec (NVENC)
and reports frames, wall-clock time, achieved FPS, output bitrate, and the
encoder-utilization telemetry sampled during the run.

Blackwell (RTX 5090) has a dedicated AV1 NVENC engine, so codec="av1" is the
point of this demo. API per NVIDIA's PyNvVideoCodec Programming Guide:
  https://docs.nvidia.com/video-technologies/pynvvideocodec/pynvc-api-prog-guide/index.html

Usage:
    # Encode synthetic 1080p frames (no input file needed):
    python av1_nvenc_service.py --frames 600 --width 1920 --height 1080

    # Re-encode a real clip to AV1:
    python av1_nvenc_service.py --input clip.mp4 --output out.av1

Requires an NVIDIA GPU + driver; will not run on CPU/macOS.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import threading
import time
from pathlib import Path

import numpy as np


# --- telemetry ------------------------------------------------------------
def gpu_snapshot() -> dict[str, str]:
    """One nvidia-smi sample: gpu/encoder util, mem used, temp."""
    query = "utilization.gpu,utilization.encoder,memory.used,temperature.gpu"
    try:
        r = subprocess.run(
            ["nvidia-smi", f"--query-gpu={query}", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10, check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return {}
    if r.returncode != 0:
        return {}
    g, e, m, t = (v.strip() for v in r.stdout.strip().split(","))
    return {"gpu_util_%": g, "enc_util_%": e, "mem_used_MiB": m, "temp_C": t}


class EncoderUtilSampler(threading.Thread):
    """Polls encoder utilization in the background so we can report the PEAK
    NVENC load during the encode, not just endpoints."""

    def __init__(self, interval: float = 0.2):
        super().__init__(daemon=True)
        self.interval = interval
        self._stop = threading.Event()
        self.peak_enc = 0
        self.samples = 0

    def run(self) -> None:
        while not self._stop.is_set():
            snap = gpu_snapshot()
            try:
                self.peak_enc = max(self.peak_enc, int(snap.get("enc_util_%", "0")))
            except ValueError:
                pass
            self.samples += 1
            time.sleep(self.interval)

    def stop(self) -> None:
        self._stop.set()
        self.join(timeout=2)


# --- frame sources --------------------------------------------------------
def synthetic_nv12_frames(n: int, w: int, h: int):
    """Yield `n` NV12 frames (a drifting gradient) as numpy uint8 arrays.
    NV12 = Y plane (h*w) + interleaved UV plane (h/2 * w)."""
    y_size = w * h
    uv_size = (w * h) // 2
    base_y = np.tile(np.linspace(0, 255, w, dtype=np.uint8), (h, 1))
    for i in range(n):
        y = ((base_y.astype(np.int16) + i) % 256).astype(np.uint8).ravel()
        uv = np.full(uv_size, 128, dtype=np.uint8)  # neutral chroma
        yield np.concatenate([y, uv])


def decoded_frames(path: str):
    """Yield frames decoded from `path` (NVDEC) for re-encode."""
    import PyNvVideoCodec as nvc
    dec = nvc.SimpleDecoder(path, gpu_id=0, use_device_memory=False)
    for i in range(len(dec)):
        yield dec[i]


# --- main encode loop -----------------------------------------------------
def run(args: argparse.Namespace) -> int:
    try:
        import PyNvVideoCodec as nvc
    except ImportError:
        print("PyNvVideoCodec not installed (needs NVIDIA GPU). "
              "`pip install PyNvVideoCodec`.", file=sys.stderr)
        return 1

    if args.input:
        frames = decoded_frames(args.input)
        total = "?"
        # probe size from first decoded frame
        import PyNvVideoCodec as _nvc
        probe = _nvc.SimpleDecoder(args.input, gpu_id=0, use_device_memory=False)
        first = probe[0]
        import torch
        t = torch.from_dlpack(first)
        h, w = int(t.shape[-2]), int(t.shape[-1])
        from_cpu = False
    else:
        w, h, n = args.width, args.height, args.frames
        frames = synthetic_nv12_frames(n, w, h)
        total = n
        from_cpu = True

    encoder = nvc.CreateEncoder(
        width=w, height=h, format="NV12",
        usecpuinputbuffer=from_cpu, gpu_id=0,
        codec="av1", bitrate=args.bitrate,
    )

    before = gpu_snapshot()
    sampler = EncoderUtilSampler()
    sampler.start()

    out_path = Path(args.output)
    written_bytes = 0
    count = 0
    t0 = time.perf_counter()
    with out_path.open("wb") as out:
        for frame in frames:
            bitstream = encoder.Encode(frame)
            if bitstream:
                b = bytearray(bitstream)
                out.write(b)
                written_bytes += len(b)
            count += 1
        tail = encoder.EndEncode()
        if tail:
            b = bytearray(tail)
            out.write(b)
            written_bytes += len(b)
    elapsed = time.perf_counter() - t0

    sampler.stop()
    after = gpu_snapshot()

    fps = count / elapsed if elapsed > 0 else 0.0
    mbps = (written_bytes * 8 / 1e6) / elapsed if elapsed > 0 else 0.0
    print("\n=== AV1 NVENC encode report ===")
    print(f"  codec            : AV1 (NVENC)")
    print(f"  resolution       : {w}x{h}")
    print(f"  frames encoded   : {count} (requested {total})")
    print(f"  wall time        : {elapsed:.3f} s")
    print(f"  throughput       : {fps:.1f} fps")
    print(f"  output           : {out_path}  ({written_bytes/1e6:.2f} MB)")
    print(f"  achieved bitrate : {mbps:.2f} Mbps (target {args.bitrate/1e6:.1f})")
    print(f"  enc util before  : {before.get('enc_util_%', 'n/a')} %")
    print(f"  enc util PEAK    : {sampler.peak_enc} % (over {sampler.samples} samples)")
    print(f"  enc util after   : {after.get('enc_util_%', 'n/a')} %")
    print("\nInterpretation: if enc PEAK is pinned near 100% you are NVENC-bound "
          "(add a second encode session or lower resolution); if it's low and fps "
          "is also low, the bottleneck is upstream (frame source / CPU copy), "
          "NOT the encoder.")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="AV1 NVENC encode + telemetry on RTX 5090")
    p.add_argument("--input", help="video to re-encode to AV1 (omit for synthetic frames)")
    p.add_argument("--output", default="out.av1", help="output AV1 elementary stream")
    p.add_argument("--frames", type=int, default=600, help="synthetic frame count")
    p.add_argument("--width", type=int, default=1920)
    p.add_argument("--height", type=int, default=1080)
    p.add_argument("--bitrate", type=int, default=10_000_000, help="target bits/sec")
    return run(p.parse_args())


if __name__ == "__main__":
    sys.exit(main())
