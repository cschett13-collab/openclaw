#!/usr/bin/env python3
"""
agent_engine.py — A local LLM coding agent for an RTX 5090 (Blackwell) box.

What it actually does (vs. the common stub that just prints a string):
  * Talks to a LOCAL Ollama model (default: qwen2.5-coder:32b) — no cloud, no API key.
  * Has two REAL tools the model can call:
        - write_and_run_python : writes a .py file and executes it
        - write_compile_run_cuda : writes a .cu file, compiles with nvcc, runs it
  * Captures stdout/stderr/exit code and feeds them back so the model can debug.

Safety (read this before you disable anything):
  * Everything happens inside WORKDIR (default ./agent_workspace). Paths are
    sandboxed — the model cannot write outside it.
  * Every execution is gated behind a confirmation prompt unless you set
    AGENT_AUTO_APPROVE=1. Auto-approve means the model runs code on your machine
    with no human in the loop — only do that in a throwaway/VM environment.
  * Commands run with a timeout and without a shell (no shell-injection surface).
  * This is a powerful local tool, not a sandbox/jail. Don't point it at a
    machine with secrets you can't afford an LLM to read.

Modern LangChain API: uses langchain_ollama.ChatOllama + langchain.agents.
create_agent. (The old langchain_community.llms.Ollama + initialize_agent are
deprecated and removed in current releases.)

Usage:
    python agent_engine.py "Write a CUDA kernel that adds two 1M-element vectors and verifies the result."
    # or interactive:
    python agent_engine.py
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from rich.console import Console
from rich.panel import Panel

# --- modern LangChain imports (post-deprecation) --------------------------
try:
    from langchain_ollama import ChatOllama
    from langchain.agents import create_agent
    from langchain_core.tools import tool
except ImportError as e:  # pragma: no cover - guidance for fresh installs
    sys.exit(
        f"Missing dependency: {e}\n"
        "Install with:  pip install -r requirements.txt\n"
        "(Do NOT use langchain_community.llms.Ollama / initialize_agent — deprecated.)"
    )

console = Console()

# --- config ---------------------------------------------------------------
MODEL = os.environ.get("OPENCLAW_AGENT_MODEL", "qwen2.5-coder:32b")
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
WORKDIR = Path(os.environ.get("AGENT_WORKDIR", "agent_workspace")).resolve()
AUTO_APPROVE = os.environ.get("AGENT_AUTO_APPROVE") == "1"
EXEC_TIMEOUT = int(os.environ.get("AGENT_EXEC_TIMEOUT", "120"))  # seconds

WORKDIR.mkdir(parents=True, exist_ok=True)


# --- safety helpers -------------------------------------------------------
def _safe_path(filename: str) -> Path:
    """Resolve `filename` strictly inside WORKDIR; reject traversal."""
    p = (WORKDIR / filename).resolve()
    if not str(p).startswith(str(WORKDIR) + os.sep) and p != WORKDIR:
        raise ValueError(f"Refusing path outside workspace: {filename}")
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _confirm(action: str) -> bool:
    if AUTO_APPROVE:
        console.print(f"[dim](auto-approved) {action}[/dim]")
        return True
    console.print(Panel(action, title="Approve execution?", border_style="yellow"))
    return input("Run this? [y/N] ").strip().lower() in {"y", "yes"}


def _run(cmd: list[str], cwd: Path) -> str:
    """Run a command (no shell), capture everything, never raise on bad exit."""
    try:
        r = subprocess.run(
            cmd, cwd=cwd, capture_output=True, text=True,
            timeout=EXEC_TIMEOUT, check=False,
        )
    except FileNotFoundError:
        return f"ERROR: '{cmd[0]}' not found on PATH."
    except subprocess.TimeoutExpired:
        return f"ERROR: command timed out after {EXEC_TIMEOUT}s: {' '.join(cmd)}"
    out = (r.stdout or "").strip()
    err = (r.stderr or "").strip()
    return f"exit_code={r.returncode}\n--- stdout ---\n{out}\n--- stderr ---\n{err}"


# --- tools the model can call --------------------------------------------
@tool
def write_and_run_python(filename: str, code: str) -> str:
    """Write Python `code` to `filename` inside the workspace, then run it with
    the current interpreter. Returns exit code, stdout and stderr. Use this to
    test PyTorch/CUDA-via-torch logic on the local RTX 5090."""
    path = _safe_path(filename)
    path.write_text(code, encoding="utf-8")
    if not _confirm(f"python {path.name}\n\n{code}"):
        return "User declined execution."
    return _run([sys.executable, str(path)], cwd=WORKDIR)


@tool
def write_compile_run_cuda(filename: str, code: str, arch: str = "sm_120") -> str:
    """Write CUDA C++ `code` to `filename` (e.g. 'vecadd.cu') in the workspace,
    compile it with nvcc targeting `arch` (default sm_120 for Blackwell/RTX 5090),
    then run the resulting binary. Returns compile + run output."""
    src = _safe_path(filename)
    src.write_text(code, encoding="utf-8")
    binary = src.with_suffix("")
    nvcc = [
        "nvcc", "-O2", f"-arch={arch}",
        str(src), "-o", str(binary),
    ]
    if not _confirm(f"{' '.join(nvcc)}\n# then run ./{binary.name}\n\n{code}"):
        return "User declined execution."
    compile_out = _run(nvcc, cwd=WORKDIR)
    if "exit_code=0" not in compile_out.splitlines()[0]:
        return f"COMPILE FAILED:\n{compile_out}"
    run_out = _run([str(binary)], cwd=WORKDIR)
    return f"COMPILE OK\n{compile_out}\n\n=== RUN ===\n{run_out}"


@tool
def gpu_telemetry() -> str:
    """Return live RTX 5090 telemetry from nvidia-smi: GPU utilization %,
    memory used/total (MiB), and encoder/decoder utilization %. Call this
    BEFORE and AFTER a change to ground any performance claim in real numbers
    rather than guessing."""
    query = ("utilization.gpu,utilization.memory,memory.used,memory.total,"
             "utilization.encoder,utilization.decoder,temperature.gpu")
    try:
        r = subprocess.run(
            ["nvidia-smi", f"--query-gpu={query}", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=15, check=False,
        )
    except FileNotFoundError:
        return "ERROR: nvidia-smi not found (no driver visible)."
    except subprocess.TimeoutExpired:
        return "ERROR: nvidia-smi timed out."
    if r.returncode != 0:
        return f"ERROR: nvidia-smi exit {r.returncode}: {r.stderr.strip()}"
    cols = ["gpu_util_%", "mem_util_%", "mem_used_MiB", "mem_total_MiB",
            "enc_util_%", "dec_util_%", "temp_C"]
    vals = [v.strip() for v in r.stdout.strip().split(",")]
    return "\n".join(f"  {k}: {v}" for k, v in zip(cols, vals))


TOOLS = [write_and_run_python, write_compile_run_cuda, gpu_telemetry]

SYSTEM_PROMPT = (
    "You are a CUDA and Python engineer working on a machine with an NVIDIA "
    "RTX 5090 (Blackwell, compute capability sm_120, 32GB GDDR7). "
    "When asked to build something, WRITE the code and USE your tools to run or "
    "compile it, then read the tool output and FIX errors iteratively until it "
    "works. For CUDA, target sm_120. Keep files inside the workspace. "
    "PERFORMANCE RULES: never claim something is 'faster' or 'optimized' from "
    "intuition. Measure it. Call gpu_telemetry before and after a change, and "
    "include explicit timings (e.g. time a kernel over N iterations) in the code "
    "you run. Report optimization results ONLY with before/after numbers from "
    "tool output; if you have no measurement, say so. "
    "Report the final working result and where the file lives."
)


def build_agent():
    llm = ChatOllama(model=MODEL, base_url=OLLAMA_HOST, temperature=0)
    # create_agent is the current factory (replaces deprecated initialize_agent).
    return create_agent(llm, TOOLS, prompt=SYSTEM_PROMPT)


def main() -> None:
    console.print(Panel.fit(
        f"[bold]RTX 5090 local coding agent[/bold]\n"
        f"model      : {MODEL}\n"
        f"ollama     : {OLLAMA_HOST}\n"
        f"workspace  : {WORKDIR}\n"
        f"auto-approve: {'ON (DANGER)' if AUTO_APPROVE else 'off (you confirm each run)'}",
        border_style="green",
    ))
    agent = build_agent()

    def ask(task: str) -> None:
        result = agent.invoke({"messages": [{"role": "user", "content": task}]})
        final = result["messages"][-1].content
        console.print(Panel(final, title="Agent", border_style="cyan"))

    if len(sys.argv) > 1:
        ask(" ".join(sys.argv[1:]))
        return
    console.print("Interactive mode. Type a task, or 'exit'.")
    while True:
        try:
            task = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if task.lower() in {"exit", "quit"}:
            break
        if task:
            ask(task)


if __name__ == "__main__":
    main()
