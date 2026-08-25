"""agents.py — the local AI Team from GOALS.md.

Six purpose-scoped agents, each defined declaratively as an ``AgentSpec``
(role, system prompt, tool subset, model, temperature) and built on the modern
``langchain.agents.create_agent`` factory. Every agent gets the shared local
memory (remember/recall) on top of its own tools.

Keep specs declarative so adding a seventh agent is a dict entry, not new
plumbing.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .memory import Memory


def _tool_registry() -> dict:
    """Map tool names to tool objects. Imported lazily so the TEAM specs (pure
    data) and the keyword router load without LangChain installed."""
    from .tools import (
        gpu_telemetry,
        list_workspace,
        read_file,
        run_python,
        web_fetch,
        write_file,
    )

    return {
        "write_file": write_file,
        "read_file": read_file,
        "list_workspace": list_workspace,
        "run_python": run_python,
        "web_fetch": web_fetch,
        "gpu_telemetry": gpu_telemetry,
    }


@dataclass(frozen=True)
class AgentSpec:
    name: str
    role: str                       # one-line job description
    system_prompt: str
    tools: tuple[str, ...] = ()     # names into _TOOLS; memory tools added automatically
    model: str | None = None        # None -> DEFAULT_MODEL
    temperature: float = 0.0
    keywords: tuple[str, ...] = field(default_factory=tuple)  # for routing


def build_agent(spec: AgentSpec, memory: Memory):
    """Construct a runnable agent for `spec`, wiring its tools + shared memory."""
    from .llm import get_llm
    from .tools import memory_tools

    registry = _tool_registry()
    tools = [registry[name] for name in spec.tools]
    tools += memory_tools(memory, spec.name)
    llm = get_llm(model=spec.model, temperature=spec.temperature)
    return create_agent_runnable(llm, tools, spec.system_prompt)


def create_agent_runnable(llm, tools, system_prompt: str):
    """Thin wrapper over langchain.agents.create_agent (kept here so the import
    stays in one place and the rest of the package doesn't depend on LangChain)."""
    from langchain.agents import create_agent

    return create_agent(llm, tools, prompt=system_prompt)


# --- the team -------------------------------------------------------------
_COMMON = (
    "You run fully locally on an RTX 5090 box — no cloud, no API keys. "
    "Use your tools to do real work, not just describe it. Before relying on a "
    "fact you were told earlier, call `recall`. After producing something "
    "durable (a finding, a draft, a decision), call `remember` so the rest of "
    "the team can reuse it. Save deliverables to files with `write_file`. "
)

TEAM: dict[str, AgentSpec] = {
    "research": AgentSpec(
        name="research",
        role="Finds and collects information",
        system_prompt=_COMMON + (
            "You are the RESEARCH agent. Given a topic, gather and synthesize "
            "information. Use `web_fetch` when the network is open; if it's "
            "blocked, say so and work from provided material or memory. Produce "
            "a concise, sourced summary and save it to a file."
        ),
        tools=("web_fetch", "write_file", "read_file", "list_workspace"),
        keywords=("research", "find", "investigate", "gather", "look up", "sources"),
    ),
    "content": AgentSpec(
        name="content",
        role="Writes, edits, and creates content",
        system_prompt=_COMMON + (
            "You are the CONTENT agent. Turn briefs and research into clear "
            "writing — posts, docs, scripts. Draft, then self-edit for clarity "
            "and accuracy. Save each piece to a file and note the format."
        ),
        tools=("write_file", "read_file", "list_workspace"),
        keywords=("write", "draft", "post", "article", "edit", "content", "copy"),
    ),
    "analytics": AgentSpec(
        name="analytics",
        role="Analyzes data and finds insights",
        system_prompt=_COMMON + (
            "You are the ANALYTICS agent. Load data from the workspace, write "
            "and RUN Python (pandas/stdlib) to analyze it with `run_python`, and "
            "report only conclusions backed by the actual output you saw. Never "
            "invent numbers; if you didn't compute it, say so. Save a report."
        ),
        tools=("run_python", "read_file", "write_file", "list_workspace"),
        keywords=("analyze", "data", "metrics", "insight", "report", "stats", "csv"),
    ),
    "outreach": AgentSpec(
        name="outreach",
        role="Builds relationships and handles outreach",
        system_prompt=_COMMON + (
            "You are the OUTREACH agent. Draft personalized, honest outreach "
            "(emails, replies, follow-ups) from context and memory. You DRAFT "
            "only — a human sends. Never fabricate relationships or commitments. "
            "Save drafts to files for review."
        ),
        tools=("write_file", "read_file", "list_workspace"),
        temperature=0.3,
        keywords=("outreach", "email", "reply", "follow up", "message", "dm", "contact"),
    ),
    "automation": AgentSpec(
        name="automation",
        role="Builds and optimizes workflows",
        system_prompt=_COMMON + (
            "You are the AUTOMATION agent. Design and build local workflows: "
            "write Python scripts that wire steps together, test them with "
            "`run_python`, and check GPU load with `gpu_telemetry` when relevant. "
            "Prefer simple, debuggable scripts with clear triggers and error "
            "handling. Save the workflow and document how to run it."
        ),
        tools=("run_python", "write_file", "read_file", "list_workspace", "gpu_telemetry"),
        keywords=("automate", "workflow", "pipeline", "script", "trigger", "schedule"),
    ),
    "support": AgentSpec(
        name="support",
        role="Answers questions and solves problems",
        system_prompt=_COMMON + (
            "You are the SUPPORT agent. Answer questions using files in the "
            "workspace and long-term memory first (`recall`, `read_file`). If you "
            "don't know, say so plainly and suggest who/what could. Be concise "
            "and accurate over confident."
        ),
        tools=("read_file", "list_workspace", "web_fetch"),
        keywords=("help", "how do i", "explain", "question", "support", "fix", "why"),
    ),
}
