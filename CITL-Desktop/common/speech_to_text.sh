
#!/usr/bin/env bash
set -euo pipefail

# Determine installation base
if [[ -z "${DST_BASE:-}" ]]; then
  if [[ -d "/c/opt/citl-tools" ]]; then
    DST_BASE="/c/opt/citl-tools"
  else
    DST_BASE="/opt/citl-tools"
  fi
fi

has_gpu() {
  command -v nvidia-smi >/dev/null 2>&1
}

INFILE="${1:-}"
if [[ -z "${INFILE}" ]]; then
  echo "Usage: citl-stt audio_file.wav"
  exit 2
fi

echo "[CITL] citl-stt invoked on ${INFILE} (base: ${DST_BASE})"

GPU_BINARY="${DST_BASE}/common/bin/stt_cuda"
CPU_BINARY="${DST_BASE}/common/bin/stt_cpu"

if has_gpu && [[ -x "${GPU_BINARY}" ]]; then
  echo "[CITL] Using GPU-accelerated STT"
  exec "${GPU_BINARY}" --in "${INFILE}"
elif [[ -x "${CPU_BINARY}" ]]; then
  echo "[CITL] Using CPU STT binary"
  exec "${CPU_BINARY}" --in "${INFILE}"
else
  # Minimal fallback: try pocketsphinx-simple or other system tool
  if command -v pocketsphinx_continuous >/dev/null 2>&1; then
    pocketsphinx_continuous -infile "${INFILE}"
  else
    echo "[CITL] No STT engine found. Install ${DST_BASE}/common/bin/stt_* or install system STT tools."
    exit 1
  fi
fi