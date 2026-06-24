# Your own AI, everywhere — on a UGREEN NAS

This folder sets up **OpenClaw** as a single, always-on personal assistant that
lives on your UGREEN NAS. Your phone, desktop, and chat apps all connect to that
one hub, so the **same conversation history, memory, and config follow you
everywhere** — you pick up exactly where you left off.

It also wires in a **hybrid brain**: a small private model on the NAS, your
big-VRAM **PC woken on demand** for heavy local work, and **hosted Claude** for
top quality when you want it.

> **The reframe:** unlike claude.ai (where each device has its own login
> session), OpenClaw is *one brain, many windows*. There's nothing to "merge" —
> every device is just a view into the same NAS-hosted assistant.

---

## The architecture

```
   iPhone / iPad ─┐
   Android ───────┤        ┌──────────────────────────────────────────┐
   Mac / PC ──────┼──LAN──▶ │  UGREEN NAS  (always on)                  │
   WhatsApp/TG/   │        │  • OpenClaw Gateway  (the "brain")         │
   Slack/iMessage─┘        │  • all history + memory + config (./data)  │
                           │  • small local model (Ollama, CPU)         │
                           └───────────────┬───────────────────────────┘
                                           │ Wake-on-LAN when needed
                                           ▼
                           ┌───────────────────────────────┐
                           │  Your PC  (32 GB VRAM)         │
                           │  • Ollama big model            │
                           │  • sleeps when idle            │
                           └───────────────────────────────┘
                                           │ when you want top quality
                                           ▼
                              Hosted Claude (your Claude Max / API)
```

---

## Honest reality check (read this first)

- **Fully-local can't match Claude/ChatGPT** on a NAS. Big-boy quality comes from
  huge models on big GPUs. So we go **hybrid**: local for private/quick/offline,
  the PC for strong local, hosted Claude when you want maximum brains.
- **The NAS model is small and CPU-only.** Great for short, private, offline
  questions. Don't expect it to write your essays.
- **The PC tier is the sweet spot for local** — 32 GB VRAM runs a 32B-class model
  well — but it has **cold-start latency** each time it wakes from sleep.
- **Wake-on-LAN is the one finicky part.** It needs host networking + BIOS/NIC
  setup (Part C). If it fights you, there's a no-WoL fallback at the end.

---

## Prerequisites

- A UGREEN NASync (DXP series) running **UGOS Pro** with the **Docker** app
  installed (App Center → Docker).
- SSH enabled on the NAS (UGOS Pro → Terminal/SSH) so you can run `docker compose`.
- Your NAS's LAN IP (e.g. `192.168.1.10`).
- (For the PC tier) a PC on the **same LAN/subnet** with Ollama installed and
  Wake-on-LAN supported.
- (For hosted Claude) your Claude Max login or an Anthropic API key.

---

## Part A — Put these files on the NAS

SSH into the NAS, then copy this `deploy/ugreen-nas/` folder somewhere on a data
volume, e.g. `/volume1/docker/openclaw/`. From inside that folder:

```bash
cp .env.example .env
# edit .env: set OPENCLAW_TZ and (optionally) generate OPENCLAW_GATEWAY_TOKEN:
#   openssl rand -hex 32
mkdir -p data/openclaw data/workspace data/auth-secrets data/ollama
# the container runs as uid 1000; make the state dirs writable by it:
sudo chown -R 1000:1000 data/openclaw data/workspace data/auth-secrets
# the Wake-on-LAN helper must live in the mounted config dir:
cp wake-pc.mjs data/openclaw/wake-pc.mjs
```

---

## Part B — Start the hub (Gateway)

```bash
# Gateway only:
docker compose -f docker-compose.ugreen.yml up -d
# ...or Gateway + small NAS model:
docker compose -f docker-compose.ugreen.yml --profile local-nas up -d
```

Confirm it's healthy:

```bash
curl -fsS http://127.0.0.1:18789/healthz && echo OK
```

Open the Control UI from any browser on your LAN at `http://<NAS-IP>:18789/` and
pair it with your gateway token (from `.env`, or fetch a link):

```bash
docker compose -f docker-compose.ugreen.yml exec openclaw-gateway \
  node dist/index.js dashboard --no-open
```

> All state — `openclaw.json`, memory, session history, auth profiles — now lives
> in `./data` on the NAS. That bind mount **is** your cross-device continuity.
> Back it up and you've backed up your whole assistant.

---

## Part C — The PC tier (big local model + Wake-on-LAN)

**On the PC:**

1. Install Ollama and pull a model that fits 32 GB VRAM, e.g.:
   ```bash
   ollama pull qwen2.5:32b
   ```
2. Make Ollama listen on the LAN (not just localhost):
   ```bash
   # Linux: set OLLAMA_HOST=0.0.0.0:11434 for the service, then restart it.
   # Windows: set the OLLAMA_HOST environment variable to 0.0.0.0:11434.
   ```
3. **Enable Wake-on-LAN** in the PC's BIOS/UEFI *and* in the OS NIC settings
   ("Allow this device to wake the computer" / "Wake on Magic Packet").
4. Set the PC to **sleep on idle** (this is what turns it back off — OpenClaw
   wakes it, the PC's own idle timer puts it back to sleep).
5. Note the PC's **LAN IP** and **MAC address**.

**On the NAS:** edit `data/openclaw/openclaw.json` (or apply via `openclaw config
set`, see Part D) using `openclaw.config.example.json5` as the template. Replace
`<PC-LAN-IP>` and `<PC-MAC>` in the `ollama-pc` provider block.

How it works: when you pick the **Big Local (PC)** model, OpenClaw probes the
PC's Ollama health URL. If the PC is asleep, it runs `wake-pc.mjs`, which sprays
Wake-on-LAN magic packets until Ollama answers, then routes your request through.
This relies on OpenClaw's real
[`localService`](https://docs.openclaw.ai/gateway/local-model-services) hook.

### Networking & Wake-on-LAN

Magic packets are UDP **broadcasts**. The compose file runs the gateway in
**host networking** precisely so those broadcasts (and LAN app discovery) reach
your network. On a default Docker bridge, the broadcast won't escape and the PC
won't wake. If `255.255.255.255` is filtered on your LAN, set
`WAKE_PC_BROADCAST` to your subnet broadcast (e.g. `192.168.1.255`).

---

## Part D — Wire up the models

Easiest path — let onboarding add each provider and your Claude auth:

```bash
docker compose -f docker-compose.ugreen.yml exec openclaw-gateway \
  node dist/index.js onboard
```

- Add **Anthropic / Claude** (sign in with Claude Max, or paste an API key).
- Add **Ollama** local for the NAS model.

Then apply the hybrid routing + the PC provider from
`openclaw.config.example.json5`. You can paste the blocks into
`data/openclaw/openclaw.json` (remove the `//` comments), or set them with:

```bash
docker compose -f docker-compose.ugreen.yml exec openclaw-gateway \
  node dist/index.js models list   # verify everything resolves
```

Switch models per conversation from any app's model picker using the aliases
(**Sonnet**, **Opus**, **Big Local (PC)**, **Quick Local (NAS)**). See
[Local models](https://docs.openclaw.ai/gateway/local-models) and
[Model failover](https://docs.openclaw.ai/concepts/model-failover).

---

## Part E — Connect your devices

- **iOS / Android / desktop apps:** point them at `http://<NAS-IP>:18789` and
  approve the pairing request:
  ```bash
  docker compose -f docker-compose.ugreen.yml exec openclaw-gateway \
    node dist/index.js devices list
  docker compose -f docker-compose.ugreen.yml exec openclaw-gateway \
    node dist/index.js devices approve <requestId>
  ```
- **Chat channels** (WhatsApp / Telegram / Slack / Discord / iMessage, etc.):
  ```bash
  docker compose -f docker-compose.ugreen.yml exec openclaw-gateway \
    node dist/index.js channels login        # WhatsApp QR
  docker compose -f docker-compose.ugreen.yml exec openclaw-gateway \
    node dist/index.js channels add --channel telegram --token "<token>"
  ```
  Docs: [Channels](https://docs.openclaw.ai/) (WhatsApp, Telegram, Discord, …).

### Reaching it away from home

Inside your house, devices hit the NAS directly. To pick up where you left off
**from anywhere**, put your devices and the NAS on a private mesh with
[Tailscale](https://tailscale.com) and use OpenClaw's `tailnet` bind mode — no
ports exposed to the public internet. (Avoid forwarding `18789` straight to the
internet; review [Security hardening](https://docs.openclaw.ai/gateway/security)
first.)

---

## Part F — Updating & backups

```bash
# Update to a newer image (pin a version in .env for control):
docker compose -f docker-compose.ugreen.yml pull
docker compose -f docker-compose.ugreen.yml up -d

# Back up everything that matters — your whole assistant is in ./data:
tar czf openclaw-backup-$(date +%F).tgz data/openclaw data/auth-secrets
```

---

## Troubleshooting

- **PC won't wake:** confirm WoL is on in BIOS *and* OS NIC; confirm the gateway
  is in host networking; try `WAKE_PC_BROADCAST=<subnet>.255`; test the MAC from
  another LAN host with a `wakeonlan`/`wol` tool first.
- **PC wakes but model request hangs:** make sure Ollama listens on
  `0.0.0.0:11434` and `http://<PC-IP>:11434/api/tags` answers from the NAS.
- **Tool calls show up as raw JSON text on a local model:** use the **native**
  Ollama URL (no `/v1`), and consider
  [local model lean mode](https://docs.openclaw.ai/concepts/experimental-features#local-model-lean-mode).
- **Permission errors on `./data`:** `sudo chown -R 1000:1000 data/openclaw
  data/workspace data/auth-secrets` (the image runs as uid 1000).
- **Can't reach the UI:** confirm `--bind lan`, the NAS firewall allows
  `18789`, and you're using the NAS LAN IP.

### No-WoL fallback

If Wake-on-LAN is more trouble than it's worth, just **leave the PC always on**
(remove the `localService` block from the `ollama-pc` provider), or skip the PC
tier entirely and rely on **Quick Local (NAS)** + **hosted Claude**. The
continuity story (one brain, every device) is unchanged either way.

---

## Reference

- `docker-compose.ugreen.yml` — the NAS stack (gateway + optional Ollama)
- `.env.example` — environment template
- `openclaw.config.example.json5` — hybrid model + Wake-on-LAN config
- `wake-pc.mjs` — the Wake-on-LAN helper OpenClaw runs on demand
- Docs: [Docker](https://docs.openclaw.ai/install/docker) ·
  [Local models](https://docs.openclaw.ai/gateway/local-models) ·
  [Local model services](https://docs.openclaw.ai/gateway/local-model-services) ·
  [Ollama](https://docs.openclaw.ai/providers/ollama)
