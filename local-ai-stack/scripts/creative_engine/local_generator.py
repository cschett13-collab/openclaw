#!/usr/bin/env python3
"""local_generator.py — local GPU-accelerated asset controller.

Synthesizes short-form video concepts and visual hooks entirely on local
hardware (RTX 5090 / CUDA):

  * Prompt Formulation: Ollama turns a niche or `deficits_json` into an
    addictive short-form hook, beat-by-beat script, caption, hashtags, and a
    list of frame/image prompts.
  * Media Endpoint Connectors: passes those frame prompts to a local image
    backend — Automatic1111/Forge (`/sdapi/v1/txt2img`) or ComfyUI
    (`/prompt` + `/history`) — which run on the GPU (TensorRT/xformers if the
    backend is configured for it).
  * Optional assembly: stitches the rendered stills into a vertical short with
    ffmpeg when available.

Outputs a `manifest.json` describing every produced asset, so `ghl_publisher.py`
and `daily_cron.py` can consume it.

Usage:
  python local_generator.py --niche "B2B tech gaps"
  python local_generator.py --deficits ../lead_generation/deficits.json --backend comfyui
"""

from __future__ import annotations

import argparse
import base64
import json
import shutil
import subprocess
import time
from pathlib import Path

from config import (
    GenerationConfig,
    ensure_dir,
    ensure_disk_space,
    get_logger,
    make_session,
    request_with_retry,
)

log = get_logger("local_generator")

HOOK_SYSTEM = (
    "You are a viral short-form video strategist. You write scroll-stopping, "
    "psychologically sticky hooks for faceless YouTube Shorts / Reels / TikTok. "
    "You return STRICT JSON only, no prose."
)


# --- 1. Prompt Formulation ---------------------------------------------------


def formulate_concept(cfg: GenerationConfig, *, niche: str, deficits: dict | None = None) -> dict:
    """Ask the local model for a complete short-form concept as JSON."""
    context = f"NICHE: {niche}\n"
    if deficits:
        context += f"AUDIT_DATA (deficits_json): {json.dumps(deficits)[:4000]}\n"

    prompt = (
        context
        + "\nReturn JSON with exactly these keys:\n"
        '{\n'
        '  "title": str,                  // internal working title\n'
        '  "hook": str,                   // first 3 seconds, max ~12 words\n'
        '  "script_beats": [str],         // 4-6 spoken beats\n'
        '  "caption": str,                // platform caption, 1-2 sentences\n'
        '  "hashtags": [str],             // 5-8, no leading #\n'
        '  "image_prompts": [str],        // 3-5 vivid text-to-image prompts, one per frame\n'
        '  "thumbnail_prompt": str        // single high-contrast cover frame\n'
        '}'
    )
    session = make_session()
    payload = {
        "model": cfg.ollama_model,
        "prompt": prompt,
        "system": HOOK_SYSTEM,
        "format": "json",
        "stream": False,
        "options": {"temperature": 0.9},
    }
    resp = request_with_retry(
        session,
        "POST",
        f"{cfg.ollama_base_url.rstrip('/')}/api/generate",
        json=payload,
        timeout=cfg.timeouts.ollama,
    )
    resp.raise_for_status()
    raw = resp.json().get("response", "").strip()
    try:
        concept = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Model returned non-JSON concept:\n{raw}") from exc
    concept.setdefault("image_prompts", [])
    concept.setdefault("hashtags", [])
    return concept


# --- 2. Media Endpoint Connectors --------------------------------------------


def _render_a1111(cfg: GenerationConfig, prompt: str, out_path: Path) -> Path:
    """Automatic1111 / Forge txt2img -> PNG on disk."""
    session = make_session()
    payload = {
        "prompt": prompt,
        "negative_prompt": "blurry, low quality, watermark, text artifacts",
        "width": 768,
        "height": 1344,  # 9:16 vertical for Shorts/Reels/TikTok
        "steps": 28,
        "cfg_scale": 6.5,
        "sampler_name": "DPM++ 2M Karras",
    }
    resp = request_with_retry(
        session,
        "POST",
        f"{cfg.a1111_base_url.rstrip('/')}/sdapi/v1/txt2img",
        json=payload,
        timeout=cfg.timeouts.render,
    )
    resp.raise_for_status()
    images = resp.json().get("images") or []
    if not images:
        raise RuntimeError("A1111 returned no images")
    out_path.write_bytes(base64.b64decode(images[0].split(",", 1)[-1]))
    return out_path


def _render_comfyui(cfg: GenerationConfig, prompt: str, out_path: Path) -> Path:
    """ComfyUI: queue a prompt, poll history, fetch the produced image.

    Expects a workflow template at COMFYUI_WORKFLOW (JSON exported with
    'Save (API Format)'). The positive-prompt text node is located by the
    `_positive` marker in its `_meta.title`, so swap in any workflow you like.
    """
    import os

    workflow_path = os.getenv("COMFYUI_WORKFLOW")
    if not workflow_path:
        raise RuntimeError("Set COMFYUI_WORKFLOW to an API-format workflow JSON to use the ComfyUI backend.")
    workflow = json.loads(Path(workflow_path).read_text(encoding="utf-8"))
    for node in workflow.values():
        if "_positive" in (node.get("_meta", {}).get("title", "") or "") and "text" in node.get("inputs", {}):
            node["inputs"]["text"] = prompt

    session = make_session()
    base = cfg.comfyui_base_url.rstrip("/")
    queued = request_with_retry(session, "POST", f"{base}/prompt",
                                json={"prompt": workflow}, timeout=cfg.timeouts.render)
    queued.raise_for_status()
    prompt_id = queued.json()["prompt_id"]

    # Poll history until this prompt completes (bounded so we never hang).
    deadline = time.time() + 300
    while time.time() < deadline:
        hist = session.get(f"{base}/history/{prompt_id}", timeout=30).json()
        entry = hist.get(prompt_id)
        if entry:
            for node_out in entry.get("outputs", {}).values():
                for img in node_out.get("images", []):
                    data = session.get(
                        f"{base}/view",
                        params={"filename": img["filename"], "subfolder": img.get("subfolder", ""), "type": img.get("type", "output")},
                        timeout=60,
                    )
                    data.raise_for_status()
                    out_path.write_bytes(data.content)
                    return out_path
        time.sleep(2)
    raise TimeoutError(f"ComfyUI render timed out for prompt {prompt_id}")


def render_frame(cfg: GenerationConfig, prompt: str, out_path: Path) -> Path:
    if cfg.image_backend == "comfyui":
        return _render_comfyui(cfg, prompt, out_path)
    return _render_a1111(cfg, prompt, out_path)


# --- Optional assembly -------------------------------------------------------


def assemble_short(frames: list[Path], out_path: Path, *, seconds_per_frame: float = 2.5) -> Path | None:
    """Stitch stills into a vertical mp4 with ffmpeg, if ffmpeg is installed."""
    if not shutil.which("ffmpeg") or not frames:
        log.warning("ffmpeg not found or no frames; skipping video assembly")
        return None
    list_file = out_path.with_suffix(".txt")
    lines = []
    for f in frames:
        lines.append(f"file '{f.resolve()}'")
        lines.append(f"duration {seconds_per_frame}")
    lines.append(f"file '{frames[-1].resolve()}'")  # ffmpeg concat needs the last frame repeated
    list_file.write_text("\n".join(lines), encoding="utf-8")
    cmd = [
        "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(list_file),
        "-vf", "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,format=yuv420p",
        "-r", "30", str(out_path),
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=600)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        log.error("ffmpeg assembly failed: %s", exc)
        return None
    return out_path


# --- Controller --------------------------------------------------------------


def generate_assets(
    cfg: GenerationConfig, *, niche: str, deficits: dict | None, out_dir: Path
) -> dict:
    """Run the full local pipeline and return a manifest dict."""
    ensure_dir(out_dir)
    ensure_disk_space(out_dir, min_free_mb=1024)

    log.info("Formulating concept for niche=%r", niche)
    concept = formulate_concept(cfg, niche=niche, deficits=deficits)

    frames: list[Path] = []
    errors: list[str] = []
    for idx, fp in enumerate(concept.get("image_prompts", [])):
        target = out_dir / f"frame_{idx:02d}.png"
        try:
            render_frame(cfg, fp, target)
            frames.append(target)
            log.info("rendered %s", target.name)
        except Exception as exc:  # one bad frame must not kill the run
            errors.append(f"frame {idx}: {exc}")
            log.error("frame %d failed: %s", idx, exc)

    video = assemble_short(frames, out_dir / "short.mp4") if frames else None

    manifest = {
        "niche": niche,
        "concept": concept,
        "backend": cfg.image_backend,
        "frames": [str(f) for f in frames],
        "video": str(video) if video else None,
        "thumbnail": str(frames[0]) if frames else None,
        "errors": errors,
        "ok": bool(frames),
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    log.info("manifest written: %d frame(s), %d error(s)", len(frames), len(errors))
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--niche", default="B2B tech gaps", help="Content niche / topic.")
    parser.add_argument("--deficits", help="Optional deficits_json file from site_auditor.py.")
    parser.add_argument("--backend", choices=["a1111", "comfyui"], help="Override IMAGE_BACKEND.")
    parser.add_argument("--out", help="Output directory (default: <output_root>/<timestamp>).")
    args = parser.parse_args(argv)

    cfg = GenerationConfig()
    if args.backend:
        cfg.image_backend = args.backend

    deficits = json.loads(Path(args.deficits).read_text(encoding="utf-8")) if args.deficits else None
    out_dir = Path(args.out) if args.out else Path(cfg.output_root) / time.strftime("%Y%m%d-%H%M%S")

    manifest = generate_assets(cfg, niche=args.niche, deficits=deficits, out_dir=out_dir)
    print(json.dumps({"out_dir": str(out_dir), "ok": manifest["ok"], "frames": len(manifest["frames"])}))
    return 0 if manifest["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
