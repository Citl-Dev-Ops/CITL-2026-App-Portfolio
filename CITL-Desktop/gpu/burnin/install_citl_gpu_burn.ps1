# PowerShell version of the GPU Burn installation script

# Check if NVIDIA GPU is present
if (-not (Get-Command nvidia-smi -ErrorAction SilentlyContinue)) {
    Write-Host "[CITL] No NVIDIA GPU detected (nvidia-smi not found)."
    Write-Host "[CITL] Skipping GPU Burn installation."
    exit 1
}

# Check if CUDA compiler (nvcc) is available
if (-not (Get-Command nvcc -ErrorAction SilentlyContinue)) {
    Write-Host "[CITL] ERROR: nvcc (CUDA compiler) not found. Install CUDA toolkit first."
    exit 1
}

# Define paths
$gpuBurnSrcDir = "C:\00 HENOSIS CODING PROJECTS\CITL PROJECTS\CITL - Desktop LLM EZ Install Kits\gpu\burnin\gpu-burn"
$gpuBurnDstDir = "C:\opt\citl-tools\gpu-burn"

# Create destination directory
Write-Host "[CITL] Installing GPU Burn from: $gpuBurnSrcDir"
New-Item -ItemType Directory -Force -Path $gpuBurnDstDir | Out-Null
Copy-Item -Recurse -Force -Path "$gpuBurnSrcDir\*" -Destination $gpuBurnDstDir

# Build the gpu_burn binary
Write-Host "[CITL] Building gpu_burn with nvcc..."
Push-Location $gpuBurnDstDir
Invoke-Expression "make clean" -ErrorAction SilentlyContinue
Invoke-Expression "make"
Pop-Location

# Create wrapper command
$wrapperPath = "C:\ProgramData\citl-gpu-burn.bat"
Set-Content -Path $wrapperPath -Value @"
@echo off
set GPU_BURN_DIR=$gpuBurnDstDir
cd %GPU_BURN_DIR%
set TIME=%1
if "%TIME%"=="" set TIME=600
echo [CITL] Running GPU Burn for %TIME%s on all GPUs using ~80%% memory...
gpu_burn.exe -m 80%% -tc %TIME%
"@

Write-Host "[CITL] GPU Burn installed."
Write-Host "      Example:  $wrapperPath 300"
