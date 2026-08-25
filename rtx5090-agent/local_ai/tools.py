"""tools.py — sandboxed tools the local agents can call.

Same safety posture as agent_engine.py: everything stays inside a workspace
directory, executions are gated behind a confirmation prompt unless
AGENT_AUTO_APPROVE=1, and subprocesses run with a timeout and no shell.

Tools come in two groups:
  * stateless     — file read/write, run python, web fetch, gpu telemetry.
  * memory-bound  — remember / recall, built per-agent via memory_tools().
"""
from __future__ import annotations

import os
import subprocess
import sys
import urllib.request
from pathlib import Path

from langchain_core.tools import tool
from rich.console import Console
from rich.panel import Panel

from .memory import Memory

console = Console()

WORKDIR = Path(os.environ.get("AGENT_WORKDIR", "agent_workspace")).resolve()
AUTO_APPROVE = os.environ.get("AGENT_AUTO_APPROVE") == "1"
EXEC_TIMEOUT = int(os.environ.get("AGENT_EXEC_TIMEOUT", "120"))
WORKDIR.mkdir(parents=True, exist_ok=True)


# --- safety helpers (shared with agent_engine.py's posture) ---------------
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


# --- stateless tools ------------------------------------------------------
@tool
def write_file(filename: str, content: str) -> str:
    """Write `content` to `filename` inside the workspace (no execution).
    Use this to save drafts, reports, configs, or notes."""
    path = _safe_path(filename)
    path.write_text(content, encoding="utf-8")
    return f"Wrote {len(content)} chars to {path.relative_to(WORKDIR)}"


@tool
def read_file(filename: str) -> str:
    """Read and return the contents of `filename` from the workspace."""
    path = _safe_path(filename)
    if not path.exists():
        return f"ERROR: {filename} does not exist in the workspace."
    return path.read_text(encoding="utf-8")


@tool
def list_workspace() -> str:
    """List files currently in the workspace."""
    files = sorted(p.relative_to(WORKDIR).as_posix()
                   for p in WORKDIR.rglob("*") if p.is_file())
    return "\n".join(files) if files else "(workspace is empty)"


@tool
def run_python(filename: str, code: str) -> str:
    """Write Python `code` to `filename` in the workspace and run it with the
    current interpreter. Returns exit code, stdout and stderr so you can debug.
    Gated by a confirmation prompt."""
    path = _safe_path(filename)
    path.write_text(code, encoding="utf-8")
    if not _confirm(f"python {path.name}\n\n{code}"):
        return "User declined execution."
    return _run([sys.executable, str(path)], cwd=WORKDIR)


@tool
def web_fetch(url: str) -> str:
    """Fetch a URL and return up to ~8000 chars of text. Subject to this box's
    network policy — if outbound access is blocked this returns an error, which
    is expected on an offline host. Use for research when the network is open."""
    if not url.startswith(("http://", "https://")):
        return "ERROR: only http(s) URLs are allowed."
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "local-ai/1.0"})
        with urllib.request.urlopen(req, timeout=20) as resp:  # noqa: S310 - http(s) only
            raw = resp.read(2_000_000)
        text = raw.decode("utf-8", errors="replace")
        return text[:8000]
    except Exception as e:  # network blocked, DNS, timeout, etc.
        return f"ERROR fetching {url}: {e}"


@tool
def gpu_telemetry() -> str:
    """Return live RTX 5090 telemetry from nvidia-smi (util %, memory, temp).
    Call before/after a change to ground performance claims in real numbers."""
    query = ("utilization.gpu,utilization.memory,memory.used,memory.total,"
             "temperature.gpu")
    try:
        r = subprocess.run(
            ["nvidia-smi", f"--query-gpu={query}", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=15, check=False,
        )
    except FileNotFoundError:
        return "ERROR: nvidia-smi not found (no driver visible)."
    if r.returncode != 0:
        return f"ERROR: nvidia-smi exit {r.returncode}: {r.stderr.strip()}"
    cols = ["gpu_util_%", "mem_util_%", "mem_used_MiB", "mem_total_MiB", "temp_C"]
    vals = [v.strip() for v in r.stdout.strip().split(",")]
    return "\n".join(f"  {k}: {v}" for k, v in zip(cols, vals))


# --- memory-bound tools ---------------------------------------------------
def memory_tools(memory: Memory, agent_name: str) -> list:
    """Build `remember`/`recall` tools bound to a shared Memory and tagged with
    the calling agent's name. Returned as fresh @tool callables per agent."""

    @tool
    def remember(text: str) -> str:
        """Save a durable fact or note to long-term memory for later recall."""
        memory.remember(agent_name, text)
        return "Saved to memory."

    @tool
    def recall(query: str) -> str:
        """Search long-term memory for notes relevant to `query`."""
        hits = memory.recall(query, k=5)
        if not hits:
            return "(no relevant memories)"
        return "\n".join(f"- ({h['agent']}) {h['text']}" for h in hits)

    return [remember, recall]
