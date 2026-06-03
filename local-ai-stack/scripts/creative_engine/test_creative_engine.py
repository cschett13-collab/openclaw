#!/usr/bin/env python3
"""Network-free unit tests for the creative engine pure logic.

Run directly:  python test_creative_engine.py
"""

import json
import os
import tempfile
from pathlib import Path

from config import (
    DiskSpaceError,
    GHLConfig,
    _backoff_delay,
    _first_existing,
    disk_sentinel,
    validate_environment,
)
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

    print("config: GHL headers")
    os.environ["GHL_PRIVATE_TOKEN"] = "tok_123"
    hdrs = GHLConfig().headers()
    check("bearer auth", hdrs["Authorization"] == "Bearer tok_123")
    check("api version header", hdrs["Version"] == "2021-07-28")
    check("json content-type", hdrs["Content-Type"] == "application/json")
    check("multipart omits content-type", "Content-Type" not in GHLConfig().headers(json_body=False))

    print("config: disk sentinel")
    with tempfile.TemporaryDirectory() as d:
        free = disk_sentinel(d, min_free_mb=0)
        check("returns free MB", isinstance(free, int) and free >= 0)
        raised = False
        try:
            disk_sentinel(d, min_free_mb=10**12)  # 1 PB floor -> must trip
        except DiskSpaceError:
            raised = True
        check("raises DiskSpaceError below threshold", raised)
        deep = Path(d) / "a" / "b" / "c"
        check("first_existing ascends to real dir", _first_existing(deep) == Path(d).resolve())

    print("config: backoff")
    check("grows with attempt", _backoff_delay(3, 1.0, 100.0) > _backoff_delay(1, 1.0, 100.0))
    check("clamped to max", _backoff_delay(20, 1.0, 5.0) <= 5.0)

    print("config: validate_environment")
    os.environ["OLLAMA_BASE_URL"] = "http://127.0.0.1:11434"
    check("valid ollama url ok", validate_environment()["OLLAMA_BASE_URL"].startswith("http"))
    os.environ["OLLAMA_BASE_URL"] = "not-a-url"
    bad = False
    try:
        validate_environment()
    except Exception:
        bad = True
    check("rejects bad ollama url", bad)
    os.environ["OLLAMA_BASE_URL"] = "http://127.0.0.1:11434"

    print("\nAll tests passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
