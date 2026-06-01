#!/usr/bin/env node
import { createHash } from "node:crypto";
// Hybrid RAG (+ optional CRAG gate) against a local Ollama model.
//
// Dense (embeddings -> cosine) + sparse (BM25) retrieval, fused with Reciprocal
// Rank Fusion, then answered by a local chat model. Zero external deps: plain
// Node built-ins + Ollama's native HTTP API. Works against your own GPU box or
// the in-sandbox Ollama -- only OLLAMA_BASE_URL changes.
//
// Usage:
//   node cloud-local-models/rag/hybrid-rag.mjs "what is corrective rag?"
//
// Env:
//   OLLAMA_BASE_URL  default http://127.0.0.1:11434   (native URL, no /v1)
//   CHAT_MODEL       default qwen2.5:0.5b
//   EMBED_MODEL      default nomic-embed-text
//   TOP_K            default 4
//   CRAG             set to 1 to grade retrieved chunks before answering
//   CORPUS_DIR       default <this dir>/corpus
import { readFileSync, readdirSync, writeFileSync, existsSync, statSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const BASE = (process.env.OLLAMA_BASE_URL ?? "http://127.0.0.1:11434").replace(/\/+$/, "");
const CHAT_MODEL = process.env.CHAT_MODEL ?? "qwen2.5:0.5b";
const EMBED_MODEL = process.env.EMBED_MODEL ?? "nomic-embed-text";
const TOP_K = Number(process.env.TOP_K ?? 4);
const USE_CRAG = process.env.CRAG === "1";
const CORPUS_DIR = process.env.CORPUS_DIR ?? join(HERE, "corpus");
const CACHE_FILE = join(HERE, ".embeddings-cache.json");

// --- corpus loading + chunking ---------------------------------------------
// Split each doc into paragraph-ish chunks; keep them small so retrieval is
// granular but each chunk still carries enough context to answer from.
function loadChunks(dir) {
  if (!existsSync(dir)) throw new Error(`corpus dir not found: ${dir}`);
  const files = readdirSync(dir).filter((f) => /\.(md|txt)$/.test(f));
  if (files.length === 0) throw new Error(`no .md/.txt files in ${dir}`);
  const chunks = [];
  for (const file of files) {
    const text = readFileSync(join(dir, file), "utf8");
    for (const para of text.split(/\n\s*\n/)) {
      const body = para.trim();
      if (body.length >= 20) chunks.push({ source: file, text: body });
    }
  }
  return chunks;
}

// --- tokenizer + BM25 (sparse retrieval) ------------------------------------
const STOP = new Set(
  "a an the of to in on at is are was were be by for and or as with from this that it its".split(
    " ",
  ),
);
function tokenize(s) {
  return (
    s
      .toLowerCase()
      .match(/[a-z0-9]+/g)
      ?.filter((t) => t.length > 1 && !STOP.has(t)) ?? []
  );
}

function buildBm25(chunks) {
  const docs = chunks.map((c) => tokenize(c.text));
  const N = docs.length;
  const df = new Map();
  for (const doc of docs) for (const t of new Set(doc)) df.set(t, (df.get(t) ?? 0) + 1);
  const avgdl = docs.reduce((a, d) => a + d.length, 0) / N;
  const tf = docs.map((doc) => {
    const m = new Map();
    for (const t of doc) m.set(t, (m.get(t) ?? 0) + 1);
    return m;
  });
  const idf = (t) => Math.log(1 + (N - (df.get(t) ?? 0) + 0.5) / ((df.get(t) ?? 0) + 0.5));
  const k1 = 1.5,
    b = 0.75;
  return (queryTokens) =>
    docs.map((_, i) => {
      let score = 0;
      const dl = docs[i].length;
      for (const t of queryTokens) {
        const f = tf[i].get(t) ?? 0;
        if (f === 0) continue;
        score += (idf(t) * (f * (k1 + 1))) / (f + k1 * (1 - b + b * (dl / avgdl)));
      }
      return score;
    });
}

// --- Ollama HTTP helpers ----------------------------------------------------
async function ollama(path, body) {
  const res = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`${path} -> ${res.status} ${res.statusText}: ${await res.text()}`);
  return res.json();
}

// Native /api/embed (current) returns { embeddings: [[...]] }.
async function embed(input) {
  const out = await ollama("/api/embed", { model: EMBED_MODEL, input });
  return out.embeddings ?? (out.embedding ? [out.embedding] : []);
}

async function chat(messages) {
  const out = await ollama("/api/chat", { model: CHAT_MODEL, messages, stream: false });
  return out.message?.content ?? "";
}

function cosine(a, b) {
  let dot = 0,
    na = 0,
    nb = 0;
  for (let i = 0; i < a.length; i++) {
    dot += a[i] * b[i];
    na += a[i] * a[i];
    nb += b[i] * b[i];
  }
  return dot / (Math.sqrt(na) * Math.sqrt(nb) || 1);
}

// --- embedding cache (avoid re-embedding an unchanged corpus) ---------------
function corpusHash(chunks) {
  return createHash("sha256")
    .update(EMBED_MODEL + "\0" + chunks.map((c) => c.text).join("\0"))
    .digest("hex");
}

async function embedCorpus(chunks) {
  const hash = corpusHash(chunks);
  if (existsSync(CACHE_FILE)) {
    const cached = JSON.parse(readFileSync(CACHE_FILE, "utf8"));
    if (cached.hash === hash) return cached.vectors;
  }
  const vectors = [];
  for (const c of chunks) vectors.push((await embed(c.text))[0]);
  writeFileSync(CACHE_FILE, JSON.stringify({ hash, vectors }));
  return vectors;
}

// --- Reciprocal Rank Fusion -------------------------------------------------
// Merge the dense and sparse rankings without needing comparable score scales.
function rrf(rankings, k = 60) {
  const score = new Map();
  for (const ranking of rankings) {
    ranking.forEach((idx, rank) => score.set(idx, (score.get(idx) ?? 0) + 1 / (k + rank + 1)));
  }
  return [...score.entries()].sort((a, b) => b[1] - a[1]).map(([idx]) => idx);
}

function rankByScore(scores) {
  return scores
    .map((s, i) => [i, s])
    .sort((a, b) => b[1] - a[1])
    .map(([i]) => i);
}

// --- optional CRAG grading gate ---------------------------------------------
// Ask the model whether each candidate chunk is actually relevant; drop the
// ones graded "no" so the answer prompt only carries trustworthy context.
async function cragFilter(query, candidates) {
  const kept = [];
  for (const c of candidates) {
    const verdict = (
      await chat([
        { role: "system", content: "Reply with exactly one word: yes or no." },
        {
          role: "user",
          content: `Is this passage relevant to the question?\nQuestion: ${query}\nPassage: ${c.text}`,
        },
      ])
    )
      .trim()
      .toLowerCase();
    if (verdict.startsWith("y")) kept.push(c);
  }
  return kept.length ? kept : candidates; // never strip everything
}

// --- main -------------------------------------------------------------------
async function main() {
  const query = process.argv.slice(2).join(" ").trim();
  if (!query) {
    console.error('usage: node hybrid-rag.mjs "your question"');
    process.exit(1);
  }

  const chunks = loadChunks(CORPUS_DIR);
  console.error(`[rag] ${chunks.length} chunks from ${CORPUS_DIR}`);
  console.error(`[rag] ollama=${BASE} chat=${CHAT_MODEL} embed=${EMBED_MODEL} crag=${USE_CRAG}`);

  // Sparse-only path: BM25 retrieval with no model calls. Handy offline and for
  // inspecting what retrieval surfaces before spending tokens on generation.
  if (process.env.RETRIEVE_ONLY === "1") {
    const bm25 = buildBm25(chunks);
    const ranking = rankByScore(bm25(tokenize(query))).slice(0, TOP_K);
    console.log("\n=== TOP CHUNKS (sparse/BM25) ===");
    ranking.forEach((i, n) =>
      console.log(
        `[${n + 1}] ${chunks[i].source}: ${chunks[i].text.slice(0, 90).replace(/\n/g, " ")}...`,
      ),
    );
    return;
  }

  // Dense retrieval.
  const vectors = await embedCorpus(chunks);
  const qvec = (await embed(query))[0];
  const denseRanking = rankByScore(vectors.map((v) => cosine(qvec, v)));

  // Sparse retrieval.
  const bm25 = buildBm25(chunks);
  const sparseRanking = rankByScore(bm25(tokenize(query)));

  // Fuse, take top-K.
  const fused = rrf([denseRanking, sparseRanking]).slice(0, TOP_K);
  let top = fused.map((i) => chunks[i]);

  if (USE_CRAG) {
    const before = top.length;
    top = await cragFilter(query, top);
    console.error(`[rag] CRAG kept ${top.length}/${before} chunks`);
  }

  // Generate grounded answer.
  const context = top.map((c, i) => `[${i + 1}] (${c.source})\n${c.text}`).join("\n\n");
  const answer = await chat([
    {
      role: "system",
      content:
        "Answer using ONLY the provided context. Cite sources as [n]. If the context does not contain the answer, say so.",
    },
    { role: "user", content: `Context:\n${context}\n\nQuestion: ${query}` },
  ]);

  console.log("\n=== ANSWER ===\n" + answer.trim());
  console.log("\n=== SOURCES ===");
  top.forEach((c, i) =>
    console.log(`[${i + 1}] ${c.source}: ${c.text.slice(0, 80).replace(/\n/g, " ")}...`),
  );
}

main().catch((e) => {
  console.error("[rag] error:", e.message);
  process.exit(1);
});
