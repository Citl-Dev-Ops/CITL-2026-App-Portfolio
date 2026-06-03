#!/usr/bin/env bash
set -euo pipefail

# Desktop-only CUDA stress harness for CITL
# Do NOT run this on Cannakits or lightweight GPUs.

if ! command -v nvidia-smi >/dev/null 2>&1; then
  echo "[CITL] No NVIDIA GPU detected (nvidia-smi not found)."
  echo "[CITL] Skipping GPU Burn installation."
  exit 1
fi

if [[ "${CITL_DISABLE_GPU_BURN:-0}" == "1" ]]; then
  echo "[CITL] CITL_DISABLE_GPU_BURN=1 – skipping GPU Burn install."
  exit 0
fi

GPU_BURN_SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/gpu-burn"
GPU_BURN_DST_DIR="/c/opt/citl-tools/gpu-burn" # Updated path for Windows compatibility

echo "[CITL] Installing GPU Burn from: ${GPU_BURN_SRC_DIR}"
mkdir -p "${GPU_BURN_DST_DIR}" # Removed 'sudo' for Windows compatibility
cp -a "${GPU_BURN_SRC_DIR}/." "${GPU_BURN_DST_DIR}/"
cd "${GPU_BURN_DST_DIR}"

# Build the gpu_burn binary (CUDA toolkit must be present)
echo "[CITL] Building gpu_burn with nvcc…"
if ! command -v nvcc >/dev/null 2>&1; then
  echo "[CITL] ERROR: nvcc (CUDA compiler) not found. Install CUDA toolkit first."
  exit 1
fi

make clean || true
make

# Create wrapper command
tee /usr/local/bin/citl-gpu-burn >/dev/null <<'EOF' # Adjusted path for Windows
#!/usr/bin/env bash
set -euo pipefail

if ! command -v nvidia-smi >/dev/null 2>&1; then
  echo "[CITL] No NVIDIA GPU detected (nvidia-smi not found)."
  exit 1
fi

GPU_BURN_DIR="/c/opt/citl-tools/gpu-burn" # Updated path for Windows compatibility
cd "${GPU_BURN_DIR}"

# Default: 600 seconds (10 minutes)
TIME="${1:-600}"

echo "[CITL] Running GPU Burn for ${TIME}s on all GPUs using ~80% memory…"
./gpu_burn -m 80% -tc "${TIME}"
EOF

chmod +x /usr/local/bin/citl-gpu-burn # Removed 'sudo' for Windows compatibility

echo "[CITL] GPU Burn installed."
echo "      Example:  sudo citl-gpu-burn 300"