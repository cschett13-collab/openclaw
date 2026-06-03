# Phase 1 — The Self-Learning Private Brain (Memory via RAG)

You don't fine-tune a model to make it "remember" you. Fine-tuning is expensive,
static, and brittle. To get a private model that gets sharper the more you talk
to it, you give it **continuous memory via vector retrieval (RAG)**. Because the
stack already runs Open WebUI over Ollama (see [`README.md`](./README.md)), you
already have every piece needed to do this locally.

## How it actually works

```
 You type ──► Auto-Memory filter ──► extract facts ──► embed ──► ChromaDB
                                                                    │
 New blank chat ──► retrieve relevant memories ──► inject into prompt context ──► model answers
```

1. **Facts are extracted** from your messages (preferences, business rules,
   pipeline details).
2. They're turned into **embeddings** (vectors) and stored in a local vector
   database (**ChromaDB** by default) on your drive.
3. On the next chat, *before* the model reads your prompt, the system searches
   that database, pulls the relevant facts, and **injects them invisibly** into
   the context.
4. The model feels like it's learning and growing with you — mathematically it's
   just querying a private, well-organized index of your history.

Where it lives: ChromaDB sits inside the `open-webui` Docker volume from our
compose file, at `/app/backend/data/vector_db`. Memories never leave your box.

> **Important correction to the "just flip a switch" version:** Open WebUI's
> built-in **Memory** is *manual* by default — you add memories explicitly, or
> the model writes them through the memories API. The "lightweight background
> process that extracts facts from every chat automatically" is an **Auto-Memory
> filter function** you install (Step 2 below). It's still local and still uses
> your own model to do the extraction — it's just an add-on, not a single toggle.

---

## Step 1 — Enable Memory

1. **Settings → Personalization → Memory** → toggle **Memory** on. This stores
   per-user memories and lets the model recall them.
2. (Admin) **Settings → Admin → Users / Permissions** — make sure the Memory
   feature is permitted for the accounts that should use it.
3. Sanity check: add one manually ("My business is roofing lead-gen in the Fox
   Valley") and confirm it appears in the Memory list.

## Step 2 — Turn on automatic fact extraction (the "self-learning" part)

This is the background process that makes it feel alive. It's a **Filter
function**:

1. Go to **Workspace → Functions → `+`** (create a new Filter function).
2. Paste an **Auto-Memory** filter (community function — search the Open WebUI
   community functions site for "Auto Memory" / "Adaptive Memory", or write your
   own `outlet` filter that calls the `/api/v1/memories/add` endpoint).
3. Configure its **valves**: point it at a *small, fast local model* (e.g.
   `llama3.1:8b`) for the extraction pass so it doesn't tie up your big model,
   and set how aggressively it should save facts.
4. **Enable the filter globally** (or per-model). From now on, after each
   exchange the filter quietly asks the small model "what's worth remembering
   here?" and writes the result into Memory.

> Keep the extractor model small and separate from your chat model. You want
> fact extraction to be cheap and instant; the RTX 5090 can run both at once.

## Step 3 — Tune the embeddings (and put them on the 5090)

RAG quality = embedding quality. **Settings → Admin → Documents** (the RAG
panel):

- **Embedding engine:** by default Open WebUI uses a local
  `sentence-transformers` model that runs on **CPU** in the `:main` image.
  For better recall *and* GPU speed, switch the engine to **Ollama** and use a
  proper embedding model:

  ```bash
  ollama pull nomic-embed-text      # or: mxbai-embed-large
  ```

  Then set the embedding model in the RAG panel to `nomic-embed-text`. Now
  embeddings run on the 5090 via Ollama, same as your chat models.
- **Chunk size / overlap / Top-K:** start with the defaults; raise Top-K if the
  model "forgets" things it should know, lower it if irrelevant facts leak in.
- Alternatively, run the **`:cuda`** image with `--gpus all` to GPU-accelerate
  the built-in embedder instead of offloading to Ollama (see the README
  "Variations" section).

## Step 4 — Feed it your knowledge (RAG documents)

Memory captures conversational facts. For static reference material — pricing
sheets, SOPs, business rules — use **Knowledge bases**:

1. **Workspace → Knowledge → `+`**, then drag in PDFs / docs.
2. In a chat, type `#` to attach a knowledge base, or attach it permanently to a
   custom model under **Workspace → Models**.
3. The model now answers grounded in those documents, retrieved the same way as
   memories.

---

## Privacy & hygiene

- Everything (facts, embeddings, documents) stays in the `open-webui` Docker
  volume on your machine. Nothing is sent to a cloud provider unless you
  explicitly add a cloud model.
- Back up the volume to keep your brain: `docker run --rm -v open-webui:/data
  -v "$PWD":/backup busybox tar czf /backup/open-webui-backup.tgz /data`.
- Review and prune memories periodically (Settings → Personalization → Memory) —
  bad or stale facts get retrieved too, and degrade answers.

## References

- Open WebUI features (Memory, RAG): https://docs.openwebui.com/features/
- Open WebUI functions (filters): https://docs.openwebui.com/features/plugin/functions/
- Embeddings via Ollama: https://docs.openwebui.com/tutorials/integrations/
