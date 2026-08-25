"""llm.py — local Ollama chat + embedding factory.

One place to construct models so every agent shares the same daemon/host config
and we never accidentally reach for a cloud provider. Chat goes through
``langchain_ollama.ChatOllama`` (the modern API; ``langchain_community`` is
deprecated). Embeddings go through the raw ``ollama`` client so semantic memory
keeps working even if LangChain's embedding wrapper drifts.
"""
from __future__ import annotations

import os
import sys

# Default coding/instruct model: qwen2.5-coder:32b is the sweet spot on a 32GB
# 5090. Override per-process with OPENCLAW_AGENT_MODEL, or per-agent in agents.py.
DEFAULT_MODEL = os.environ.get("OPENCLAW_AGENT_MODEL", "qwen2.5-coder:32b")
EMBED_MODEL = os.environ.get("OPENCLAW_EMBED_MODEL", "nomic-embed-text")
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")


def get_llm(model: str | None = None, temperature: float = 0.0):
    """Return a ChatOllama bound to the local daemon. `model` defaults to
    DEFAULT_MODEL; raise a helpful error if langchain-ollama isn't installed."""
    try:
        from langchain_ollama import ChatOllama
    except ImportError as e:  # pragma: no cover - install guidance
        sys.exit(
            f"Missing dependency: {e}\n"
            "Install with:  pip install -r requirements.txt\n"
            "(Use langchain_ollama.ChatOllama — NOT the deprecated "
            "langchain_community.llms.Ollama.)"
        )
    return ChatOllama(model=model or DEFAULT_MODEL, base_url=OLLAMA_HOST,
                      temperature=temperature)


def embed(texts: list[str]) -> list[list[float]] | None:
    """Embed `texts` with the local embedding model. Returns one vector per
    input, or None if embeddings are unavailable (daemon down, model not pulled)
    — callers degrade to keyword search rather than crashing."""
    if not texts:
        return []
    try:
        import ollama

        client = ollama.Client(host=OLLAMA_HOST)
        # ollama.embed accepts a list and returns {"embeddings": [[...], ...]}.
        resp = client.embed(model=EMBED_MODEL, input=texts)
        vecs = resp.get("embeddings")
        if vecs and len(vecs) == len(texts):
            return [list(map(float, v)) for v in vecs]
    except Exception:
        # Embeddings are best-effort; semantic memory falls back to keywords.
        return None
    return None
