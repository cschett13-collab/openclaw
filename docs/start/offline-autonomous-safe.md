---
summary: "Run OpenClaw fully offline on local models, with autonomous agents, content-safety guardrails, and status updates you can watch from one place"
read_when:
  - You want agents that work on their own without you sitting there
  - You want to run on your own local models (no cloud, no per-token bills, no third-party data sharing)
  - You want safety guardrails on what agents can do
  - You want one place to see what agents are doing and proof they are still working
title: "Offline, autonomous, and safe"
sidebarTitle: "Offline + autonomous + safe"
---

This guide stitches together four things OpenClaw already does, into one "set it and forget it" setup:

1. **Offline** — run on your own local models. No internet round-trips for inference, no per-token bills, no prompts leaving your machine.
2. **Autonomous** — agents run on a schedule and act on their own.
3. **Safe** — guardrails limit what an autonomous agent can do.
4. **Watchable** — every run reports back, and failures alert you, so you can see what happened from one place.

Each section links to the deep-dive page for that feature. Start here, follow the links when you want more.

<Note>
Local models are a real trade-off, not a free lunch. Smaller or heavily quantized models raise the bar on context size and prompt-injection defense. Read [Local models](/gateway/local-models) for the hardware floor and the safety caveats before you wire an autonomous agent to a tiny local model.
</Note>

## 1. Run offline on local models

The lowest-friction local backend is [Ollama](/providers/ollama). Install Ollama, pull a model, then point OpenClaw at your local Ollama host.

```json5
{
  models: {
    providers: {
      ollama: {
        // Native Ollama API. Do NOT add /v1 — that breaks tool calling.
        baseUrl: "http://127.0.0.1:11434",
        api: "ollama",
        // Marker credential for loopback/LAN hosts; not a real key.
        apiKey: "ollama-local",
        timeoutSeconds: 300,
        models: [
          {
            id: "gemma4",
            name: "gemma4",
            input: ["text"],
            contextWindow: 32768,
            params: { num_ctx: 32768, keep_alive: "15m" },
          },
        ],
      },
    },
  },
  agents: {
    defaults: {
      model: { primary: "ollama/gemma4" },
    },
  },
}
```

Keep memory/embeddings local too, so nothing leaves the box:

```json5
{
  agents: {
    defaults: {
      memorySearch: {
        provider: "ollama",
        model: "nomic-embed-text",
        remote: { baseUrl: "http://127.0.0.1:11434", apiKey: "ollama-local" },
      },
    },
  },
}
```

For GPU rigs, LM Studio, vLLM, SGLang, LiteLLM, or other OpenAI-compatible servers, see [Local models](/gateway/local-models). For Ollama specifics (vision models, multiple hosts, thinking control) see [Ollama](/providers/ollama).

<Tip>
The fastest path is `openclaw onboard` and choosing local mode — it writes the provider block for you. Use the config above when you want to set it by hand.
</Tip>

## 2. Make agents autonomous

Autonomy in OpenClaw is scheduled work. You tell an agent *when* to run and *what* to do, and it runs without you. The simplest way is to ask the agent in plain language ("every weekday at 6pm, summarize my unread mail and send it to me"); under the hood that creates a **cron job**.

A cron job carries:

- a **schedule** — `kind: "cron"` with an `expr` (e.g. `"0 18 * * *"`), or `kind: "every"` with `everyMs`, plus an optional `tz` timezone;
- a **payload** — usually `kind: "agentTurn"` with the `message` (the instruction) the agent runs;
- **delivery** and **failureAlert** — covered in section 4.

See [Cron jobs](/automation/cron-jobs) for the full schema and [Standing orders](/automation/standing-orders) for durable "always do this" instructions. For the difference between scheduled cron and the always-on heartbeat loop, see [Cron vs heartbeat](/automation/cron-vs-heartbeat).

## 3. Add content-safety guardrails

An autonomous agent acting on its own is exactly where guardrails matter most. OpenClaw gives you layered controls — use several together.

### Limit which tools a scheduled run can use

A cron job's `agentTurn` payload accepts a `toolsAllow` allowlist. The run can only use the tools you name, so a "summarize my mail" job can read and message but cannot, say, run shell commands.

```json5
{
  // inside a cron job payload
  payload: {
    kind: "agentTurn",
    message: "Summarize today's unread mail and send me the digest.",
    toolsAllow: ["gmail", "message"],
  },
}
```

### Require approval before risky actions

`approvals` forwards a confirmation request to you before an agent runs a guarded action (shell exec, plugin actions). You approve from your chat channel; nothing runs until you say yes.

```json5
{
  approvals: {
    exec: {
      enabled: true,
      targets: [{ channel: "telegram", to: "<your-user-id>" }],
    },
  },
}
```

See [Gateway security](/gateway/security) for the shell allowlist (`SafeBin`) and exec-approval behavior.

### Inspect or block messages with hooks

Message hooks (`message:received`, `message:sent`) let you screen content before it is processed or sent. This is where you can wire a **local guard model** — run a moderation model on your own Ollama host and reject content that fails it, so safety filtering also stays offline. See [Hooks](/automation/hooks).

<Warning>
Guardrails reduce risk; they do not erase it. A small local model is easier to jailbreak via prompt injection than a frontier model. Keep autonomous agents on the least privilege they need (`toolsAllow`), gate destructive actions behind `approvals`, and prefer the largest local model your hardware can host. See [Local models](/gateway/local-models) and [Security](/gateway/security).
</Warning>

## 4. Watch what agents do and prove they are working

This is the part that makes "set and forget" trustworthy: every scheduled run can report back, and silent failures alert you. You configure this per cron job.

### Get a report after every run

Set the job's `delivery` so each finished run lands in your chat (`announce`) or hits a URL you control (`webhook`):

```json5
{
  // announce the result to a chat channel
  delivery: { mode: "announce", channel: "telegram", to: "<your-user-id>" },
}
```

```json5
{
  // or POST the finished-run event to your own endpoint/dashboard
  delivery: { mode: "webhook", to: "https://your-host.example/openclaw-runs" },
}
```

### Get alerted when a job stops working

`failureAlert` pings you after a job fails repeatedly, with a cooldown so you are not spammed:

```json5
{
  failureAlert: {
    after: 2,
    channel: "telegram",
    mode: "announce",
    cooldownMs: 3600000,
  },
}
```

### One place to see everything

- **Your messaging channel** is the simplest "one app for all": route every job's `delivery` and `failureAlert` to the same chat (Telegram, Discord, Slack, etc.) and you get a single running feed of what agents did and any failures.
- **The OpenClaw apps** ([macOS](/platforms/macos), [iOS](/platforms/ios), [Android](/platforms/android)) connect to your gateway to view sessions and status from one screen.
- **`openclaw doctor`** checks that your config and providers are healthy.
- For metrics/observability over time, the gateway can export to [Prometheus](/gateway/prometheus) and [OpenTelemetry](/gateway/opentelemetry).

## Putting it together

1. Wire a local Ollama model (section 1) and confirm a normal chat works offline.
2. Ask your agent to schedule one small recurring task with a tight `toolsAllow` (sections 2–3).
3. Point that job's `delivery` and `failureAlert` at your main chat channel (section 4).
4. Watch one cycle land in chat. Once you trust it, add more jobs.

Deep dives: [Local models](/gateway/local-models) · [Ollama](/providers/ollama) · [Cron jobs](/automation/cron-jobs) · [Standing orders](/automation/standing-orders) · [Hooks](/automation/hooks) · [Security](/gateway/security)
