# Local AI Stack — Open WebUI + Ollama + Tailscale

A self-hosted, ChatGPT-class private AI setup for a Pop!_OS workstation with an
NVIDIA RTX 5090, reachable securely from your phone anywhere.

```
 ┌─────────────┐        ┌──────────────────┐        ┌─────────────────────┐
 │   Phone /    │ Tailscale │   Open WebUI     │  HTTP   │   Ollama (native)   │
 │   Laptop     │◄────────►│  (Docker :3000)  │◄───────►│  127.0.0.1:11434    │
 │  (anywhere)  │ WireGuard │   "The Brain"    │  /api   │  RTX 5090 compute   │
 └─────────────┘        └──────────────────┘        └─────────────────────┘
```

## The three layers

**Layer 1 — The Brain (Open WebUI).** A pro-grade, self-hosted chat interface
that matches ChatGPT/Claude feature-for-feature: native function calling (paste
Python tools), RAG (drag-and-drop PDFs / vector DB), and multi-model routing
(local 5090 models + cloud API keys in one place). Don't hand-roll Python
tool-calling wrappers — Open WebUI already does it.

**Layer 2 — The Compute (Ollama, headless).** Runs natively in the background
on Pop!_OS, exposing local models over `http://127.0.0.1:11434`. It does the
text-generation math directly on the RTX 5090. Open WebUI is just a client.

**Layer 3 — Remote Access (Tailscale).** A zero-config mesh VPN over WireGuard.
No router port-forwarding, no exposing your home network to the public internet.
It builds an encrypted tunnel from your phone to your desktop so the whole stack
is reachable from anywhere.

> **Why is Open WebUI in Docker but Ollama is native?** The RTX 5090 (Blackwell)
> work happens inside Ollama. Running Ollama natively gives it direct, fully
> supported access to your system NVIDIA driver/CUDA — no container GPU plumbing
> to debug. Open WebUI is a stateless web app, so a container is the cleanest way
> to run it. The two talk over plain HTTP on the loopback/host interface.

---

## Quick start

```bash
git clone <this-repo> && cd local-ai-stack
./setup.sh            # installs Ollama, configures host binding, starts Open WebUI, sets up Tailscale
```

Then open `http://localhost:3000` on the workstation, or
`http://<your-machine>.<tailnet>.ts.net:3000` from your phone.

The sections below explain exactly what `setup.sh` does, so you can also run the
steps by hand.

---

## Step 1 — Fire up the Docker stack

Install Docker Engine + Compose if you don't have it (Pop!_OS / Ubuntu):

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker "$USER"   # log out/in (or: newgrp docker) so you can run docker without sudo
```

Start Open WebUI and point it at your **native** Ollama. The unified command:

```bash
docker run -d \
  --name open-webui \
  --restart unless-stopped \
  -p 3000:8080 \
  --add-host=host.docker.internal:host-gateway \
  -e OLLAMA_BASE_URL=http://host.docker.internal:11434 \
  -v open-webui:/app/backend/data \
  ghcr.io/open-webui/open-webui:main
```

What each flag does:

| Flag | Purpose |
|------|---------|
| `-p 3000:8080` | Open WebUI listens on `8080` inside the container; expose it as `3000` on the host. |
| `--add-host=host.docker.internal:host-gateway` | Lets the container resolve the host machine, so it can reach native Ollama. |
| `-e OLLAMA_BASE_URL=...` | Tells Open WebUI where Ollama lives. |
| `-v open-webui:/app/backend/data` | Persists accounts, chats, settings, and RAG documents across restarts. |
| `--restart unless-stopped` | Comes back automatically after reboots. |

Prefer the version-pinned, declarative form? Use the included compose file:

```bash
docker compose up -d
```

> **About "GPU acceleration".** The Open WebUI container itself does **not** need
> `--gpus all` in this native-Ollama topology — the GPU math runs in Ollama, not
> in the web app. Only add `--gpus all` (and switch to the `:cuda` image) if you
> want Open WebUI's *built-in* features (local embeddings for RAG, speech-to-text)
> to use the GPU. See "Variations" below.

---

## Step 2 — The compute: install and expose Ollama

Install Ollama natively:

```bash
curl -fsSL https://ollama.com/install.sh | sh
```

The installer registers a `systemd` service. **Verify your GPU is detected** —
the RTX 5090 (Blackwell, compute capability `sm_120`) needs a recent Ollama and
a CUDA 12.x-class driver:

```bash
nvidia-smi                 # driver sees the 5090?
journalctl -u ollama | grep -i "inference compute"   # Ollama logs the GPU it found
```

If the 5090 isn't picked up, update your NVIDIA driver (Pop!_OS:
`sudo apt update && sudo apt install system76-driver-nvidia`) and upgrade Ollama
(re-run the install script — it pulls the latest, which carries newer CUDA
runtimes for Blackwell).

### Let the container reach Ollama

By default Ollama binds only to `127.0.0.1`, which a Docker container cannot
reach via `host.docker.internal`. Bind it to all interfaces with a systemd
override:

```bash
sudo systemctl edit ollama
```

Add:

```ini
[Service]
Environment="OLLAMA_HOST=0.0.0.0:11434"
```

Then:

```bash
sudo systemctl daemon-reload
sudo systemctl restart ollama
```

> **Security note:** `0.0.0.0` means Ollama answers on every interface on the
> box. That's fine when the machine sits behind your LAN/Tailscale and isn't
> port-forwarded to the internet. If you want to be stricter, bind to the Docker
> bridge gateway (typically `172.17.0.1:11434`) instead of `0.0.0.0`. If you run
> Open WebUI with `--network=host`, you can keep Ollama on `127.0.0.1` and use
> `OLLAMA_BASE_URL=http://127.0.0.1:11434`.

### Pull a model

```bash
ollama pull llama3.1:8b        # quick general model
ollama pull qwen2.5-coder:32b  # the 5090's 32GB VRAM eats this for breakfast
ollama list
```

Models you pull appear automatically in Open WebUI's model dropdown.

---

## Step 3 — Remote mobile access with Tailscale

Install and bring up Tailscale on the workstation:

```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
```

Authenticate in the browser link it prints. Install the Tailscale app on your
phone and sign in with the **same account** — they join the same private tailnet.

Find your machine's tailnet address:

```bash
tailscale status        # shows the machine name and 100.x.y.z IP
tailscale ip -4
```

From your phone (with Tailscale on), browse to:

```
http://<machine-name>:3000          # MagicDNS short name
http://100.x.y.z:3000               # or the raw Tailscale IP
```

### Optional: HTTPS without certificates to manage

Tailscale can terminate TLS for you and serve Open WebUI over `https` on your
tailnet (handy because some mobile features prefer a secure context):

```bash
tailscale serve --bg 3000
```

This publishes `https://<machine-name>.<tailnet>.ts.net` to your devices only —
still never exposed to the public internet. Undo with `tailscale serve --https=443 off`.

> Do **not** use `tailscale funnel` unless you deliberately want this reachable
> from the public internet. Funnel breaks the "private tunnel only" guarantee.

---

## First run

1. Open `http://localhost:3000` on the workstation.
2. Create the first account — **the first user becomes the admin.** Do this
   before exposing anything over Tailscale.
3. Confirm your Ollama models show up in the top-left model picker.
4. Settings → Admin → Connections verifies the Ollama URL if a model is missing.

---

## Using the pro features

- **Tools (function calling):** Workspace → Tools → `+`. Paste a Python tool
  (web search, DB query, file read), save, then enable it per-chat with the `+`.
- **RAG / documents:** click `#` in the chat box or drag a PDF in. Open WebUI
  chunks + embeds it and the model answers grounded in your files. Knowledge
  bases live under Workspace → Knowledge.
- **Multi-model routing:** Settings → Admin → Connections. Add your native
  Ollama (already there) plus any OpenAI-compatible cloud endpoint + API key.
  Local 5090 models and cloud models then live in the same dropdown.

---

## Variations

**GPU-accelerated Open WebUI features (RAG embeddings, STT).** Use the CUDA image
and pass the GPU. Requires the NVIDIA Container Toolkit
(`sudo apt install nvidia-container-toolkit && sudo systemctl restart docker`):

```bash
docker run -d --name open-webui --restart unless-stopped \
  --gpus all \
  -p 3000:8080 \
  --add-host=host.docker.internal:host-gateway \
  -e OLLAMA_BASE_URL=http://host.docker.internal:11434 \
  -v open-webui:/app/backend/data \
  ghcr.io/open-webui/open-webui:cuda
```

**All-in-one (Ollama bundled inside the Open WebUI container).** Simplest, but
gives up the "native Ollama" benefits above. One container, GPU passed through:

```bash
docker run -d --name open-webui --restart unless-stopped \
  --gpus all \
  -p 3000:8080 \
  -v ollama:/root/.ollama \
  -v open-webui:/app/backend/data \
  ghcr.io/open-webui/open-webui:ollama
```

---

## Operations cheat sheet

```bash
# Update Open WebUI to the latest image
docker compose pull && docker compose up -d      # (or the docker run equivalent)
docker image prune -f

# Logs / status
docker logs -f open-webui
docker ps

# Update Ollama and models
curl -fsSL https://ollama.com/install.sh | sh    # re-run upgrades in place
ollama pull <model>

# Tailscale
tailscale status
sudo tailscale up --accept-routes
```

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| No models in the dropdown | Ollama not reachable from the container. Check `OLLAMA_HOST=0.0.0.0` override and `docker exec open-webui curl -s http://host.docker.internal:11434/api/tags`. |
| `connection refused` to Ollama | systemd override not applied — `sudo systemctl restart ollama`, confirm with `ss -tlnp | grep 11434`. |
| Models run on CPU (slow) | Driver/Ollama too old for Blackwell. Update the NVIDIA driver and re-run the Ollama installer; check `journalctl -u ollama | grep -i gpu`. |
| Can't reach `:3000` from phone | Tailscale not up on one side, or you used the LAN IP. Use the MagicDNS name and confirm `tailscale status` lists both devices online. |
| Port 3000 already taken | Change the host side: `-p 8081:8080`. |

## References

- Open WebUI docs: https://docs.openwebui.com/
- Ollama: https://github.com/ollama/ollama
- Tailscale: https://tailscale.com/kb/
