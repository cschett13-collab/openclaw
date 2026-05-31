#!/usr/bin/env bash
# Local AI Stack bootstrapper for Pop!_OS / Ubuntu.
# Installs/uses: Ollama (native), Open WebUI (Docker), Tailscale.
# Safe to re-run — every step is idempotent.
#
# Usage:  ./setup.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
log()  { printf '\033[1;36m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m!! \033[0m %s\n' "$*" >&2; }
have() { command -v "$1" >/dev/null 2>&1; }

# ---------------------------------------------------------------------------
# Layer 2: Ollama (native, GPU)
# ---------------------------------------------------------------------------
if have ollama; then
  log "Ollama already installed: $(ollama --version 2>/dev/null || echo present)"
else
  log "Installing Ollama (native)…"
  curl -fsSL https://ollama.com/install.sh | sh
fi

log "Configuring Ollama to listen on 0.0.0.0 so the Open WebUI container can reach it…"
sudo mkdir -p /etc/systemd/system/ollama.service.d
sudo tee /etc/systemd/system/ollama.service.d/override.conf >/dev/null <<'EOF'
[Service]
Environment="OLLAMA_HOST=0.0.0.0:11434"
EOF
sudo systemctl daemon-reload
sudo systemctl restart ollama || warn "Could not restart ollama via systemd; start it manually if needed."

if have nvidia-smi; then
  log "GPU check:"
  nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader || true
else
  warn "nvidia-smi not found — install the NVIDIA driver (Pop!_OS: sudo apt install system76-driver-nvidia) for GPU acceleration."
fi

# ---------------------------------------------------------------------------
# Layer 1: Open WebUI (Docker)
# ---------------------------------------------------------------------------
if ! have docker; then
  log "Installing Docker Engine…"
  curl -fsSL https://get.docker.com | sh
  sudo usermod -aG docker "$USER" || true
  warn "Added you to the 'docker' group. Log out/in (or run 'newgrp docker') so docker works without sudo."
fi

DOCKER="docker"
docker info >/dev/null 2>&1 || DOCKER="sudo docker"

log "Starting Open WebUI…"
if $DOCKER compose version >/dev/null 2>&1; then
  ( cd "$SCRIPT_DIR" && $DOCKER compose up -d )
else
  $DOCKER run -d \
    --name open-webui \
    --restart unless-stopped \
    -p 3000:8080 \
    --add-host=host.docker.internal:host-gateway \
    -e OLLAMA_BASE_URL=http://host.docker.internal:11434 \
    -v open-webui:/app/backend/data \
    ghcr.io/open-webui/open-webui:main
fi

# ---------------------------------------------------------------------------
# Layer 3: Tailscale (remote access)
# ---------------------------------------------------------------------------
if have tailscale; then
  log "Tailscale already installed."
else
  log "Installing Tailscale…"
  curl -fsSL https://tailscale.com/install.sh | sh
fi

if tailscale status >/dev/null 2>&1; then
  log "Tailscale already connected."
else
  warn "Run 'sudo tailscale up' and authenticate in the browser to join your tailnet."
fi

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------
cat <<DONE

$(log "Setup complete.")
  Local:    http://localhost:3000
  Tailnet:  http://$(hostname):3000   (with Tailscale running on both devices)

Next:
  1. Open the local URL and create the FIRST account — it becomes the admin.
  2. Pull a model:   ollama pull llama3.1:8b
  3. Optional HTTPS over your tailnet:   tailscale serve --bg 3000
DONE
