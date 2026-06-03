# Lead Generation — "Broken Window" pipeline

Data-gathering + AI-leverage scripts for Playbook 1 in
[`../../PLAYBOOKS.md`](../../PLAYBOOKS.md). The pipeline:

```
 target URL ──► site_auditor.py ──► deficits_json ──► email_writer.py ──► outreach email
                  (requests)                            (local Ollama / RTX 5090)
```

## Setup

```bash
cd local-ai-stack/scripts/lead_generation
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

`email_writer.py` needs the local stack running (see [`../../README.md`](../../README.md)) —
Ollama on `127.0.0.1:11434` with a model pulled (`ollama pull llama3.1:8b`).

## site_auditor.py

Fetches each target like a browser and checks for objective, fixable deficits:
missing/invalid **SSL**, missing **Facebook Pixel** (regex on the standard
snippet + 15–16 digit Pixel ID), and missing **GoHighLevel chat widget** (regex
on the LeadConnector loader / `<chat-widget>` element). Outputs `deficits_json`.

```bash
# Single site -> a JSON object on stdout
python site_auditor.py roofingco.com --pretty

# Batch a list -> a JSON array written to a file
python site_auditor.py --input prospects.txt --output deficits.json
```

Output shape (per site):

```json
{
  "url": "https://roofingco.com",
  "host": "roofingco.com",
  "reachable": true,
  "metrics": { "status_code": 200, "load_time_ms": 412, "page_bytes": 51234 },
  "signals": {
    "has_ssl": true, "ssl_valid": true, "forces_https": true,
    "facebook_pixel": false, "facebook_pixel_ids": [], "ghl_widget": false
  },
  "deficits": [
    { "code": "no_facebook_pixel", "severity": "medium", "title": "No Facebook Pixel", "detail": "..." },
    { "code": "no_ghl_widget",     "severity": "medium", "title": "No website chat widget", "detail": "..." }
  ]
}
```

## email_writer.py

Feeds `deficits_json` to the local model and writes a short, one-to-one email
that leads with the highest-severity deficit.

```bash
python site_auditor.py roofingco.com | \
  python email_writer.py - --owner "Mike" --business "Mike's Roofing"
```

## Tests

Detection logic is split into pure functions and covered without network access:

```bash
python test_site_auditor.py
```

## Notes

- Only fetches publicly served pages, like a browser. Audit sites you have a
  legitimate business reason to contact.
- Detection is signature-based, so a heavily customized or proxied site can
  produce a false negative; treat results as leads, not gospel.
