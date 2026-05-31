#!/usr/bin/env python3
"""ghl_publisher.py — bridge local media into the GoHighLevel Social Planner.

Uploads a locally rendered asset to the GHL media library, then schedules a
social post across the connected accounts (YouTube Shorts / Reels / TikTok).

Auth & endpoints (GHL / LeadConnector API v2):
  * Base:    https://services.leadconnectorhq.com
  * Headers: Authorization: Bearer <GHL_PRIVATE_TOKEN>, Version: 2021-07-28
  * Media:   POST /medias/upload-file            (multipart) -> hosted URL
  * Post:    POST /social-media-posting/{locationId}/posts

NOTE: GHL's exact request/response field names evolve. The header + auth scheme
and base paths below are the documented v2 contract, but VERIFY the post body
and media-upload field names against the current docs at
https://highlevel.stoplight.io/ before going live. The payload builders are
isolated so you only adjust them in one place.

Usage:
  python ghl_publisher.py --manifest runs/20260531-120000/manifest.json
  python ghl_publisher.py --manifest run/manifest.json --schedule 2026-06-01T14:00:00Z
"""

from __future__ import annotations

import argparse
import json
import mimetypes
from dataclasses import dataclass
from pathlib import Path

from config import TIMEOUTS, GHLConfig, get_logger, make_session, request_with_retry

log = get_logger("ghl_publisher")


@dataclass
class GHLClient:
    cfg: GHLConfig

    def __post_init__(self) -> None:
        self.session = make_session(timeout=TIMEOUTS.ghl)
        # No Content-Type here: multipart upload sets its own; create_post's
        # json= adds application/json automatically.
        self.session.headers.update(self.cfg.headers(json_body=False))

    def _url(self, path: str) -> str:
        return f"{self.cfg.base_url.rstrip('/')}{path}"

    def upload_media(self, file_path: Path) -> str:
        """Upload a local file to the GHL media library; return its hosted URL."""
        mime = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
        # Read bytes up front so a retried upload re-sends the full payload
        # (a file handle would be exhausted after the first failed attempt).
        files = {"file": (file_path.name, file_path.read_bytes(), mime)}
        data = {"locationId": self.cfg.location_id}
        resp = request_with_retry(
            self.session,
            "POST",
            self._url("/medias/upload-file"),
            files=files,
            data=data,
            timeout=TIMEOUTS.ghl,
        )
        resp.raise_for_status()
        body = resp.json()
        # GHL has returned the hosted location under a few keys across versions.
        url = body.get("url") or body.get("fileUrl") or body.get("link")
        if not url:
            raise RuntimeError(f"Media upload succeeded but no URL in response: {body}")
        log.info("uploaded %s -> %s", file_path.name, url)
        return url

    def create_post(
        self,
        *,
        summary: str,
        media_url: str,
        media_type: str,
        schedule_iso: str | None,
    ) -> dict:
        """Create a scheduled (or draft) social post across the account ids."""
        payload = build_post_payload(
            account_ids=self.cfg.account_ids,
            summary=summary,
            media_url=media_url,
            media_type=media_type,
            schedule_iso=schedule_iso,
        )
        resp = request_with_retry(
            self.session,
            "POST",
            self._url(f"/social-media-posting/{self.cfg.location_id}/posts"),
            json=payload,
            timeout=TIMEOUTS.ghl,
        )
        if resp.status_code >= 400:
            raise RuntimeError(f"GHL post failed ({resp.status_code}): {resp.text}")
        return resp.json()


def build_post_payload(
    *,
    account_ids: list[str],
    summary: str,
    media_url: str,
    media_type: str,
    schedule_iso: str | None,
) -> dict:
    """Construct the Social Planner post body. (Verify field names vs current docs.)"""
    payload: dict = {
        "accountIds": account_ids,
        "summary": summary,
        "media": [{"url": media_url, "type": media_type}],
    }
    if schedule_iso:
        payload["scheduleDate"] = schedule_iso
        payload["status"] = "scheduled"
    else:
        payload["status"] = "draft"
    return payload


def build_caption(concept: dict) -> str:
    """Caption + hashtags from a local_generator concept block."""
    caption = (concept.get("caption") or concept.get("hook") or "").strip()
    tags = concept.get("hashtags") or []
    hashtags = " ".join(f"#{t.lstrip('#')}" for t in tags)
    return f"{caption}\n\n{hashtags}".strip()


def publish_manifest(cfg: GHLConfig, manifest: dict, *, schedule_iso: str | None) -> dict:
    """Upload the manifest's best asset and schedule it."""
    cfg.require()
    client = GHLClient(cfg)

    asset = manifest.get("video") or manifest.get("thumbnail")
    if not asset:
        raise RuntimeError("Manifest has no video or thumbnail asset to publish.")
    asset_path = Path(asset)
    if not asset_path.is_file() or asset_path.stat().st_size == 0:
        raise RuntimeError(f"Asset missing or empty: {asset_path}")

    media_type = "video" if asset_path.suffix.lower() in {".mp4", ".mov", ".webm"} else "image"
    media_url = client.upload_media(asset_path)
    summary = build_caption(manifest.get("concept", {}))
    result = client.create_post(
        summary=summary, media_url=media_url, media_type=media_type, schedule_iso=schedule_iso
    )
    log.info("scheduled post: %s", result.get("id") or result)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--manifest", required=True, help="manifest.json from local_generator.py.")
    parser.add_argument("--schedule", help="ISO-8601 schedule time (UTC). Omit to create a draft.")
    args = parser.parse_args(argv)

    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    try:
        publish_manifest(GHLConfig(), manifest, schedule_iso=args.schedule)
    except Exception as exc:
        log.error("publish failed: %s", exc)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
