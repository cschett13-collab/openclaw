"""memory.py — local, file-backed memory for the agent team.

Two of the five memory types from GOALS.md, kept deliberately simple and
dependency-light (stdlib ``sqlite3`` only):

  * episodic  — an append-only log of what happened (who did what, when).
  * semantic  — facts/notes you can recall by meaning, via local embeddings.

If the embedding model is unavailable, semantic recall degrades to a keyword
LIKE search instead of failing. Everything lives in one SQLite file so memory
survives across runs and across agents on the same box — no cloud, no server.
"""
from __future__ import annotations

import json
import math
import os
import sqlite3
import time
from pathlib import Path

from .llm import embed

DEFAULT_DB = Path(os.environ.get("LOCAL_AI_MEMORY", "agent_memory.sqlite")).resolve()


def _cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity without numpy (numpy isn't guaranteed on a CPU box)."""
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


class Memory:
    """Shared episodic + semantic store. One instance per process is fine; the
    SQLite file is the source of truth, so multiple processes can share it."""

    def __init__(self, db_path: Path | str = DEFAULT_DB) -> None:
        self.db_path = Path(db_path).resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS episodic (
                id     INTEGER PRIMARY KEY AUTOINCREMENT,
                ts     REAL NOT NULL,
                agent  TEXT NOT NULL,
                event  TEXT NOT NULL,
                detail TEXT
            );
            CREATE TABLE IF NOT EXISTS semantic (
                id     INTEGER PRIMARY KEY AUTOINCREMENT,
                ts     REAL NOT NULL,
                agent  TEXT NOT NULL,
                text   TEXT NOT NULL,
                vec    TEXT          -- JSON float array, or NULL if no embedding
            );
            """
        )
        self._conn.commit()

    # --- episodic -----------------------------------------------------------
    def log_event(self, agent: str, event: str, detail: str = "") -> None:
        """Record that something happened. Cheap; call it liberally."""
        self._conn.execute(
            "INSERT INTO episodic (ts, agent, event, detail) VALUES (?,?,?,?)",
            (time.time(), agent, event, detail),
        )
        self._conn.commit()

    def recent(self, n: int = 10, agent: str | None = None) -> list[dict]:
        """Most recent episodic events, newest first."""
        if agent:
            rows = self._conn.execute(
                "SELECT * FROM episodic WHERE agent=? ORDER BY id DESC LIMIT ?",
                (agent, n),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM episodic ORDER BY id DESC LIMIT ?", (n,)
            ).fetchall()
        return [dict(r) for r in rows]

    # --- semantic -----------------------------------------------------------
    def remember(self, agent: str, text: str) -> None:
        """Store a fact/note for later recall-by-meaning. Embeds locally if the
        embedding model is available; stores text-only otherwise."""
        vecs = embed([text])
        vec_json = json.dumps(vecs[0]) if vecs else None
        self._conn.execute(
            "INSERT INTO semantic (ts, agent, text, vec) VALUES (?,?,?,?)",
            (time.time(), agent, text, vec_json),
        )
        self._conn.commit()

    def recall(self, query: str, k: int = 5) -> list[dict]:
        """Return up to `k` semantic memories most relevant to `query`.

        Uses cosine over local embeddings when both the query and stored rows
        have vectors; otherwise falls back to a keyword LIKE match so recall
        never hard-fails just because the embedding model isn't loaded.
        """
        rows = [dict(r) for r in self._conn.execute("SELECT * FROM semantic").fetchall()]
        if not rows:
            return []

        qvec = embed([query])
        qvec = qvec[0] if qvec else None
        scored: list[tuple[float, dict]] = []
        if qvec is not None:
            for r in rows:
                if r["vec"]:
                    score = _cosine(qvec, json.loads(r["vec"]))
                    scored.append((score, r))
        if scored:
            scored.sort(key=lambda t: t[0], reverse=True)
            return [{**r, "score": round(s, 4)} for s, r in scored[:k]]

        # Fallback: keyword search.
        q = query.lower()
        hits = [r for r in rows if any(w in r["text"].lower() for w in q.split())]
        return hits[-k:][::-1]

    def context_block(self, query: str, k: int = 4) -> str:
        """Render recalled memories as a prompt-injectable text block (empty
        string when there's nothing relevant)."""
        hits = self.recall(query, k)
        if not hits:
            return ""
        lines = [f"- ({h['agent']}) {h['text']}" for h in hits]
        return "Relevant memory:\n" + "\n".join(lines)

    def close(self) -> None:
        self._conn.close()
