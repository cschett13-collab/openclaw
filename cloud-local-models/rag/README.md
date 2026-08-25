# Hybrid RAG against a local model

A self-contained **Hybrid RAG** pipeline (dense embeddings + BM25 sparse +
Reciprocal Rank Fusion) with an optional **CRAG** grading gate, answered by a
local model over Ollama. Zero external dependencies — plain Node + Ollama's
native HTTP API.

This is #1 (Hybrid) and #4 (Corrective) from the "Top 5 RAG Architectures"
reference. It runs against **your own GPU box** or the **in-sandbox Ollama** —
only `OLLAMA_BASE_URL` changes.

## How it works

```
query ──┬─ embed ─→ cosine vs chunk vectors ─→ dense ranking ─┐
        └─ tokenize ─→ BM25 ──────────────────→ sparse ranking ─┴─ RRF ─→ top-K
                                                                          │
                                          [optional CRAG: grade each chunk, drop irrelevant]
                                                                          │
                                                     context + question ─→ local LLM ─→ answer + sources
```

- **Dense**: embeds each chunk with `EMBED_MODEL`, ranks by cosine similarity.
  Embeddings are cached to `.embeddings-cache.json` (keyed by model + corpus
  hash) so an unchanged corpus is not re-embedded.
- **Sparse**: classic BM25 (k1=1.5, b=0.75) over a simple tokenizer.
- **Fusion**: Reciprocal Rank Fusion merges the two rankings without needing
  comparable score scales.
- **CRAG** (opt-in): asks the model yes/no whether each top chunk is relevant and
  drops the ones graded "no" (never strips everything).

## Run it

Point at your box (native Ollama URL, **no `/v1`**) and make sure both a chat and
an embedding model are pulled:

```bash
# on the Ollama host:
ollama pull qwen2.5-coder:32b      # or any chat model
ollama pull nomic-embed-text       # embedding model

# run a query:
OLLAMA_BASE_URL="http://gpu-box.tailnet-name.ts.net:11434" \
CHAT_MODEL="qwen2.5-coder:32b" \
EMBED_MODEL="nomic-embed-text" \
node cloud-local-models/rag/hybrid-rag.mjs "what is corrective rag?"

# add the CRAG grading gate:
CRAG=1 node cloud-local-models/rag/hybrid-rag.mjs "how do I reduce hallucination?"
```

Inspect retrieval with no model calls (offline-friendly):

```bash
RETRIEVE_ONLY=1 node cloud-local-models/rag/hybrid-rag.mjs "answers that live in relationships"
```

## Config (env)

| Var               | Default                  | Notes                                 |
| ----------------- | ------------------------ | ------------------------------------- |
| `OLLAMA_BASE_URL` | `http://127.0.0.1:11434` | Native Ollama URL, no `/v1`           |
| `CHAT_MODEL`      | `qwen2.5:0.5b`           | Any pulled chat model                 |
| `EMBED_MODEL`     | `nomic-embed-text`       | Any pulled embedding model            |
| `TOP_K`           | `4`                      | Chunks fed to the LLM                 |
| `CRAG`            | unset                    | `1` enables the grading gate          |
| `RETRIEVE_ONLY`   | unset                    | `1` = sparse retrieval only, no model |
| `CORPUS_DIR`      | `./corpus`               | Folder of `.md`/`.txt` docs           |

## Your corpus

Drop `.md` / `.txt` files into `corpus/`. Docs are split into paragraph-sized
chunks. The included `corpus/rag-architectures.md` is a sample so you can test
immediately (e.g. ask "what is GraphRAG?").
