#!/usr/bin/env python3
"""daily_cron.py — headless director for the faceless content channel.

Once-a-day assembly chain, designed to be driven by cron (it runs once and
exits; it does NOT loop, so it can't stall the machine):

  1. Rotate to the next niche (avoids repeating the previous day's pick).
  2. Run local_generator to synthesize the assets on the GPU.
  3. Verify the rendered output before touching the network.
  4. Hand the manifest to ghl_publisher to schedule across the social queues.

Each stage is isolated: a failure is logged and ends the run cleanly with a
non-zero exit code, never a hang. Wire it up with cron, e.g.:

    # 9:05am daily
    5 9 * * *  cd /path/to/creative_engine && /usr/bin/python3 daily_cron.py >> cron.log 2>&1

Usage:
  python daily_cron.py
  python daily_cron.py --niche "high-hook data visualizations" --schedule 2026-06-01T14:00:00Z
  python daily_cron.py --dry-run        # generate locally, skip publishing
"""

from __future__ import annotations

import argparse
import json
import random
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from config import GHLConfig, GenerationConfig, ensure_dir, get_logger
from ghl_publisher import publish_manifest
from local_generator import generate_assets

log = get_logger("daily_cron")

# Predefined content domains the faceless channel rotates through.
NICHES = [
    "B2B tech gaps",
    "business optimization",
    "high-hook data visualizations",
    "local SEO myths",
    "small-business automation wins",
    "marketing ROI breakdowns",
]


def pick_niche(state_file: Path, override: str | None = None) -> str:
    """Rotate through NICHES, avoiding an immediate repeat of yesterday's pick."""
    if override:
        return override
    last = None
    if state_file.exists():
        try:
            last = json.loads(state_file.read_text(encoding="utf-8")).get("last_niche")
        except (json.JSONDecodeError, OSError):
            last = None
    choices = [n for n in NICHES if n != last] or NICHES
    choice = random.choice(choices)
    try:
        state_file.write_text(json.dumps({"last_niche": choice, "at": _now_iso()}), encoding="utf-8")
    except OSError as exc:
        log.warning("could not persist niche state: %s", exc)
    return choice


def verify_output(manifest: dict) -> bool:
    """Confirm at least one non-empty asset exists before we try to publish."""
    if not manifest.get("ok"):
        return False
    asset = manifest.get("video") or manifest.get("thumbnail")
    if not asset:
        return False
    p = Path(asset)
    return p.is_file() and p.stat().st_size > 0


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def default_schedule() -> str:
    """Schedule a few hours out by default so queues stagger naturally."""
    return (datetime.now(timezone.utc) + timedelta(hours=3)).isoformat(timespec="seconds")


def run(*, niche_override: str | None, schedule_iso: str | None, dry_run: bool) -> int:
    gen_cfg = GenerationConfig()
    run_root = ensure_dir(gen_cfg.output_root)
    state_file = run_root / ".niche_state.json"

    # 1) niche
    niche = pick_niche(state_file, niche_override)
    out_dir = run_root / time.strftime("%Y%m%d-%H%M%S")
    log.info("=== daily run: niche=%r out=%s ===", niche, out_dir)

    # 2) generate (local GPU)
    try:
        manifest = generate_assets(gen_cfg, niche=niche, deficits=None, out_dir=out_dir)
    except Exception as exc:
        log.error("generation stage failed: %s", exc)
        return 2

    # 3) verify
    if not verify_output(manifest):
        log.error("output verification failed; errors=%s", manifest.get("errors"))
        return 3

    if dry_run:
        log.info("dry-run: assets ready at %s, skipping publish", out_dir)
        return 0

    # 4) publish
    try:
        publish_manifest(GHLConfig(), manifest, schedule_iso=schedule_iso or default_schedule())
    except Exception as exc:
        log.error("publish stage failed: %s", exc)
        return 4

    log.info("=== daily run complete ===")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--niche", help="Force a specific niche instead of rotating.")
    parser.add_argument("--schedule", help="ISO-8601 schedule time (UTC). Default: +3h.")
    parser.add_argument("--dry-run", action="store_true", help="Generate locally; skip GHL publishing.")
    args = parser.parse_args(argv)
    return run(niche_override=args.niche, schedule_iso=args.schedule, dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
