"""local_ai — a fully local multi-agent system for the RTX 5090 box.

No cloud, no API keys: every agent runs against a local Ollama daemon. This
package turns the single coding agent in ``agent_engine.py`` into the six-agent
"AI Team" from ``GOALS.md`` (Research, Content, Analytics, Outreach,
Automation, Support), plus the supporting systems they need:

  * llm.py          — local Ollama chat + embedding factory
  * memory.py       — SQLite-backed episodic + semantic memory (local)
  * tools.py        — sandboxed file / python / web / memory tools
  * agents.py       — the team: purpose, prompt, tools and model per agent
  * orchestrator.py — route a task to the right agent, or run a pipeline

Honest scope: these are capable local assistants with real tools and memory,
gated by human confirmation on anything that executes code. They are not an
autonomous lab. Quality tracks the local model you run (a 32B coder/instruct
model is the sweet spot on 32GB).
"""

__all__ = ["TEAM", "AgentSpec", "build_agent", "Memory", "Orchestrator"]

# Lazy exports (PEP 562): importing the package shouldn't force LangChain to be
# present just to use the stdlib-only Memory layer. Submodules pull their own
# heavier deps on first access.
_LAZY = {
    "TEAM": ("agents", "TEAM"),
    "AgentSpec": ("agents", "AgentSpec"),
    "build_agent": ("agents", "build_agent"),
    "Memory": ("memory", "Memory"),
    "Orchestrator": ("orchestrator", "Orchestrator"),
}


def __getattr__(name: str):
    import importlib

    if name in _LAZY:
        module, attr = _LAZY[name]
        return getattr(importlib.import_module(f".{module}", __name__), attr)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
