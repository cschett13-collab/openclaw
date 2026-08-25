#!/usr/bin/env python3
"""team.py — CLI for the local AI Team.

Drive the six-agent team from GOALS.md against a local Ollama daemon — no cloud,
no API keys. Memory persists across runs in a local SQLite file.

Usage:
    python team.py list                       # show the team
    python team.py route "summarize trends"   # auto-pick an agent
    python team.py research "find X"          # run a named agent directly
    python team.py chat                        # interactive, persistent memory
    python team.py pipeline                    # demo research -> content pipeline

Safety: agents that run code (analytics, automation) confirm each execution
unless AGENT_AUTO_APPROVE=1. See README.md before disabling that.
"""
from __future__ import annotations

import sys

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from local_ai import TEAM
from local_ai.orchestrator import Orchestrator

console = Console()


def cmd_list() -> None:
    table = Table(title="Local AI Team", border_style="green")
    table.add_column("agent", style="bold")
    table.add_column("role")
    table.add_column("tools")
    for name, spec in TEAM.items():
        tools = ", ".join(spec.tools) + ", remember, recall"
        table.add_row(name, spec.role, tools)
    console.print(table)


def cmd_route(orch: Orchestrator, task: str) -> None:
    picked = orch.route(task)
    console.print(f"[dim]routed to[/dim] [bold]{picked}[/bold]")
    orch.run(task, agent=picked)


def cmd_chat(orch: Orchestrator) -> None:
    console.print(Panel.fit(
        "Interactive team chat. Each line is routed to the best agent.\n"
        "Prefix with 'agent:' to force one (e.g. 'content: write a haiku').\n"
        "Type 'exit' to quit.", border_style="green"))
    while True:
        try:
            line = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if line.lower() in {"exit", "quit"}:
            break
        if not line:
            continue
        if ":" in line and line.split(":", 1)[0].strip() in TEAM:
            agent, task = line.split(":", 1)
            orch.run(task.strip(), agent=agent.strip())
        else:
            orch.run(line)


def cmd_pipeline(orch: Orchestrator) -> None:
    """Demo a two-step pipeline: research a topic, then write a post about it."""
    topic = "the practical benefits of running AI models locally"
    orch.pipeline([
        ("research", f"Research {topic}. Save findings to research.md."),
        ("content", "Using the previous research, write a short blog post and "
                    "save it to post.md."),
    ])


def main() -> None:
    if len(sys.argv) < 2:
        console.print(__doc__)
        return
    cmd = sys.argv[1].lower()

    if cmd == "list":
        cmd_list()
        return

    orch = Orchestrator()
    if cmd == "chat":
        cmd_chat(orch)
    elif cmd == "pipeline":
        cmd_pipeline(orch)
    elif cmd == "route":
        if len(sys.argv) < 3:
            console.print("Usage: python team.py route \"<task>\"")
            return
        cmd_route(orch, " ".join(sys.argv[2:]))
    elif cmd in TEAM:
        if len(sys.argv) < 3:
            console.print(f"Usage: python team.py {cmd} \"<task>\"")
            return
        orch.run(" ".join(sys.argv[2:]), agent=cmd)
    else:
        console.print(f"Unknown command '{cmd}'. Try: list, route, chat, "
                      f"pipeline, or an agent name ({', '.join(TEAM)}).")


if __name__ == "__main__":
    main()
