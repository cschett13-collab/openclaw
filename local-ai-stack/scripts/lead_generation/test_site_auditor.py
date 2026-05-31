#!/usr/bin/env python3
"""Network-free unit tests for site_auditor detection logic.

Run directly (no pytest needed):  python test_site_auditor.py
"""

from site_auditor import (
    build_deficits,
    find_facebook_pixels,
    has_ghl_widget,
    normalize_url,
)

PIXEL_HTML = """
<script>!function(f,b,e,v,n,t,s){...}(window,document,'script',
'https://connect.facebook.net/en_US/fbevents.js');
fbq('init', '1234567890123456'); fbq('track', 'PageView');</script>
<noscript><img src="https://www.facebook.com/tr?id=1234567890123456&ev=PageView"/></noscript>
"""

GHL_HTML = """
<chat-widget location-id="abc123" data-widget-id="w_987"></chat-widget>
<script src="https://widgets.leadconnectorhq.com/loader.js"
  data-resources-url="https://widgets.leadconnectorhq.com/chat-widget/loader.js"></script>
"""

PLAIN_HTML = "<html><head><title>Joe's Plumbing</title></head><body>Call us!</body></html>"


def check(name: str, cond: bool) -> None:
    assert cond, f"FAILED: {name}"
    print(f"  ok: {name}")


def main() -> int:
    print("normalize_url")
    check("bare domain -> https", normalize_url("example.com") == "https://example.com")
    check("http preserved", normalize_url("http://x.com") == "http://x.com")
    check("https preserved", normalize_url("https://x.com") == "https://x.com")

    print("find_facebook_pixels")
    check("detects pixel id", find_facebook_pixels(PIXEL_HTML) == ["1234567890123456"])
    check("no false positive", find_facebook_pixels(PLAIN_HTML) == [])
    check(
        "loader without id -> unknown",
        find_facebook_pixels("<script src='connect.facebook.net/en_US/fbevents.js'></script>")
        == ["unknown"],
    )

    print("has_ghl_widget")
    check("detects GHL widget", has_ghl_widget(GHL_HTML) is True)
    check("no false positive", has_ghl_widget(PLAIN_HTML) is False)

    print("build_deficits")
    clean = build_deficits(
        {"has_ssl": True, "ssl_valid": True, "forces_https": True,
         "facebook_pixel": True, "ghl_widget": True}
    )
    check("fully optimized site -> no deficits", clean == [])

    broken = build_deficits(
        {"has_ssl": False, "ssl_valid": False, "forces_https": False,
         "facebook_pixel": False, "ghl_widget": False}
    )
    codes = {d["code"] for d in broken}
    check("flags no_ssl", "no_ssl" in codes)
    check("flags no_facebook_pixel", "no_facebook_pixel" in codes)
    check("flags no_ghl_widget", "no_ghl_widget" in codes)
    check("no_ssl is high severity", next(d for d in broken if d["code"] == "no_ssl")["severity"] == "high")

    print("\nAll tests passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
