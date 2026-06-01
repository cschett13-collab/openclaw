#!/usr/bin/env bash
#
# openclaw_local_gateway.sh — wire the OpenClaw gateway to a LOCAL Ollama
# server on this machine (e.g. an RTX 5090 box), then start it.
#
# This is the bridge between rtx5090-agent/ (which sets up Ollama + models)
# and the OpenClaw gateway. It is deterministic and gated: it refuses to start
# the gateway unless Ollama is actually reachable and the primary model is
# present, so the gateway never boots pointed at a dead backend.
#
# What it does, in fixed order:
#   1. Verify Ollama is installed and the daemon answers on $OLLAMA_HOST.
#   2. Pull the primary model (and the coding fallback, unless skipped).
#   3. Build OpenClaw if dist/ is missing.
#   4. Configure OpenClaw to use local Ollama (native API, no /v1) and set the
#      default model — via non-interactive onboarding (idempotent).
#   5. Start the gateway, bound so your tailnet/LAN can reach it.
#
# Model choice (smartest long-term that actually works on 32GB VRAM):
#   primary  = gpt-oss:20b        — strong agentic/tool-calling + reasoning,
#                                    ~13GB so it leaves room for large context.
#   fallback = qwen2.5-coder:32b  — heavier coding model (Q4_K_M ~22GB).
# Override with PRIMARY_MODEL / FALLBACK_MODEL. Swap to newer Ollama tags freely.
#
# Usage:
#   ./openclaw_local_gateway.sh                 # configure + start gateway
#   ./openclaw_local_gateway.sh --setup-only    # configure, do not start
#   SKIP_FALLBACK=1 ./openclaw_local_gateway.sh # only pull the primary model
#   OPENCLAW_BIND=lan ./openclaw_local_gateway.sh  # LAN instead of tailnet
#
# Env:
#   PRIMARY_MODEL    default gpt-oss:20b
#   FALLBACK_MODEL   default qwen2.5-coder:32b
#   SKIP_FALLBACK    1 = do not pull the fallback model
#   OLLAMA_HOST      default http://127.0.0.1:11434   (native API, NO /v1)
#   OPENCLAW_BIND    default tailnet                  (tailnet|lan|loopback)
#   OPENCLAW_PORT    default 18789
#
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"

PRIMARY_MODEL="${PRIMARY_MODEL:-gpt-oss:20b}"
FALLBACK_MODEL="${FALLBACK_MODEL:-qwen2.5-coder:32b}"
OLLAMA_HOST="${OLLAMA_HOST:-http://127.0.0.1:11434}"
OPENCLAW_BIND="${OPENCLAW_BIND:-tailnet}"
OPENCLAW_PORT="${OPENCLAW_PORT:-18789}"
# Loopback/private Ollama hosts do not need a real token; this is the marker
# OpenClaw uses for local hosts (see docs/providers/ollama.md).
export OLLAMA_API_KEY="${OLLAMA_API_KEY:-ollama-local}"

log()  { printf '\033[1;32m[openclaw]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[warn]\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31m[stop]\033[0m %s\n' "$*" >&2; exit 1; }

oc() { node "$REPO/openclaw.mjs" "$@"; }

# Reject the classic mistake: a /v1 suffix selects OpenAI-compat mode, which
# breaks native Ollama tool calling. Keep the native API base URL.
case "$OLLAMA_HOST" in
  */v1|*/v1/) die "OLLAMA_HOST must be the native Ollama URL with NO /v1 suffix (got: $OLLAMA_HOST). Tool calling breaks on /v1." ;;
esac

# --- 1. Ollama reachable --------------------------------------------------
command -v ollama >/dev/null 2>&1 || die "ollama not found. Run ./setup_rtx5090.sh first (it installs Ollama + CUDA), or install from https://ollama.com/download"
log "Checking Ollama daemon at $OLLAMA_HOST ..."
if ! curl -fsS "$OLLAMA_HOST/api/tags" >/dev/null 2>&1; then
  warn "Ollama daemon not answering; starting 'ollama serve' in the background."
  nohup ollama serve >/tmp/ollama-serve.log 2>&1 &
  for _ in $(seq 1 30); do
    curl -fsS "$OLLAMA_HOST/api/tags" >/dev/null 2>&1 && break
    sleep 1
  done
fi
curl -fsS "$OLLAMA_HOST/api/tags" >/dev/null 2>&1 || die "Ollama still unreachable at $OLLAMA_HOST. Check 'ollama serve' (log: /tmp/ollama-serve.log)."
log "Ollama is up."

# --- 2. Models ------------------------------------------------------------
log "Pulling primary model: $PRIMARY_MODEL (one-time; large download)"
ollama pull "$PRIMARY_MODEL"
if [[ "${SKIP_FALLBACK:-0}" != "1" ]]; then
  log "Pulling fallback coding model: $FALLBACK_MODEL"
  ollama pull "$FALLBACK_MODEL" || warn "Could not pull $FALLBACK_MODEL; continuing with primary only."
fi

# --- 3. Build OpenClaw if needed -----------------------------------------
if [[ ! -f "$REPO/dist/entry.mjs" && ! -f "$REPO/dist/index.js" ]]; then
  log "OpenClaw not built yet; running pnpm install && pnpm build (one-time)."
  command -v pnpm >/dev/null 2>&1 || die "pnpm not found. Run 'corepack enable' first."
  ( cd "$REPO" && pnpm install && pnpm build )
fi

# --- 4. Configure OpenClaw to use local Ollama ---------------------------
# Non-interactive onboarding is idempotent: it writes gateway.mode=local and an
# Ollama provider pointed at the native local API with the chosen primary model.
log "Configuring OpenClaw for local Ollama ($PRIMARY_MODEL) ..."
oc onboard --non-interactive \
  --auth-choice ollama \
  --custom-base-url "$OLLAMA_HOST" \
  --custom-model-id "$PRIMARY_MODEL" \
  --accept-risk

oc models set "ollama/$PRIMARY_MODEL" || warn "Could not set default model non-fatally; set it later with: openclaw models set ollama/$PRIMARY_MODEL"
# Best-effort coding fallback (ignored if the CLI rejects the array form).
if [[ "${SKIP_FALLBACK:-0}" != "1" ]]; then
  oc config set agents.defaults.model.fallbacks "[\"ollama/$FALLBACK_MODEL\"]" 2>/dev/null \
    || warn "Set the fallback manually in openclaw.json: agents.defaults.model.fallbacks = [\"ollama/$FALLBACK_MODEL\"]"
fi

# --- 5. Smoke the model on the lean path before starting the agent --------
log "Smoke-testing the model through OpenClaw (no agent tools) ..."
if oc infer model run --local --model "ollama/$PRIMARY_MODEL" --prompt "Reply with exactly: pong" 2>/dev/null | grep -qi "pong"; then
  log "Model smoke test passed."
else
  warn "Model smoke test did not return 'pong'. The gateway will still start, but check 'openclaw models status' if replies fail."
fi

if [[ "${1:-}" == "--setup-only" ]]; then
  log "--setup-only set. Start later with: node $REPO/openclaw.mjs gateway --bind $OPENCLAW_BIND --port $OPENCLAW_PORT"
  exit 0
fi

# --- 6. Start the gateway -------------------------------------------------
# tailnet bind makes the gateway reachable from other Tailscale nodes (e.g. your
# phone). Requires Tailscale running on this host; fall back to lan otherwise.
log "Starting gateway: bind=$OPENCLAW_BIND port=$OPENCLAW_PORT"
log "Control UI will be at http://127.0.0.1:$OPENCLAW_PORT/ (and your tailnet IP on bind=tailnet)."
exec node "$REPO/openclaw.mjs" gateway --bind "$OPENCLAW_BIND" --port "$OPENCLAW_PORT" --verbose
