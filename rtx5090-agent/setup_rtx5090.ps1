<#
  setup_rtx5090.ps1 — Windows host bootstrap for an RTX 5090 dev box.

  IMPORTANT: Native-Windows PyTorch support for Blackwell (sm_120) is flaky.
  The supported, sane path is WSL2 + Ubuntu, then run setup_rtx5090.sh inside it.
  This script prepares the WINDOWS side: driver check, WSL2, CUDA-on-WSL prereqs.

  Run from an elevated PowerShell:
      Set-ExecutionPolicy -Scope Process Bypass
      .\setup_rtx5090.ps1
#>
[CmdletBinding()]
param(
    [switch]$SkipWsl
)
$ErrorActionPreference = 'Stop'

function Info($m){ Write-Host "[setup] $m" -ForegroundColor Green }
function Warn($m){ Write-Host "[warn]  $m" -ForegroundColor Yellow }
function Die ($m){ Write-Host "[fail]  $m" -ForegroundColor Red; exit 1 }

# ----- 0. admin check -----------------------------------------------------
$id = [Security.Principal.WindowsIdentity]::GetCurrent()
if (-not ([Security.Principal.WindowsPrincipal]$id).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Die "Run this in an ELEVATED PowerShell (Run as Administrator)."
}

# ----- 1. driver / GPU check ---------------------------------------------
Info "Checking NVIDIA driver..."
$smi = "$env:WINDIR\System32\nvidia-smi.exe"
if (-not (Test-Path $smi)) {
    Die "nvidia-smi not found. Install the latest NVIDIA Game Ready / Studio driver
         (RTX 5090 needs a Blackwell-capable driver, >= 570 series) from nvidia.com,
         then re-run."
}
& $smi --query-gpu=name,driver_version,memory.total --format=csv,noheader |
    ForEach-Object { Info "GPU: $_" }

# ----- 2. WSL2 ------------------------------------------------------------
if ($SkipWsl) {
    Warn "-SkipWsl set; not touching WSL."
} else {
    Info "Ensuring WSL2 + Ubuntu is installed..."
    # `wsl --status` exits non-zero if WSL is absent.
    $wslOk = $false
    try { wsl --status *>$null; $wslOk = ($LASTEXITCODE -eq 0) } catch {}
    if (-not $wslOk) {
        Info "Installing WSL2 with Ubuntu (a reboot will be required)..."
        wsl --install -d Ubuntu
        Warn "Reboot Windows, then open 'Ubuntu', and inside it run:"
        Warn "    ./setup_rtx5090.sh"
        exit 0
    }
    wsl --set-default-version 2 | Out-Null
    Info "WSL2 present. The NVIDIA Windows driver provides the CUDA passthrough;"
    Info "do NOT install a Linux GPU driver inside WSL."
}

# ----- 3. hand off to the Linux script -----------------------------------
Info "Windows side ready."
Write-Host ""
Write-Host "  Next steps (inside WSL2 / Ubuntu):" -ForegroundColor Cyan
Write-Host "    cd <this repo>/rtx5090-agent"
Write-Host "    chmod +x setup_rtx5090.sh && ./setup_rtx5090.sh"
Write-Host ""
Write-Host "  That installs CUDA Toolkit 12.8, cu128 PyTorch, Ollama, and the agent." -ForegroundColor Cyan
