#!/usr/bin/env python3
"""benchmark.py — ground the engine's performance in real numbers, not guesses.

Measures the two throughput-defining stages on the local RTX 5090 host:

  * Ollama text generation — tokens/sec, derived from Ollama's own eval_count /
    eval_duration metrics (not wall-clock estimation).
  * Image render (Automatic1111/Forge or ComfyUI) — seconds/image and images/min
    over N iterations, the real cap on how many frames a Short costs.

If a service is down it's reported as such rather than crashing the run, so the
benchmark itself never becomes a flaky dependency.

Usage:
  python benchmark.py                 # both stages, 3 image iters
  python benchmark.py --runs 5 --json
  python benchmark.py --ollama-only
"""

from __future__ import annotations

import argparse
import base64
import json
import time

from config import GenerationConfig, get_logger, make_session, request_with_retry

log = get_logger("benchmark")

OLLAMA_PROMPT = "Write a 60-word punchy explainer about why local AI beats cloud AI for small businesses."
IMAGE_PROMPT = "high-contrast cinematic vertical poster, bold data visualization, dramatic lighting"


def bench_ollama(cfg: GenerationConfig, *, runs: int) -> dict:
    """Average tokens/sec across `runs` generations using Ollama's metrics."""
    session = make_session(timeout=cfg.timeouts.ollama)
    url = f"{cfg.ollama_base_url.rstrip('/')}/api/generate"
    samples: list[float] = []
    try:
        for i in range(runs):
            payload = {"model": cfg.ollama_model, "prompt": OLLAMA_PROMPT, "stream": False}
            resp = request_with_retry(session, "POST", url, json=payload, timeout=cfg.timeouts.ollama)
            resp.raise_for_status()
            data = resp.json()
            eval_count = data.get("eval_count")
            eval_dur_ns = data.get("eval_duration")
            if eval_count and eval_dur_ns:
                samples.append(eval_count / (eval_dur_ns / 1e9))
            log.info("ollama run %d/%d: %.1f tok/s", i + 1, runs, samples[-1] if samples else float("nan"))
    except Exception as exc:  # service down / model missing — report, don't crash
        return {"ok": False, "error": str(exc), "model": cfg.ollama_model}

    if not samples:
        return {"ok": False, "error": "no eval metrics returned", "model": cfg.ollama_model}
    return {
        "ok": True,
        "model": cfg.ollama_model,
        "runs": len(samples),
        "tokens_per_sec_avg": round(sum(samples) / len(samples), 1),
        "tokens_per_sec_min": round(min(samples), 1),
        "tokens_per_sec_max": round(max(samples), 1),
    }


def bench_image(cfg: GenerationConfig, *, runs: int) -> dict:
    """Average seconds/image and images/min for the configured image backend."""
    if cfg.image_backend == "comfyui":
        return {"ok": False, "error": "benchmark supports the a1111 backend; set IMAGE_BACKEND=a1111", "backend": "comfyui"}

    session = make_session(timeout=cfg.timeouts.render)
    url = f"{cfg.a1111_base_url.rstrip('/')}/sdapi/v1/txt2img"
    payload = {
        "prompt": IMAGE_PROMPT,
        "width": 768,
        "height": 1344,
        "steps": 28,
        "cfg_scale": 6.5,
        "sampler_name": "DPM++ 2M Karras",
    }
    durations: list[float] = []
    try:
        for i in range(runs):
            start = time.perf_counter()
            resp = request_with_retry(session, "POST", url, json=payload, timeout=cfg.timeouts.render)
            resp.raise_for_status()
            images = resp.json().get("images") or []
            if not images:
                return {"ok": False, "error": "backend returned no images", "backend": "a1111"}
            base64.b64decode(images[0].split(",", 1)[-1])  # prove it decodes
            durations.append(time.perf_counter() - start)
            log.info("image run %d/%d: %.2fs", i + 1, runs, durations[-1])
    except Exception as exc:
        return {"ok": False, "error": str(exc), "backend": "a1111"}

    avg = sum(durations) / len(durations)
    return {
        "ok": True,
        "backend": "a1111",
        "runs": len(durations),
        "seconds_per_image_avg": round(avg, 2),
        "seconds_per_image_min": round(min(durations), 2),
        "images_per_min": round(60.0 / avg, 1),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--runs", type=int, default=3, help="Iterations per stage.")
    parser.add_argument("--ollama-only", action="store_true")
    parser.add_argument("--image-only", action="store_true")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    args = parser.parse_args(argv)

    cfg = GenerationConfig()
    report: dict = {"ollama_base_url": cfg.ollama_base_url, "image_backend": cfg.image_backend}

    if not args.image_only:
        report["ollama"] = bench_ollama(cfg, runs=args.runs)
    if not args.ollama_only:
        report["image"] = bench_image(cfg, runs=args.runs)

    if args.json:
        print(json.dumps(report, indent=2))
        return 0

    print("\n=== creative-engine benchmark ===")
    if "ollama" in report:
        o = report["ollama"]
        if o["ok"]:
            print(f"Ollama ({o['model']}): {o['tokens_per_sec_avg']} tok/s avg "
                  f"({o['tokens_per_sec_min']}–{o['tokens_per_sec_max']}) over {o['runs']} run(s)")
        else:
            print(f"Ollama: UNAVAILABLE — {o['error']}")
    if "image" in report:
        im = report["image"]
        if im["ok"]:
            print(f"Image ({im['backend']}): {im['seconds_per_image_avg']}s/image avg, "
                  f"{im['images_per_min']} images/min over {im['runs']} run(s)")
        else:
            print(f"Image: UNAVAILABLE — {im['error']}")
    print("=================================")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
