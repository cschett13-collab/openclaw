# Creative Engine — local generation → GoHighLevel publishing

A faceless short-form content pipeline that does the heavy lifting on local
hardware (RTX 5090 / CUDA) and pushes finished posts out through the
GoHighLevel (GHL) Social Planner.

```
 daily_cron.py  (headless director, run once/day by cron)
      │
      ├─ local_generator.py   Ollama hook/script  +  A1111/ComfyUI frames  (GPU)
      │        └─ manifest.json  (concept + assets)
      │
      └─ ghl_publisher.py     upload media → schedule post → YT Shorts / Reels / TikTok
```

## Modules

| File | Role |
|------|------|
| `config.py` | Resilient HTTP sessions (retry/backoff for dropouts), disk-space guards, env-driven config, logging. |
| `local_generator.py` | Prompt formulation (Ollama) + media connectors (Automatic1111/Forge `txt2img`, ComfyUI `/prompt`), optional ffmpeg assembly → `manifest.json`. |
| `ghl_publisher.py` | Uploads a manifest asset to the GHL media library and schedules a Social Planner post. |
| `daily_cron.py` | Rotates niches, runs the generator, verifies output, triggers the publisher. Runs once and exits. |

## Setup

```bash
cd local-ai-stack/scripts/creative_engine
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

Local services (see [`../../README.md`](../../README.md)):
- **Ollama** on `127.0.0.1:11434` (`ollama pull llama3.1:8b`).
- An image backend — **Automatic1111/Forge** (`--api`, port 7860) *or* **ComfyUI** (port 8188).
- **ffmpeg** (optional) for stitching stills into a vertical `.mp4`.

## Configuration (environment variables)

```bash
# Generation
export OLLAMA_BASE_URL=http://127.0.0.1:11434
export OLLAMA_MODEL=llama3.1:8b
export IMAGE_BACKEND=a1111            # or: comfyui
export A1111_BASE_URL=http://127.0.0.1:7860
export COMFYUI_BASE_URL=http://127.0.0.1:8188
export COMFYUI_WORKFLOW=/path/to/workflow_api.json   # only for comfyui backend

# Storage & hardware thresholds (config.py)
export CREATIVE_ASSET_ROOT=/volume1/FVCE_Pipeline/creative_assets  # raw/ rendered/ temp_frames/
export MIN_FREE_MB=2048               # disk sentinel floor
export OLLAMA_TIMEOUT=120             # seconds
export RENDER_TIMEOUT=600             # SD/ComfyUI render ceiling
export GHL_TIMEOUT=120

# Publishing (GHL v2)
export GHL_PRIVATE_TOKEN=...          # never commit this
export GHL_LOCATION_ID=...
export GHL_ACCOUNT_IDS=acc_1,acc_2    # connected social accounts
```

## Run

```bash
# Generate assets only
python local_generator.py --niche "B2B tech gaps"

# Generate from an audit (ties into the lead_generation pipeline)
python local_generator.py --deficits ../lead_generation/deficits.json

# Publish an existing manifest
python ghl_publisher.py --manifest runs/20260531-120000/manifest.json --schedule 2026-06-01T14:00:00Z

# Full daily chain (dry-run skips publishing)
python daily_cron.py --dry-run
python daily_cron.py

# cron: 9:05am daily
# 5 9 * * *  cd /path/to/creative_engine && /usr/bin/python3 daily_cron.py >> cron.log 2>&1
```

## Resilience built in

- **Connection dropouts:** every HTTP call goes through a `requests` session with
  exponential-backoff retries on connect/read errors and 429/5xx (`config.make_session`).
- **Disk boundaries:** `ensure_disk_space` refuses to start a render when the
  volume is low; one failed frame is logged and skipped, not fatal.
- **No stalls:** ComfyUI polling and ffmpeg are time-bounded; `daily_cron.py`
  runs once and exits with a meaningful code (2 = generate, 3 = verify, 4 = publish).

## ⚠️ Verify the GHL contract before going live

The GHL/LeadConnector **auth scheme and base paths** used here are the
documented v2 contract (`Bearer` token + `Version: 2021-07-28`, base
`https://services.leadconnectorhq.com`, posts under
`/social-media-posting/{locationId}/posts`, media via `/medias/upload-file`).
The exact **post body and media-response field names** drift between API
revisions — confirm them against https://highlevel.stoplight.io/ and adjust the
isolated `build_post_payload` / `upload_media` helpers. They're deliberately the
only places that encode GHL's schema.

## Tests

```bash
python test_creative_engine.py    # network-free: payloads, caption, niche rotation, output verify
```

## Note

Publish to social accounts you own/manage and follow each platform's automation
and disclosure policies.
