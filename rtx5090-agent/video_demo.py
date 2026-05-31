#!/usr/bin/env python3
"""
video_demo.py — GPU video decode/encode on the RTX 5090 via PyNvVideoCodec.

Uses NVDEC to decode frames straight into GPU memory (zero-copy to a PyTorch
tensor) and NVENC to re-encode — the hardware blocks that make a 5090 useful
for video, not just LLMs.

API per NVIDIA's PyNvVideoCodec Programming Guide (SimpleDecoder / CreateEncoder):
  https://docs.nvidia.com/video-technologies/pynvvideocodec/pynvc-api-prog-guide/index.html

Usage:
    python video_demo.py decode input.mp4          # decode -> GPU tensors
    python video_demo.py transcode input.mp4 out.h264
"""
from __future__ import annotations

import sys


def decode(path: str) -> None:
    import PyNvVideoCodec as nvc
    import torch

    # use_device_memory=True -> frames stay on the GPU (NVDEC output surface).
    # RGBP = planar RGB, which maps to a [C, H, W] tensor.
    decoder = nvc.SimpleDecoder(
        path, gpu_id=0, use_device_memory=True,
        output_color_type=nvc.OutputColorType.RGBP,
    )
    total = len(decoder)
    print(f"frames: {total}")
    if total == 0:
        return
    # Zero-copy decoded frame -> torch tensor on the GPU.
    frame = decoder[0]
    t = torch.from_dlpack(frame)
    print(f"frame0 tensor: shape={tuple(t.shape)} dtype={t.dtype} device={t.device}")
    # Sample a small batch to prove random access + GPU residency.
    idxs = [i for i in (0, total // 2, total - 1) if i < total]
    batch = decoder.get_batch_frames_by_index(idxs)
    stacked = torch.stack([torch.from_dlpack(f).float() / 255.0 for f in batch])
    print(f"sampled {len(idxs)} frames -> batch tensor {tuple(stacked.shape)} on {stacked.device}")


def transcode(src: str, dst: str) -> None:
    import PyNvVideoCodec as nvc

    decoder = nvc.SimpleDecoder(src, gpu_id=0, use_device_memory=False)
    if len(decoder) == 0:
        print("no frames to encode")
        return
    # Probe dimensions from the first decoded frame's tensor (H, W).
    import torch
    first = torch.from_dlpack(decoder[0])
    h, w = int(first.shape[-2]), int(first.shape[-1])
    encoder = nvc.CreateEncoder(
        width=w, height=h, format="NV12",
        usecpuinputbuffer=False, gpu_id=0, codec="h264", bitrate=10_000_000,
    )
    written = 0
    with open(dst, "wb") as out:
        for i in range(len(decoder)):
            bitstream = encoder.Encode(decoder[i])
            if bitstream:
                out.write(bytearray(bitstream))
                written += 1
        tail = encoder.EndEncode()
        if tail:
            out.write(bytearray(tail))
    print(f"encoded {written} frames -> {dst}")


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    try:
        import PyNvVideoCodec  # noqa: F401
    except ImportError:
        print("PyNvVideoCodec not installed. `pip install PyNvVideoCodec` "
              "(needs an NVIDIA GPU + driver; not available on macOS/CPU).")
        return 1
    cmd = sys.argv[1]
    if cmd == "decode":
        decode(sys.argv[2])
    elif cmd == "transcode" and len(sys.argv) >= 4:
        transcode(sys.argv[2], sys.argv[3])
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
