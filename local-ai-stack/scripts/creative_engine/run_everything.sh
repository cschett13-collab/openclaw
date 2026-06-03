#!/usr/bin/env bash
# run_everything.sh — deterministic, fail-fast entry point for the creative engine.
#
# Validates the whole environment BEFORE touching the GPU, and bails on the first
# problem with a clear message. Only once every gate passes does it run the
# pipeline. Designed so a cron job or an agent never starts a render against a
# half-broken host.
#
# Usage:
#   ./run_everything.sh              # validate, then daily_cron --dry-run
#   DRY_RUN=0 ./run_everything.sh    # validate, then publish for real
#   REQUIRE_GHL=1 ./run_everything.sh  # also enforce GHL credentials
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"

PYTHON="${PYTHON:-python3}"

step() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
ok()   { printf '\033[1;32m ok:\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m  ! \033[0m%s\n' "$*"; }
fail() { printf '\033[1;31mFAIL:\033[0m %s\n' "$*" >&2; exit 1; }

step "1/7 Python & tooling"
command -v "$PYTHON" >/dev/null || fail "python3 not found"
ok "$($PYTHON --version 2>&1)"
if command -v ffmpeg >/dev/null; then ok "ffmpeg present"; else warn "ffmpeg missing — video assembly will be skipped"; fi
if command -v nvidia-smi >/dev/null; then
  ok "GPU: $(nvidia-smi --query-gpu=name --format=csv,noheader | head -n1)"
else
  warn "nvidia-smi not found — renders will fall back to CPU (slow)"
fi

step "2/7 Python dependencies"
$PYTHON - <<'PY' || fail "missing deps; run: pip install -r requirements.txt"
import requests, urllib3  # noqa: F401
PY
ok "requests / urllib3 importable"

step "3/7 Config & environment validation"
$PYTHON - <<'PY' || fail "environment validation failed (check OLLAMA_BASE_URL / GHL_* env)"
import os
from config import validate_environment
resolved = validate_environment(require_ghl=os.getenv("REQUIRE_GHL") == "1")
for k, v in resolved.items():
    print(f"    {k}={v}")
PY
ok "environment validated"

step "4/7 Disk sentinel"
$PYTHON - <<'PY' || fail "disk space below safety threshold"
from config import disk_sentinel, WorkspacePaths
root = WorkspacePaths.from_env().root
print(f"    {disk_sentinel(root)} MB free at {root}")
PY
ok "disk headroom ok"

step "5/7 Ollama reachable"
OLLAMA="${OLLAMA_BASE_URL:-http://127.0.0.1:11434}"
curl -fsS --max-time 5 "$OLLAMA/api/tags" >/dev/null || fail "Ollama not reachable at $OLLAMA (systemctl status ollama)"
ok "Ollama up at $OLLAMA"

step "6/7 Image backend reachable"
BACKEND="${IMAGE_BACKEND:-a1111}"
if [ "$BACKEND" = "comfyui" ]; then
  URL="${COMFYUI_BASE_URL:-http://127.0.0.1:8188}/system_stats"
else
  URL="${A1111_BASE_URL:-http://127.0.0.1:7860}/sdapi/v1/sd-models"
fi
curl -fsS --max-time 10 "$URL" >/dev/null || fail "image backend '$BACKEND' not reachable at $URL"
ok "image backend up ($BACKEND)"

step "7/7 Self-tests"
$PYTHON test_creative_engine.py >/dev/null || fail "unit tests failed — fix before rendering"
ok "unit tests pass"

step "Environment is sane — starting pipeline"
if [ "${DRY_RUN:-1}" = "1" ]; then
  echo "  (DRY_RUN=1: generating locally, not publishing — set DRY_RUN=0 to publish)"
  exec "$PYTHON" daily_cron.py --dry-run
else
  exec "$PYTHON" daily_cron.py
fi
