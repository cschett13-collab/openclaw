#!/usr/bin/env python3
"""Network-free unit tests for the creative engine pure logic.

Run directly:  python test_creative_engine.py
"""

import json
import tempfile
from pathlib import Path

from daily_cron import NICHES, pick_niche, verify_output
from ghl_publisher import build_caption, build_post_payload


def check(name: str, cond: bool) -> None:
    assert cond, f"FAILED: {name}"
    print(f"  ok: {name}")


def main() -> int:
    print("build_caption")
    cap = build_caption({"caption": "Your site is invisible on Google.", "hashtags": ["seo", "#localbiz"]})
    check("includes caption text", "invisible on Google" in cap)
    check("normalizes hashtags", "#seo" in cap and "#localbiz" in cap)
    check("no double hash", "##" not in cap)

    print("build_post_payload")
    scheduled = build_post_payload(
        account_ids=["a1", "a2"], summary="hi", media_url="https://x/y.mp4",
        media_type="video", schedule_iso="2026-06-01T14:00:00Z",
    )
    check("carries account ids", scheduled["accountIds"] == ["a1", "a2"])
    check("media url + type", scheduled["media"][0] == {"url": "https://x/y.mp4", "type": "video"})
    check("scheduled status", scheduled["status"] == "scheduled" and "scheduleDate" in scheduled)
    draft = build_post_payload(account_ids=["a1"], summary="hi", media_url="u", media_type="image", schedule_iso=None)
    check("draft when no schedule", draft["status"] == "draft" and "scheduleDate" not in draft)

    print("pick_niche rotation")
    with tempfile.TemporaryDirectory() as d:
        state = Path(d) / "state.json"
        state.write_text(json.dumps({"last_niche": NICHES[0]}), encoding="utf-8")
        # Across many draws it must never repeat the recorded 'last' niche.
        picks = set()
        for _ in range(200):
            state.write_text(json.dumps({"last_niche": NICHES[0]}), encoding="utf-8")
            picks.add(pick_niche(state))
        check("never repeats last niche", NICHES[0] not in picks)
        check("override wins", pick_niche(state, "custom topic") == "custom topic")

    print("verify_output")
    with tempfile.TemporaryDirectory() as d:
        good = Path(d) / "short.mp4"
        good.write_bytes(b"x" * 10)
        check("ok with real asset", verify_output({"ok": True, "video": str(good)}) is True)
        check("fail when not ok", verify_output({"ok": False, "video": str(good)}) is False)
        check("fail on missing file", verify_output({"ok": True, "video": str(Path(d) / "nope.mp4")}) is False)
        empty = Path(d) / "empty.png"
        empty.write_bytes(b"")
        check("fail on empty file", verify_output({"ok": True, "thumbnail": str(empty)}) is False)

    print("\nAll tests passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
