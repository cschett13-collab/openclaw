# Cloud Environment for Local Models

Run OpenClaw in the cloud while your **models** stay open-weight — either served
on your own GPU box (production) or spun up inside the cloud container (CI/demo).

This folder is the companion to `../rtx5090-agent/` (which provisions a real
local GPU + Ollama). Here we wire OpenClaw's model providers to those local
backends, and document the two ways "cloud + local models" actually fit together.

> Naming: **OpenClaw** is the product; `openclaw` is the CLI/config key. Config
> below uses the canonical `models.providers.<id>` shape. All keys were taken
> from `docs/providers/ollama.md`, `docs/providers/lmstudio.md`, and
> `docs/gateway/local-models.md`.

---

## The decision matrix

|                         | A. Connect to your real box               | B. Serve in the cloud sandbox             |
| ----------------------- | ----------------------------------------- | ----------------------------------------- |
| Where the model runs    | Your GPU machine (RTX 5090, Mac, LAN box) | Inside the cloud container                |
| Hardware                | Real GPU                                  | CPU-only, ephemeral                       |
| Good for                | Production, real throughput               | CI smoke tests, demos, wiring checks      |
| How OpenClaw reaches it | `baseUrl` → tunnel / LAN / tailnet URL    | `baseUrl` → `http://127.0.0.1:11434`      |
| Persistence             | Survives; box is yours                    | Gone when the container is reclaimed      |
| Model size              | Whatever your VRAM allows                 | Tiny (e.g. `qwen2.5:0.5b`, `llama3.2:1b`) |

Both paths use the **same** OpenClaw provider contract — only the `baseUrl`
(and auth) differ. Pick the config file accordingly.

---

## A. Connect the cloud OpenClaw to your real local box (production)

Your model already runs locally (see `../rtx5090-agent/` for the Ollama + GPU
setup). Expose that endpoint to the cloud and point OpenClaw at it.

### A1. Expose the endpoint

Pick one — do **not** put a raw Ollama port on the public internet without auth:

- **Tailscale / tailnet** (recommended): both machines join your tailnet, use the
  box's tailnet name, e.g. `http://gpu-box.tailnet-name.ts.net:11434`.
- **SSH reverse tunnel**: `ssh -R 11434:localhost:11434 user@cloud-host` →
  reach it at `http://127.0.0.1:11434` from inside the cloud env.
- **Authenticated reverse proxy** (Caddy/Nginx + bearer token) if you must use a
  public hostname; then set a _real_ `OLLAMA_API_KEY`, not the local marker.

### A2. Point OpenClaw at it

Use `config/openclaw.ollama-remote.json`. Key rules (from `docs/providers/ollama.md`):

- Use the **native** Ollama URL — **no `/v1`** suffix (the `/v1` OpenAI-compat
  path breaks tool calling).
- For loopback / LAN / `.local` / bare-hostname hosts you may use the
  `ollama-local` marker as `apiKey`. For a **public** hostname use a real key.

```jsonc
{
  "models": {
    "providers": {
      "ollama-remote": {
        "baseUrl": "http://gpu-box.tailnet-name.ts.net:11434", // native URL, no /v1
        "apiKey": "ollama-local", // real key if public host
        "api": "ollama",
        "models": [{ "id": "ollama-remote/qwen2.5-coder:32b", "name": "Qwen2.5 Coder 32B" }],
      },
    },
  },
  "agents": { "defaults": { "model": { "primary": "ollama-remote/qwen2.5-coder:32b" } } },
}
```

LM Studio / vLLM on your box are OpenAI-compatible — use
`config/openclaw.openai-compat.json` and keep the `/v1` suffix for those.

---

## B. Serve an open model inside the cloud sandbox (CI / demo)

The cloud container is CPU-only and ephemeral, so this is for **wiring checks,
CI, and demos** — not real GPU throughput. Two ways to bring up a backend:

### B1. One-shot script (Ollama, CPU)

```bash
cloud-local-models/serve-local-model.sh            # installs ollama, serves qwen2.5:0.5b
MODEL=llama3.2:1b cloud-local-models/serve-local-model.sh
```

It installs Ollama if missing, starts `ollama serve` in the background, waits for
`/api/tags` to be healthy, and pulls a small model. Then point OpenClaw at the
loopback endpoint with `config/openclaw.ollama-local.json`:

```jsonc
{
  "models": {
    "providers": {
      "ollama": {
        "baseUrl": "http://127.0.0.1:11434",
        "apiKey": "ollama-local",
        "api": "ollama",
      },
    },
  },
  "agents": { "defaults": { "model": { "primary": "ollama/qwen2.5:0.5b" } } },
}
```

> Leaving `models.providers.ollama` undefined and just setting
> `OLLAMA_API_KEY=ollama-local` also works — OpenClaw then auto-discovers models
> from `http://127.0.0.1:11434` (see `docs/providers/ollama.md`).

### B2. docker-compose (Ollama or vLLM)

`docker-compose.yml` brings up an Ollama service on `:11434`. Use it locally or
in CI where Docker is available:

```bash
docker compose -f cloud-local-models/docker-compose.yml up -d ollama
docker compose -f cloud-local-models/docker-compose.yml exec ollama ollama pull qwen2.5:0.5b
```

A commented `vllm` service is included for OpenAI-compatible serving (needs a
GPU runtime; uses `config/openclaw.openai-compat.json`).

---

## Files in this folder

| File                                 | Purpose                                                                       |
| ------------------------------------ | ----------------------------------------------------------------------------- |
| `serve-local-model.sh`               | Install + run Ollama with a small model inside the sandbox (path B1)          |
| `docker-compose.yml`                 | Ollama (and optional vLLM) services for CI/demo (path B2)                     |
| `config/openclaw.ollama-local.json`  | OpenClaw config → in-sandbox Ollama (loopback)                                |
| `config/openclaw.ollama-remote.json` | OpenClaw config → your real Ollama box (tunnel/LAN)                           |
| `config/openclaw.openai-compat.json` | OpenClaw config → any OpenAI-compatible server (LM Studio / vLLM / llama.cpp) |

To apply a config: copy it to `~/.openclaw/config.json`, or run
`openclaw onboard` and choose Ollama / LM Studio (see the provider docs for the
non-interactive flags).
