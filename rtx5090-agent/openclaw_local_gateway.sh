#!/usr/bin/env bash
#
# openclaw_local_gateway.sh — wire the OpenClaw gateway to a LOCAL Ollama
# server on this machine (e.g. an RTX 5090 box) and make it start on boot.
#
# This is the bridge between rtx5090-agent/ (CUDA + Ollama + models) and the
# OpenClaw gateway. It is deterministic and gated: it refuses to proceed unless
# Ollama is reachable and the primary model is present, so the gateway never
# boots pointed at a dead backend.
#
# DEFAULT (no args) = persistent install that survives reboot:
#   1. Verify Ollama is up (native API, NO /v1) and ENABLE it on boot.
#   2. Pull the primary model (+ coding fallback unless skipped).
#   3. Build OpenClaw if dist/ is missing.
#   4. Configure local Ollama + a PERSISTENT gateway auth token + tailnet bind.
#   5. Smoke-test the model through OpenClaw (lean path, no agent tools).
#   6. Install the gateway as a systemd USER service, enable linger, start it.
#      -> after this, a reboot brings the gateway back automatically.
#
# Modes:
#   ./openclaw_local_gateway.sh              # full persistent boot install (default)
#   ./openclaw_local_gateway.sh --foreground # configure + run in foreground (no service)
#   ./openclaw_local_gateway.sh --setup-only # configure only; no service, no run
#   ./openclaw_local_gateway.sh --status     # show gateway service + reachability
#
# Model choice (smartest long-term that actually works on 32GB VRAM):
#   primary  = gpt-oss:20b        — strong agentic/tool-calling + reasoning, ~13GB.
#   fallback = qwen2.5-coder:32b  — heavier coding model (Q4_K_M ~22GB).
# Override with PRIMARY_MODEL / FALLBACK_MODEL. Swap to newer Ollama tags freely.
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
# Loopback/private Ollama hosts do not need a real token; this marker is what
# OpenClaw uses for local hosts (docs/providers/ollama.md). Onboarding persists
# it to auth-profiles.json so the systemd service does not depend on shell env.
export OLLAMA_API_KEY="${OLLAMA_API_KEY:-ollama-local}"
# systemctl --user needs this over SSH with no login session.
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"

MODE="${1:-install}"

log()  { printf '\033[1;32m[openclaw]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[warn]\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31m[stop]\033[0m %s\n' "$*" >&2; exit 1; }
oc()   { node "$REPO/openclaw.mjs" "$@"; }

is_wsl() { grep -qiE 'microsoft|wsl' /proc/version 2>/dev/null; }

# --- --status short-circuit ----------------------------------------------
if [[ "$MODE" == "--status" ]]; then
  oc gateway status || true
  exit 0
fi

# Reject the classic mistake: a /v1 suffix selects OpenAI-compat mode, which
# breaks native Ollama tool calling.
case "$OLLAMA_HOST" in
  */v1|*/v1/) die "OLLAMA_HOST must be the native Ollama URL with NO /v1 suffix (got: $OLLAMA_HOST)." ;;
esac

# --- 1. Ollama reachable + enabled on boot -------------------------------
command -v ollama >/dev/null 2>&1 || die "ollama not found. Run ./setup_rtx5090.sh first, or install from https://ollama.com/download"
log "Checking Ollama daemon at $OLLAMA_HOST ..."
if ! curl -fsS "$OLLAMA_HOST/api/tags" >/dev/null 2>&1; then
  warn "Ollama not answering; starting 'ollama serve' in the background."
  nohup ollama serve >/tmp/ollama-serve.log 2>&1 &
  for _ in $(seq 1 30); do curl -fsS "$OLLAMA_HOST/api/tags" >/dev/null 2>&1 && break; sleep 1; done
fi
curl -fsS "$OLLAMA_HOST/api/tags" >/dev/null 2>&1 || die "Ollama still unreachable at $OLLAMA_HOST (log: /tmp/ollama-serve.log)."
log "Ollama is up."

# Enable Ollama on boot via its system unit. NOTE: skip on WSL2 — the official
# unit's Restart=always + GPU model load at boot can crash-loop the WSL2 VM
# (docs/providers/ollama.md). On WSL2 start Ollama manually instead.
if [[ "$MODE" == "install" ]] && ! is_wsl; then
  if command -v systemctl >/dev/null 2>&1 && systemctl list-unit-files 2>/dev/null | grep -q '^ollama\.service'; then
    log "Enabling ollama.service on boot (needs sudo) ..."
    sudo systemctl enable --now ollama 2>/dev/null || warn "Could not enable ollama.service; enable it manually so models load after reboot."
  else
    warn "No ollama.service unit found; ensure 'ollama serve' starts on boot on this host."
  fi
fi

# --- 2. Models ------------------------------------------------------------
log "Pulling primary model: $PRIMARY_MODEL (one-time; large download)"
ollama pull "$PRIMARY_MODEL"
if [[ "${SKIP_FALLBACK:-0}" != "1" ]]; then
  log "Pulling fallback coding model: $FALLBACK_MODEL"
  ollama pull "$FALLBACK_MODEL" || warn "Could not pull $FALLBACK_MODEL; continuing with primary only."
fi

# --- 3. Build OpenClaw if needed -----------------------------------------
if [[ ! -f "$REPO/dist/entry.mjs" && ! -f "$REPO/dist/index.js" ]]; then
  log "OpenClaw not built; running pnpm install && pnpm build (one-time)."
  command -v pnpm >/dev/null 2>&1 || die "pnpm not found. Run 'corepack enable' first."
  ( cd "$REPO" && pnpm install && pnpm build )
fi

# --- 4. Configure OpenClaw: local Ollama + persistent token + bind --------
log "Configuring OpenClaw for local Ollama ($PRIMARY_MODEL) ..."
oc onboard --non-interactive \
  --auth-choice ollama \
  --custom-base-url "$OLLAMA_HOST" \
  --custom-model-id "$PRIMARY_MODEL" \
  --accept-risk
oc models set "ollama/$PRIMARY_MODEL" || warn "Set default later: openclaw models set ollama/$PRIMARY_MODEL"
if [[ "${SKIP_FALLBACK:-0}" != "1" ]]; then
  oc config set agents.defaults.model.fallbacks "[\"ollama/$FALLBACK_MODEL\"]" 2>/dev/null \
    || warn "Set fallback manually: agents.defaults.model.fallbacks = [\"ollama/$FALLBACK_MODEL\"]"
fi

# Persist a STABLE gateway token so clients keep working across reboots. Reuse
# an existing token if one is already configured; only generate on first run.
GATEWAY_TOKEN="$(oc config get gateway.auth.token 2>/dev/null | tr -d '[:space:]' || true)"
case "$GATEWAY_TOKEN" in
  ""|"Config"*|*"not found"*)
    GATEWAY_TOKEN="$(openssl rand -hex 32 2>/dev/null || head -c32 /dev/urandom | od -An -tx1 | tr -d ' \n')"
    oc config set gateway.auth.mode token
    oc config set gateway.auth.token "$GATEWAY_TOKEN"
    log "Generated and persisted a stable gateway token."
    ;;
  *) log "Reusing existing persisted gateway token." ;;
esac
oc config set gateway.bind "$OPENCLAW_BIND" || warn "Could not set gateway.bind; defaulting to config value."

# --- 5. Model smoke test (lean path) -------------------------------------
log "Smoke-testing the model through OpenClaw ..."
if oc infer model run --local --model "ollama/$PRIMARY_MODEL" --prompt "Reply with exactly: pong" 2>/dev/null | grep -qi "pong"; then
  log "Model smoke test passed."
else
  warn "Model smoke test did not return 'pong'. Check 'openclaw models status' if replies fail."
fi

# --- 6. Run / install -----------------------------------------------------
if [[ "$MODE" == "--setup-only" ]]; then
  log "--setup-only done. Start later with: $0   (installs boot service) or  $0 --foreground"
  exit 0
fi

if [[ "$MODE" == "--foreground" ]]; then
  log "Foreground run: bind=$OPENCLAW_BIND port=$OPENCLAW_PORT (Ctrl-C to stop; does NOT survive reboot)."
  exec node "$REPO/openclaw.mjs" gateway --bind "$OPENCLAW_BIND" --port "$OPENCLAW_PORT" --verbose
fi

# Default: persistent boot install via systemd user service.
log "Installing gateway as a systemd user service (port $OPENCLAW_PORT) ..."
oc gateway install --force --token "$GATEWAY_TOKEN" --port "$OPENCLAW_PORT"

# Enable + start the unit, and enable linger so it starts at boot with no login.
if command -v systemctl >/dev/null 2>&1; then
  systemctl --user enable --now "openclaw-gateway.service" 2>/dev/null \
    || oc gateway start \
    || warn "Could not enable/start the user service; try: openclaw gateway start"
  if command -v loginctl >/dev/null 2>&1; then
    log "Enabling linger so the service starts on boot before you log in (needs sudo) ..."
    sudo loginctl enable-linger "$(id -un)" 2>/dev/null \
      || warn "Could not enable linger. Run: sudo loginctl enable-linger $(id -un)  (else the gateway only starts after you log in)."
  fi
else
  warn "systemctl not found. On this host, install a boot supervisor for: node $REPO/openclaw.mjs gateway --bind $OPENCLAW_BIND --port $OPENCLAW_PORT"
fi

# --- Verify it is actually up --------------------------------------------
log "Verifying gateway is serving ..."
for _ in $(seq 1 20); do curl -fsS "http://127.0.0.1:$OPENCLAW_PORT/healthz" >/dev/null 2>&1 && break; sleep 1; done
if curl -fsS "http://127.0.0.1:$OPENCLAW_PORT/healthz" >/dev/null 2>&1; then
  log "Gateway is UP on http://127.0.0.1:$OPENCLAW_PORT/ (and your tailnet IP on bind=tailnet)."
  log "It will start automatically on next boot. Check anytime with: $0 --status"
else
  oc gateway status || true
  die "Gateway did not report healthy yet. Inspect: openclaw gateway status  and  journalctl --user -u openclaw-gateway -e"
fi
