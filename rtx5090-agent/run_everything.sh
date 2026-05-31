#!/usr/bin/env bash
#
# run_everything.sh — deterministic, honest entrypoint.
#
# This does NOT "sync your machine" and is NOT autonomous. It just chains the
# steps in a fixed order and REFUSES to start the agent unless the GPU smoke
# test passes — so the LLM never touches a broken CUDA/driver setup.
#
#   1. ensure the venv exists + deps installed   (sync_deps)
#   2. run verify_gpu.py                          (ground truth)
#   3. only if (2) passes -> start the agent      (gated)
#
# Usage:
#   ./run_everything.sh                       # smoke test, then interactive agent
#   ./run_everything.sh "your first task"     # smoke test, then run that task
#   ./run_everything.sh --check-only          # just the smoke test, no agent
#
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${VENV_DIR:-$HOME/.venvs/rtx5090}"
AGENT_LANE="${AGENT_LANE:-modern}"   # modern -> agent_engine.py, classic -> agent_engine_classic.py

log()  { printf '\033[1;32m[run]\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31m[stop]\033[0m %s\n' "$*" >&2; exit 1; }

# --- 1. venv + deps -------------------------------------------------------
if [[ ! -f "$VENV_DIR/bin/activate" ]]; then
  die "venv not found at $VENV_DIR. Run ./setup_rtx5090.sh first."
fi
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"
log "Syncing deps (idempotent)..."
pip install -q -r "$HERE/requirements.txt"

# --- 2. ground-truth smoke test ------------------------------------------
log "Running GPU smoke test (verify_gpu.py)..."
if ! python "$HERE/verify_gpu.py"; then
  die "Smoke test FAILED. Fix the GPU/driver/toolkit issue above before the
       agent runs. The most common causes on a 5090 are: driver too old for
       Blackwell, CUDA Toolkit < 12.8 (no sm_120), or WSL2 device passthrough."
fi
log "Smoke test passed — GPU is usable."

[[ "${1:-}" == "--check-only" ]] && { log "--check-only set; done."; exit 0; }

# --- 3. gated agent launch -----------------------------------------------
if [[ "$AGENT_LANE" == "classic" ]]; then
  ENGINE="$HERE/agent_engine_classic.py"
else
  ENGINE="$HERE/agent_engine.py"
fi
log "Starting agent ($AGENT_LANE lane). It executes code it writes — you approve each run."
exec python "$ENGINE" "$@"
