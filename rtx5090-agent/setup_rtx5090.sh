#!/usr/bin/env bash
#
# setup_rtx5090.sh — Provision an RTX 5090 (Blackwell, sm_120) box for local
# CUDA dev + image/video generation + a local LLM coding agent.
#
# Target: Ubuntu 22.04/24.04, native Linux OR Windows-WSL2 (Ubuntu).
#         On Windows do NOT run this in native PowerShell — use WSL2.
#
# Safe by default:
#   - never auto-installs the GPU DRIVER (that's a host/reboot concern); it
#     verifies one is present and tells you what to do if not.
#   - idempotent-ish: re-running skips what already exists.
#   - uses a Python venv, never touches system Python.
#
# Usage:
#   chmod +x setup_rtx5090.sh
#   ./setup_rtx5090.sh                 # full setup
#   ./setup_rtx5090.sh --skip-models   # skip the (large) ollama pulls
#
set -euo pipefail

# ----- config -------------------------------------------------------------
CUDA_SERIES="12.8"                       # first toolkit series with sm_120 support
TORCH_INDEX="https://download.pytorch.org/whl/cu128"
# Best local coder that fits 32GB GDDR7 at Q4_K_M (~22GB). Override via env.
CODING_MODEL="${CODING_MODEL:-qwen2.5-coder:32b}"
FALLBACK_MODEL="deepseek-coder-v2:16b"   # lighter option if VRAM is tight
VENV_DIR="${VENV_DIR:-$HOME/.venvs/rtx5090}"
SKIP_MODELS=0
[[ "${1:-}" == "--skip-models" ]] && SKIP_MODELS=1

log()  { printf '\033[1;32m[setup]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[warn]\033[0m  %s\n' "$*"; }
die()  { printf '\033[1;31m[fail]\033[0m  %s\n' "$*" >&2; exit 1; }

# ----- 0. sanity: GPU + driver --------------------------------------------
log "Checking NVIDIA driver / GPU visibility..."
if ! command -v nvidia-smi >/dev/null 2>&1; then
  die "nvidia-smi not found. Install the latest NVIDIA driver first.
       Native Linux:  sudo apt install nvidia-driver-570 (or newer; 5090 needs >= 570)
       WSL2:          install the driver on WINDOWS, not inside WSL. Do NOT
                      install a Linux driver in WSL — the GPU is passed through."
fi
nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader \
  | sed 's/^/  GPU: /'
if ! nvidia-smi --query-gpu=name --format=csv,noheader | grep -qi "5090"; then
  warn "Did not detect an RTX 5090 by name — continuing anyway."
fi

# ----- 1. CUDA toolkit -----------------------------------------------------
# We need nvcc for native CUDA compilation. The torch wheels bundle their own
# CUDA runtime, but the AGENT compiles .cu files, so a real toolkit is required.
log "Checking CUDA Toolkit (need series ${CUDA_SERIES}+ for sm_120)..."
if command -v nvcc >/dev/null 2>&1; then
  nvcc --version | grep -i release | sed 's/^/  /'
else
  warn "nvcc not found. Installing CUDA Toolkit ${CUDA_SERIES} via NVIDIA apt repo."
  warn "If you prefer the .run installer, abort now (Ctrl-C) and use NVIDIA's site."
  . /etc/os-release
  distro="ubuntu${VERSION_ID//./}"            # e.g. ubuntu2404
  arch="$(uname -m)"; [[ "$arch" == "aarch64" ]] && arch="sbsa" || arch="x86_64"
  keyring="cuda-keyring_1.1-1_all.deb"
  tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
  ( cd "$tmp"
    wget -q "https://developer.download.nvidia.com/compute/cuda/repos/${distro}/${arch}/${keyring}"
    sudo dpkg -i "$keyring"
  )
  sudo apt-get update -y
  # cuda-toolkit-12-8 pulls nvcc + libs WITHOUT the bundled driver.
  sudo apt-get install -y "cuda-toolkit-${CUDA_SERIES/./-}"
  export PATH="/usr/local/cuda-${CUDA_SERIES}/bin:$PATH"
  grep -q "cuda-${CUDA_SERIES}/bin" "$HOME/.bashrc" 2>/dev/null || \
    echo "export PATH=/usr/local/cuda-${CUDA_SERIES}/bin:\$PATH" >> "$HOME/.bashrc"
  command -v nvcc >/dev/null || die "nvcc still not on PATH; open a new shell and re-run."
fi

# cuDNN / TensorRT note: the torch cu128 wheels bundle cuDNN. Standalone cuDNN
# is only needed for non-torch C/C++ builds; install via `apt install cudnn`
# from the same NVIDIA repo if you need it. TensorRT comes from pip below.

# ----- 2. Python venv + torch (cu128) -------------------------------------
log "Creating Python venv at ${VENV_DIR}..."
command -v python3 >/dev/null || die "python3 not found."
python3 -m venv "$VENV_DIR"
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"
python -m pip install --upgrade pip wheel

log "Installing PyTorch from the cu128 index (sm_120 Blackwell kernels)..."
# Must come from the cu128 index — the default PyPI build is CPU/sm_90 only
# and will refuse to run on the 5090 ("sm_120 is not compatible").
pip install torch torchvision torchaudio --index-url "$TORCH_INDEX"

log "Installing agent framework + GPU libs..."
pip install -r "$(dirname "$0")/requirements.txt"

# ----- 3. verify torch actually sees the 5090 -----------------------------
log "Verifying PyTorch can target the GPU..."
python - <<'PY'
import sys, torch
print(f"  torch        : {torch.__version__}")
print(f"  cuda built   : {torch.version.cuda}")
print(f"  is_available : {torch.cuda.is_available()}")
if not torch.cuda.is_available():
    sys.exit("  ERROR: CUDA not available to torch. Check driver/WSL passthrough.")
name = torch.cuda.get_device_name(0)
cap  = torch.cuda.get_device_capability(0)
print(f"  device       : {name}  sm_{cap[0]}{cap[1]}")
# A real op forces kernel launch; catches the silent 'no sm_120 kernel' case.
x = torch.randn(2048, 2048, device="cuda")
print(f"  matmul ok    : {bool((x @ x).sum().isfinite())}")
PY

# ----- 4. Ollama + local coding model -------------------------------------
if ! command -v ollama >/dev/null 2>&1; then
  log "Installing Ollama..."
  curl -fsSL https://ollama.com/install.sh | sh
fi
# Make sure the daemon is up (systemd on native, manual on WSL).
if ! curl -fsS http://localhost:11434/api/version >/dev/null 2>&1; then
  log "Starting Ollama daemon in background..."
  (ollama serve >/tmp/ollama.log 2>&1 &) ; sleep 3
fi

if [[ "$SKIP_MODELS" -eq 1 ]]; then
  warn "--skip-models set; not pulling ${CODING_MODEL}."
else
  log "Pulling coding model: ${CODING_MODEL} (this is several GB)..."
  if ! ollama pull "$CODING_MODEL"; then
    warn "Pull of ${CODING_MODEL} failed; trying fallback ${FALLBACK_MODEL}."
    ollama pull "$FALLBACK_MODEL"
    CODING_MODEL="$FALLBACK_MODEL"
  fi
fi

log "Done."
echo
echo "  Activate the env : source ${VENV_DIR}/bin/activate"
echo "  Run the agent    : OPENCLAW_AGENT_MODEL=${CODING_MODEL} python $(dirname "$0")/agent_engine.py"
echo
echo "  Reminder: the agent EXECUTES code it generates. Read agent_engine.py's"
echo "  safety section before turning off the confirmation prompt."
