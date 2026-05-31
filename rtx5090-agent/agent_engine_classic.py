#!/usr/bin/env python3
"""
agent_engine_classic.py — Same local RTX 5090 coding agent as agent_engine.py,
but built with the CLASSIC LangChain lane: create_tool_calling_agent + AgentExecutor.

Two valid ways to build a tool-calling agent in current LangChain:

  * MODERN  (agent_engine.py): `create_agent(llm, tools, prompt=<system str>)`
            returns a ready graph; invoke with {"messages": [...]}; no AgentExecutor.

  * CLASSIC (this file):       `create_tool_calling_agent(llm, tools, prompt)` +
            `AgentExecutor(...)`; prompt is a ChatPromptTemplate with {input}
            and a MessagesPlaceholder("agent_scratchpad"); invoke with {"input": ...}.

Do NOT cross them: `create_agent(..., "openai-tools")` then wrapping in
AgentExecutor fails — `create_agent` takes no "agent type" arg and already
returns the runnable. This file is the consistent CLASSIC version.

It keeps the same safety posture as agent_engine.py: workspace path
containment, a confirmation gate (AGENT_AUTO_APPROVE=1 to bypass), no shell,
and a per-command timeout.

Usage:
    python agent_engine_classic.py "Verify GPU and PyNvVideoCodec status"
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

try:
    from langchain_ollama import ChatOllama
    from langchain.agents import create_tool_calling_agent, AgentExecutor
    from langchain.prompts import ChatPromptTemplate, MessagesPlaceholder
    from langchain_core.tools import tool
except ImportError as e:  # pragma: no cover - install guidance
    sys.exit(
        f"Missing dependency: {e}\n"
        "Install with:  pip install -r requirements.txt"
    )

# --- config (shared conventions with agent_engine.py) --------------------
MODEL = os.environ.get("OPENCLAW_AGENT_MODEL", "qwen2.5-coder:32b")
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
WORKDIR = Path(os.environ.get("AGENT_WORKDIR", "agent_workspace")).resolve()
AUTO_APPROVE = os.environ.get("AGENT_AUTO_APPROVE") == "1"
EXEC_TIMEOUT = int(os.environ.get("AGENT_EXEC_TIMEOUT", "120"))

WORKDIR.mkdir(parents=True, exist_ok=True)


def _safe_path(filename: str) -> Path:
    """Resolve `filename` strictly inside WORKDIR; reject traversal."""
    p = (WORKDIR / filename).resolve()
    if not str(p).startswith(str(WORKDIR) + os.sep) and p != WORKDIR:
        raise ValueError(f"Refusing path outside workspace: {filename}")
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _confirm(action: str) -> bool:
    if AUTO_APPROVE:
        print(f"(auto-approved) {action}")
        return True
    print(f"\n--- Approve execution? ---\n{action}\n--------------------------")
    return input("Run this? [y/N] ").strip().lower() in {"y", "yes"}


@tool
def execute_code(code: str) -> str:
    """Write Python `code` to the workspace and execute it with the current
    interpreter. Returns exit code, stdout and stderr so failures can be fixed
    and retried. Use for PyTorch/CUDA-via-torch and PyNvVideoCodec tasks."""
    path = _safe_path("task.py")
    path.write_text(code, encoding="utf-8")
    if not _confirm(f"python3 {path}\n\n{code}"):
        return "User declined execution."
    try:
        res = subprocess.run(
            [sys.executable, str(path)], cwd=WORKDIR,
            capture_output=True, text=True, timeout=EXEC_TIMEOUT, check=False,
        )
    except subprocess.TimeoutExpired:
        return f"FAILED: timed out after {EXEC_TIMEOUT}s."
    except FileNotFoundError:
        return "FAILED: python interpreter not found."
    if res.returncode != 0:
        return f"FAILED (Exit {res.returncode}):\n{(res.stderr or '').strip()}"
    return f"SUCCESS:\n{(res.stdout or '').strip()}"


def build_executor() -> AgentExecutor:
    llm = ChatOllama(model=MODEL, base_url=OLLAMA_HOST, temperature=0)
    tools = [execute_code]
    prompt = ChatPromptTemplate.from_messages([
        ("system",
         "You are an autonomous engineer on a machine with an NVIDIA RTX 5090 "
         "(Blackwell, sm_120, 32GB). Use execute_code to run code. For "
         "high-volume video use PyNvVideoCodec for NVDEC/NVENC. If code fails, "
         "do root-cause analysis on the error, fix the source, and re-run."),
        ("human", "{input}"),
        MessagesPlaceholder(variable_name="agent_scratchpad"),
    ])
    agent = create_tool_calling_agent(llm, tools, prompt)
    # handle_parsing_errors: local models occasionally emit a malformed tool
    # call; this keeps one bad turn from crashing the whole loop.
    return AgentExecutor(agent=agent, tools=tools, verbose=True,
                         handle_parsing_errors=True)


def main() -> None:
    print(f"[classic agent] model={MODEL} workspace={WORKDIR} "
          f"auto_approve={'ON (DANGER)' if AUTO_APPROVE else 'off'}")
    executor = build_executor()
    task = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "Verify GPU and PyNvVideoCodec status"
    executor.invoke({"input": task})


if __name__ == "__main__":
    main()
