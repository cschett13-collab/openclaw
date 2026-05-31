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
| `agent_engine.py`   | The agent (**modern** lane): `create_agent` + CUDA/`nvcc` and Python tools, sandboxed. |
| `agent_engine_classic.py` | Same agent, **classic** lane: `create_tool_calling_agent` + `AgentExecutor`. |
| `run_everything.sh` | Gated entrypoint: syncs deps → runs the smoke test → starts the agent **only if it passes**. |
| `verify_gpu.py`     | Standalone smoke test: torch GPU op + `nvcc -arch=sm_120` compile/run + optional PyNvVideoCodec import. |
| `video_demo.py`     | GPU video decode/encode (NVDEC/NVENC) via PyNvVideoCodec, zero-copy to PyTorch. |
| `team.py`           | CLI for the **local AI Team** — six purpose-scoped agents + orchestration (see below). |
| `local_ai/`         | The team package: `llm`, `memory`, `tools`, `agents`, `orchestrator`. |

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

**Prove the GPU actually works (don't ask the LLM to "verify" it):**
```bash
python verify_gpu.py        # real torch op + nvcc sm_120 compile/run; exit 0 = good
```

**Gated all-in-one (smoke test must pass before the agent starts):**
```bash
./run_everything.sh                    # check, then interactive agent
./run_everything.sh "your first task"  # check, then run that task
./run_everything.sh --check-only       # just the smoke test
AGENT_LANE=classic ./run_everything.sh # use the classic-lane agent
```

### Honest scope

The agent has a `gpu_telemetry` tool (`nvidia-smi`) and is instructed to report
performance **only with before/after measurements**, never from intuition. It
still does **not** autonomously detect throughput ceilings or invent kernel
optimizations — a local 32B model frequently writes CUDA that won't compile or
is slower than baseline. Treat it as a capable assistant that runs and measures
what it writes, with you approving each execution — not an autonomous lab.

**GPU video (NVDEC/NVENC):**
```bash
python video_demo.py decode myclip.mp4            # decode -> GPU torch tensors
python video_demo.py transcode myclip.mp4 out.h264
```

## The Local AI Team (`local_ai/`)

`agent_engine.py` is one coding agent. `local_ai/` is the **six-agent team** from
[`../GOALS.md`](../GOALS.md), running fully local on the same Ollama daemon — no
cloud, no API keys — with shared memory and an orchestrator that routes work.

| Agent | Job | Tools |
|-------|-----|-------|
| `research`  | Finds & collects information | web fetch, files |
| `content`   | Writes, edits, creates | files |
| `analytics` | Analyzes data, finds insights | run python, files |
| `outreach`  | Drafts outreach (human sends) | files |
| `automation`| Builds & tests local workflows | run python, files, gpu telemetry |
| `support`   | Answers questions, solves problems | files, web fetch |

Every agent also gets `remember` / `recall` over a shared local memory.

**Systems underneath:**

- **Memory** (`memory.py`) — one SQLite file holds *episodic* (event log) and
  *semantic* (recall-by-meaning) memory. Semantic search uses local embeddings
  (`ollama pull nomic-embed-text`) and degrades to keyword search if unavailable.
- **Tools** (`tools.py`) — sandboxed to a workspace dir, same confirm-before-exec
  posture as `agent_engine.py` (no shell, timeouts, path-traversal rejected).
- **Orchestration** (`orchestrator.py`) — keyword router with an LLM tie-break,
  plus pipelines that pass one agent's output as the next's context, and
  error handling that records failures instead of crashing a run.

```bash
ollama pull qwen2.5-coder:32b        # the team's default model
ollama pull nomic-embed-text         # semantic memory (optional but recommended)

python team.py list                          # show the team
python team.py route "summarize Q2 metrics"  # auto-pick the best agent
python team.py analytics "load data.csv and report the top 3 trends"
python team.py chat                          # interactive, memory persists
python team.py pipeline                      # demo: research -> content
```

Force an agent in chat with a prefix: `content: write a launch tweet`. Memory
lives in `agent_memory.sqlite` (override with `LOCAL_AI_MEMORY`) and persists
across runs. Same safety switch applies: agents that execute code confirm each
run unless `AGENT_AUTO_APPROVE=1`.

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

## Two agent lanes (don't cross them)

Current LangChain offers two valid ways to build a tool-calling agent:

| | `agent_engine.py` (modern) | `agent_engine_classic.py` (classic) |
|---|---|---|
| factory | `create_agent(llm, tools, prompt=<system str>)` | `create_tool_calling_agent(llm, tools, prompt)` |
| executor | none — returns a ready graph | wrap in `AgentExecutor(...)` |
| prompt | system string | `ChatPromptTemplate` + `MessagesPlaceholder("agent_scratchpad")` |
| invoke | `{"messages": [...]}` | `{"input": ...}` |

**Common mistake:** `create_agent(llm, tools, prompt, "openai-tools")` then wrapping
in `AgentExecutor`. That fails — `create_agent` takes no agent-type arg and already
returns the runnable. Pick one lane; both are equivalent at runtime.

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
