#!/usr/bin/env python3
"""email_writer.py — the "AI leverage" step of the Broken Window playbook.

Reads the ``deficits_json`` produced by ``site_auditor.py`` and uses the local
5090 model (via Ollama) to write a short, hyper-personalized, one-to-one
outreach email that leads with the single highest-impact deficit.

Usage:
  python site_auditor.py roofingco.com -o deficits.json --pretty
  python email_writer.py deficits.json --owner "Mike" --business "Mike's Roofing"

  # or pipe straight through:
  python site_auditor.py roofingco.com | python email_writer.py - --business "Mike's Roofing"
"""

from __future__ import annotations

import argparse
import json
import sys

from ollama_client import DEFAULT_BASE_URL, DEFAULT_MODEL, OllamaClient, OllamaError

SYSTEM_PROMPT = (
    "You are a concise B2B outreach copywriter for a local marketing agency. "
    "You write short, specific, one-to-one emails to small-business owners. "
    "Rules: under 120 words; no fluff, no buzzwords, no 'I hope this finds you "
    "well'; lead with the single most important problem and why it costs them "
    "customers; offer a concrete free fix (e.g. a 30-second screen recording); "
    "one soft call to action; plain text, no markdown. Sound like a helpful "
    "human who actually looked at their site, not a mass mailer."
)

# Lower severity number = address first.
_SEVERITY_RANK = {"high": 0, "medium": 1, "low": 2}


def top_deficit(deficits: list[dict]) -> dict | None:
    if not deficits:
        return None
    return sorted(deficits, key=lambda d: _SEVERITY_RANK.get(d.get("severity", "low"), 3))[0]


def build_prompt(site: dict, *, owner: str | None, business: str | None) -> str:
    lead = top_deficit(site.get("deficits", []))
    facts = {
        "business": business or site.get("host", "the business"),
        "owner": owner or "there",
        "website": site.get("url"),
        "lead_deficit": lead,
        "all_deficits": site.get("deficits", []),
    }
    return (
        "Write the outreach email using only these facts. Address the owner by "
        "name if provided. Open by naming the lead_deficit specifically and the "
        "concrete harm it does, then offer the free fix, then a soft CTA.\n\n"
        f"FACTS:\n{json.dumps(facts, indent=2)}"
    )


def load_sites(path: str) -> list[dict]:
    text = sys.stdin.read() if path == "-" else open(path, encoding="utf-8").read()
    data = json.loads(text)
    return data if isinstance(data, list) else [data]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("deficits", help="deficits_json file from site_auditor.py, or '-' for stdin.")
    parser.add_argument("--owner", help="Owner's first name, if known.")
    parser.add_argument("--business", help="Business name, if known.")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Ollama model to use.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="Ollama base URL.")
    args = parser.parse_args(argv)

    client = OllamaClient(base_url=args.base_url, model=args.model)
    sites = load_sites(args.deficits)

    for i, site in enumerate(sites):
        if not site.get("deficits"):
            print(f"[skip] {site.get('host', site.get('url'))}: no deficits found", file=sys.stderr)
            continue
        prompt = build_prompt(site, owner=args.owner, business=args.business)
        try:
            email = client.generate(prompt, system=SYSTEM_PROMPT, temperature=0.7)
        except OllamaError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        if i:
            print("\n" + "=" * 60 + "\n")
        print(f"# {site.get('host', site.get('url'))}\n")
        print(email)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
