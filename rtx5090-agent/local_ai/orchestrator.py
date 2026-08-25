"""orchestrator.py — route tasks to the right agent, or run a pipeline.

This is the "Orchestration" box from GOALS.md: routing, sequencing, memory
hand-off, and error handling, all local. Two entry points:

  * run(task, agent=None) — pick an agent (keyword router, LLM tie-break) and
    run one task. Logs to episodic memory; injects relevant semantic memory.
  * pipeline(steps)       — run an ordered list of (agent, task) steps, passing
    each step's output forward as context to the next.

Agents are built lazily and cached, so a long-running session pays the model
warm-up cost once per agent.
"""
from __future__ import annotations

from rich.console import Console
from rich.panel import Panel

from .agents import TEAM, AgentSpec, build_agent
from .llm import get_llm
from .memory import Memory

console = Console()


class Orchestrator:
    def __init__(self, memory: Memory | None = None) -> None:
        self.memory = memory or Memory()
        self._agents: dict[str, object] = {}  # name -> runnable, built lazily

    # --- agent lifecycle ----------------------------------------------------
    def _agent(self, name: str):
        if name not in self._agents:
            self._agents[name] = build_agent(TEAM[name], self.memory)
        return self._agents[name]

    # --- routing ------------------------------------------------------------
    def route(self, task: str) -> str:
        """Choose the best agent for `task`. Keyword scoring first (cheap,
        deterministic); fall back to a one-shot LLM classification only on a
        tie or miss."""
        t = task.lower()
        scores: dict[str, int] = {}
        for name, spec in TEAM.items():
            scores[name] = sum(1 for kw in spec.keywords if kw in t)
        best = max(scores.values())
        if best > 0:
            winners = [n for n, s in scores.items() if s == best]
            if len(winners) == 1:
                return winners[0]
            return self._llm_route(task, winners)
        return self._llm_route(task, list(TEAM))

    def _llm_route(self, task: str, candidates: list[str]) -> str:
        """Ask the local model to pick one agent name from `candidates`."""
        roster = "\n".join(f"- {n}: {TEAM[n].role}" for n in candidates)
        prompt = (
            "Pick the single best agent for this task. Reply with ONLY the agent "
            f"name, nothing else.\n\nAgents:\n{roster}\n\nTask: {task}\nAgent:"
        )
        try:
            reply = get_llm(temperature=0).invoke(prompt)
            text = getattr(reply, "content", str(reply)).strip().lower()
            for name in candidates:
                if name in text:
                    return name
        except Exception:
            pass
        return candidates[0]  # deterministic fallback

    # --- execution ----------------------------------------------------------
    def run(self, task: str, agent: str | None = None, context: str = "") -> str:
        """Run one task. If `agent` is None, route it. Returns the agent's final
        text. Errors are caught and returned (and logged) rather than raised, so
        a pipeline can decide whether to continue."""
        name = agent or self.route(task)
        if name not in TEAM:
            return f"ERROR: unknown agent '{name}'. Known: {', '.join(TEAM)}"

        mem_block = self.memory.context_block(task)
        parts = [p for p in (mem_block, context) if p]
        user_msg = ("\n\n".join(parts) + "\n\n" + task) if parts else task

        console.print(Panel.fit(f"[bold]{name}[/bold] — {TEAM[name].role}",
                                border_style="magenta"))
        self.memory.log_event(name, "task_started", task)
        try:
            result = self._agent(name).invoke(
                {"messages": [{"role": "user", "content": user_msg}]}
            )
            final = result["messages"][-1].content
        except Exception as e:  # model/daemon/tool failure
            self.memory.log_event(name, "task_failed", f"{task} :: {e}")
            return f"ERROR running '{name}': {e}"

        self.memory.log_event(name, "task_done", final[:500])
        console.print(Panel(final, title=name, border_style="cyan"))
        return final

    def pipeline(self, steps: list[tuple[str, str]]) -> list[str]:
        """Run ordered (agent, task) steps, feeding each output to the next as
        context. Returns each step's output. A failed step is recorded and its
        error string is passed forward so later steps can react."""
        outputs: list[str] = []
        context = ""
        for agent, task in steps:
            out = self.run(task, agent=agent, context=context)
            outputs.append(out)
            context = f"Previous step ({agent}) output:\n{out}"
        return outputs
