#!/bin/bash
# Serve a small open-weight model with Ollama inside the cloud sandbox.
# CPU-only and ephemeral: this is for CI smoke tests, demos, and wiring checks,
# NOT real GPU throughput. For production use your own GPU box (see README path A).
#
# Usage:
#   cloud-local-models/serve-local-model.sh           # default model qwen2.5:0.5b
#   MODEL=llama3.2:1b cloud-local-models/serve-local-model.sh
#
# After it reports ready, point OpenClaw at it with
# cloud-local-models/config/openclaw.ollama-local.json
set -euo pipefail

MODEL="${MODEL:-qwen2.5:0.5b}"
OLLAMA_HOST="${OLLAMA_HOST:-http://127.0.0.1:11434}"
HEALTH_URL="${OLLAMA_HOST%/}/api/tags"

log() { printf '[serve-local-model] %s\n' "$*"; }

# 1. Install Ollama if missing (idempotent).
if ! command -v ollama >/dev/null 2>&1; then
  log "ollama not found; installing via official script"
  curl -fsSL https://ollama.com/install.sh | sh
fi

# 2. Start the daemon if it is not already answering.
if ! curl -fsS "$HEALTH_URL" >/dev/null 2>&1; then
  log "starting 'ollama serve' in the background"
  ollama serve >/tmp/ollama-serve.log 2>&1 &
fi

# 3. Wait for readiness (up to ~60s).
log "waiting for Ollama to become healthy at $HEALTH_URL"
for _ in $(seq 1 60); do
  if curl -fsS "$HEALTH_URL" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done
if ! curl -fsS "$HEALTH_URL" >/dev/null 2>&1; then
  log "ERROR: Ollama did not become healthy; see /tmp/ollama-serve.log"
  exit 1
fi

# 4. Pull the model (idempotent: skips if already present).
log "pulling model '$MODEL' (small CPU-friendly model)"
ollama pull "$MODEL"

log "ready. Ollama serving '$MODEL' at $OLLAMA_HOST"
log "point OpenClaw at it: cp cloud-local-models/config/openclaw.ollama-local.json ~/.openclaw/config.json"
