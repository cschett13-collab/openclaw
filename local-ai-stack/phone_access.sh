#!/usr/bin/env bash
# phone_access.sh — make the local Open WebUI reachable on your phone over
# Tailscale (Layer 3). Run this on the Pop!_OS workstation after ./setup.sh.
#
# It brings Tailscale up, publishes Open WebUI over HTTPS on your private
# tailnet (no public exposure, no router port-forwarding), and prints the URL
# — as a scannable QR code if `qrencode` is installed.
#
#   ./phone_access.sh            # serve Open WebUI (port 3000) to your phone
#   PORT=8080 ./phone_access.sh  # different local port
#
# On the phone: install the Tailscale app, sign in with the SAME account, then
# open the printed https URL.
set -euo pipefail

PORT="${PORT:-3000}"

log()  { printf '\033[1;36m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m!! \033[0m%s\n' "$*" >&2; }
fail() { printf '\033[1;31mFAIL:\033[0m %s\n' "$*" >&2; exit 1; }

command -v tailscale >/dev/null || fail "tailscale not installed — run ./setup.sh first."

# 1) Ensure the tailnet is up.
if tailscale status >/dev/null 2>&1; then
  log "Tailscale already connected."
else
  log "Bringing Tailscale up (authenticate in the browser link)…"
  sudo tailscale up
fi

# 2) Confirm Open WebUI is actually listening locally before we expose it.
if ! curl -fsS --max-time 5 "http://127.0.0.1:${PORT}" >/dev/null 2>&1; then
  warn "Nothing responding on http://127.0.0.1:${PORT} — is Open WebUI running? (docker ps)"
  warn "Continuing anyway; the tailnet route will work once the container is up."
fi

# 3) Publish over HTTPS on the tailnet (TLS terminated by Tailscale).
log "Serving Open WebUI (port ${PORT}) over HTTPS on your tailnet…"
tailscale serve --bg "${PORT}" || fail "tailscale serve failed (needs Tailscale v1.40+ and HTTPS enabled for your tailnet)."

# 4) Resolve THIS machine's MagicDNS name (Self.DNSName — not a peer's) and
#    build the phone URL.
get_self_fqdn() {
  local json
  json="$(tailscale status --json 2>/dev/null)" || return 1
  if command -v jq >/dev/null; then
    jq -r '.Self.DNSName // empty' <<<"$json" | sed 's/\.$//'
  elif command -v python3 >/dev/null; then
    python3 -c 'import sys,json; d=json.load(sys.stdin); print((d.get("Self") or {}).get("DNSName","").rstrip("."))' <<<"$json"
  else
    # Last resort: requires Self to appear before any Peer in the JSON.
    grep -oE '"DNSName":[[:space:]]*"[^"]+"' <<<"$json" | head -n1 | sed -E 's/.*"([^"]+)"/\1/; s/\.$//'
  fi
}
FQDN="$(get_self_fqdn)"
[ -n "${FQDN:-}" ] || fail "Could not resolve your tailnet hostname (tailscale status)."
URL="https://${FQDN}"

echo
log "Open this on your phone (Tailscale app signed in to the same account):"
printf '\n    \033[1;32m%s\033[0m\n\n' "$URL"

# 5) Bonus: terminal QR code to scan straight from the phone camera.
if command -v qrencode >/dev/null; then
  qrencode -t ANSIUTF8 "$URL"
else
  warn "Install 'qrencode' for a scannable QR code here (sudo apt install qrencode)."
fi

echo
log "To stop sharing later: tailscale serve --https=443 off"
