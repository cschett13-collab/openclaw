#!/usr/bin/env python3
"""site_auditor.py — the data-gathering engine for the "Broken Window" playbook.

Takes one or more target business URLs, fetches each page, and checks for
objective, fixable deficits:

  * Missing SSL / HTTPS (does the site serve a valid cert, and force https?)
  * Missing Facebook Pixel (regex search for the standard Pixel snippet + ID)
  * Missing GoHighLevel chat widget (regex search for GHL widget scripts)

It emits a clean JSON payload (``deficits_json``) per site that the local 5090
model can later parse to write a hyper-personalized outreach email
(see ``email_writer.py``).

Usage:
  python site_auditor.py https://example.com
  python site_auditor.py example.com roofingco.com --pretty
  python site_auditor.py --input prospects.txt --output deficits.json

Only fetches publicly served pages, exactly like a browser would. Be a good
citizen: don't point it at sites you have no business reason to audit.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from urllib.parse import urlparse

import requests

USER_AGENT = (
    "Mozilla/5.0 (compatible; LeadAuditBot/1.0; +local-ai-stack site_auditor)"
)

# --- Detection: pure functions over HTML (no network, so they're unit-testable) ---

# Standard Meta/Facebook Pixel: `fbq('init', '1234567890123456')` and the
# fbevents.js loader. Pixel IDs are 15-16 digit numbers.
_FB_INIT_RE = re.compile(r"""fbq\s*\(\s*['"]init['"]\s*,\s*['"](\d{15,16})['"]""", re.I)
_FB_SCRIPT_RE = re.compile(r"connect\.facebook\.net/[^\"']*?/fbevents\.js", re.I)
_FB_NOSCRIPT_RE = re.compile(r"facebook\.com/tr\?id=(\d{15,16})", re.I)

# GoHighLevel / LeadConnector chat widget signatures.
_GHL_RE = re.compile(
    r"leadconnectorhq\.com"          # widget loader / asset host
    r"|widgets\.leadconnector"       # widgets.leadconnectorhq.com/loader.js
    r"|<chat-widget\b"               # the custom element GHL injects
    r"|data-widget-id"               # GHL widget config attribute
    r"|LC_API",                      # LeadConnector JS API
    re.I,
)


def find_facebook_pixels(html: str) -> list[str]:
    """Return the list of distinct Facebook Pixel IDs found in the HTML."""
    ids = set(_FB_INIT_RE.findall(html))
    ids.update(_FB_NOSCRIPT_RE.findall(html))
    # A bare fbevents.js include with no parseable id still counts as "present".
    if not ids and _FB_SCRIPT_RE.search(html):
        return ["unknown"]
    return sorted(ids)


def has_ghl_widget(html: str) -> bool:
    """True if a GoHighLevel / LeadConnector chat widget is present."""
    return bool(_GHL_RE.search(html))


# --- Network helpers ---


def normalize_url(raw: str) -> str:
    """Coerce a bare domain or http URL into an https URL to probe first."""
    raw = raw.strip()
    if not raw:
        return raw
    if not re.match(r"^https?://", raw, re.I):
        return "https://" + raw
    return raw


def _get(url: str, timeout: int) -> requests.Response:
    return requests.get(
        url,
        timeout=timeout,
        headers={"User-Agent": USER_AGENT},
        allow_redirects=True,
    )


def audit_site(raw_url: str, timeout: int = 15) -> dict:
    """Audit a single site and return its ``deficits_json`` payload."""
    https_url = normalize_url(raw_url)
    host = urlparse(https_url).netloc

    payload: dict = {
        "url": https_url,
        "host": host,
        "reachable": False,
        "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "metrics": {},
        "signals": {},
        "deficits": [],
    }

    # 1) HTTPS / SSL check. Try https first with cert verification.
    has_ssl = False
    ssl_valid = False
    resp: requests.Response | None = None
    try:
        resp = _get(https_url, timeout)
        has_ssl = True
        ssl_valid = True
    except requests.exceptions.SSLError:
        # Cert exists but is invalid/expired/mismatched.
        has_ssl = True
        ssl_valid = False
    except requests.exceptions.RequestException:
        has_ssl = False

    # Fall back to http if https never connected, so we can still read the page.
    forces_https = False
    if resp is None:
        http_url = "http://" + host
        try:
            resp = _get(http_url, timeout)
            forces_https = resp.url.lower().startswith("https://")
            has_ssl = has_ssl or forces_https
        except requests.exceptions.RequestException as exc:
            payload["error"] = f"Unreachable over http and https: {exc}"
            return payload
    else:
        forces_https = resp.url.lower().startswith("https://")

    payload["reachable"] = True
    payload["url"] = resp.url
    html = resp.text or ""

    payload["metrics"] = {
        "status_code": resp.status_code,
        "load_time_ms": int(resp.elapsed.total_seconds() * 1000),
        "page_bytes": len(resp.content),
    }

    # 2) + 3) Marketing-stack detection.
    pixels = find_facebook_pixels(html)
    ghl = has_ghl_widget(html)

    payload["signals"] = {
        "has_ssl": has_ssl,
        "ssl_valid": ssl_valid,
        "forces_https": forces_https,
        "facebook_pixel": bool(pixels),
        "facebook_pixel_ids": pixels,
        "ghl_widget": ghl,
    }
    payload["deficits"] = build_deficits(payload["signals"])
    return payload


def build_deficits(signals: dict) -> list[dict]:
    """Translate raw signals into the human-facing list of fixable deficits."""
    deficits: list[dict] = []

    if not signals.get("has_ssl"):
        deficits.append(
            {
                "code": "no_ssl",
                "severity": "high",
                "title": "No SSL certificate",
                "detail": "Site is served over HTTP only. Chrome flags it "
                "'Not Secure', which scares off visitors and hurts SEO.",
            }
        )
    elif not signals.get("ssl_valid"):
        deficits.append(
            {
                "code": "ssl_invalid",
                "severity": "high",
                "title": "Invalid SSL certificate",
                "detail": "An SSL certificate is present but invalid or expired, "
                "so browsers show a full-page security warning.",
            }
        )
    elif not signals.get("forces_https"):
        deficits.append(
            {
                "code": "no_https_redirect",
                "severity": "low",
                "title": "HTTP not redirected to HTTPS",
                "detail": "The secure version exists but visitors hitting the "
                "plain HTTP URL aren't forced over to it.",
            }
        )

    if not signals.get("facebook_pixel"):
        deficits.append(
            {
                "code": "no_facebook_pixel",
                "severity": "medium",
                "title": "No Facebook Pixel",
                "detail": "No Meta Pixel detected, so the business can't retarget "
                "website visitors or measure ad conversions.",
            }
        )

    if not signals.get("ghl_widget"):
        deficits.append(
            {
                "code": "no_ghl_widget",
                "severity": "medium",
                "title": "No website chat widget",
                "detail": "No GoHighLevel chat widget detected. Visitors with a "
                "question have no instant way to convert into a lead.",
            }
        )

    return deficits


# --- CLI ---


def _load_targets(args: argparse.Namespace) -> list[str]:
    targets = list(args.urls)
    if args.input:
        with open(args.input, encoding="utf-8") as fh:
            targets.extend(line.strip() for line in fh if line.strip() and not line.startswith("#"))
    return targets


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("urls", nargs="*", help="One or more target URLs or bare domains.")
    parser.add_argument("-i", "--input", help="File with one URL per line ('#' comments allowed).")
    parser.add_argument("-o", "--output", help="Write JSON here instead of stdout.")
    parser.add_argument("-t", "--timeout", type=int, default=15, help="Per-request timeout (s).")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print the JSON.")
    args = parser.parse_args(argv)

    targets = _load_targets(args)
    if not targets:
        parser.error("Provide at least one URL, or --input FILE.")

    results = []
    for target in targets:
        print(f"[auditing] {target}", file=sys.stderr)
        try:
            results.append(audit_site(target, timeout=args.timeout))
        except Exception as exc:  # keep the batch going on a single bad URL
            results.append({"url": target, "reachable": False, "error": str(exc)})

    # Single URL -> object; multiple -> array. Always valid `deficits_json`.
    out = results[0] if len(results) == 1 else results
    text = json.dumps(out, indent=2 if args.pretty else None)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
        print(f"[done] wrote {args.output}", file=sys.stderr)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
