# RTX 5090 Local AI Dev + Coding Agent

A corrected, working setup for an **NVIDIA RTX 5090** (Blackwell, `sm_120`, 32GB
GDDR7): CUDA dev toolchain, cu128 PyTorch, and a **local** LLM coding agent that
can write, compile, and run CUDA/Python on your machine — no cloud, no API key.

## What's here

| File | Purpose |
|------|---------|
| `setup_rtx5090.sh`  | Linux / WSL2 provisioner: CUDA Toolkit 12.8, cu128 PyTorch, Ollama, model pull, GPU smoke test. |
| `setup_rtx5090.ps1` | Windows host prep: driver check + WSL2 (then hand off to the `.sh`). |
| `requirements.txt`  | Modern LangChain + GPU libs (torch installed separately from cu128). |
| `agent_engine.py`   | The agent: local Ollama model + **real, sandboxed** compile/run tools. |

## Quick start

**Linux or WSL2 (Ubuntu):**
```bash
cd rtx5090-agent
chmod +x setup_rtx5090.sh
./setup_rtx5090.sh
source ~/.venvs/rtx5090/bin/activate
python agent_engine.py "Write a CUDA kernel that adds two vectors of 1M floats and verifies the result on the GPU."
```

**Windows:** run `setup_rtx5090.ps1` elevated → it installs WSL2 → then run the
`.sh` inside Ubuntu. Native-Windows PyTorch on Blackwell is still unreliable;
WSL2 is the supported path.

## Why the original one-liner script failed

These are real, breaking issues that were corrected here:

1. **`ollama pull deepseek-coder-v3`** — that tag does not exist. DeepSeek-**V3**
   is a 671B model that will not fit in 32GB. The right pick for a 5090 is
   **`qwen2.5-coder:32b`** (Q4_K_M ≈ 22GB, leaves room for context); a lighter
   fallback is `deepseek-coder-v2:16b`.
2. **Deprecated LangChain API** — `langchain_community.llms.Ollama` and
   `initialize_agent` are deprecated/removed. Use `langchain_ollama.ChatOllama`
   + `langchain.agents.create_agent`.
3. **The agent did nothing** — the old `run_cuda_task` just printed a string and
   returned text; it never wrote, compiled, or ran anything. Here the tools
   actually write files, invoke `nvcc -arch=sm_120` / `python`, and feed
   stdout/stderr/exit-code back to the model so it can self-debug.
4. **`nvidia-pyindex` + `nvidia-tensorrt`** — deprecated combo; TensorRT now
   installs as `tensorrt-cu12`.
5. **Driver install assumptions** — the GPU driver is a host/reboot concern
   (and on WSL2 the Linux side must NOT install a driver). The script *verifies*
   the driver instead of blindly installing one.

## ⚠️ Safety — read before `AGENT_AUTO_APPROVE=1`

`agent_engine.py` lets an LLM **execute code on your machine**. Mitigations baked in:

- All file writes are confined to `agent_workspace/` (path-traversal rejected).
- Every compile/run is **confirmed interactively** unless you opt out.
- Commands run with a timeout and **no shell** (no shell-injection surface).

It is a guarded local tool, **not a jail/VM**. Setting `AGENT_AUTO_APPROVE=1`
removes the human from the loop — only do that on a throwaway box or VM. Don't
point it at a machine holding secrets you wouldn't want a model to read.

## Useful env vars

| Var | Default | Meaning |
|-----|---------|---------|
| `OPENCLAW_AGENT_MODEL` | `qwen2.5-coder:32b` | Ollama model tag |
| `CODING_MODEL`        | `qwen2.5-coder:32b` | model the setup script pulls |
| `AGENT_WORKDIR`       | `./agent_workspace` | sandbox directory |
| `AGENT_AUTO_APPROVE`  | _(unset)_ | `1` = run without confirming (dangerous) |
| `AGENT_EXEC_TIMEOUT`  | `120` | per-command timeout (seconds) |
| `OLLAMA_HOST`         | `http://localhost:11434` | Ollama daemon URL |
