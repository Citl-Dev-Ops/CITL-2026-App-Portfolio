#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="${SCRIPT_DIR}/bin"

# Allow override with an explicit backend path.
if [[ -n "${CITL_TTS_BACKEND:-}" ]]; then
  exec "${CITL_TTS_BACKEND}" "$@"
fi

# Default preference: GPU if present, else CPU; override with CITL_TTS_MODE=cpu
if [[ "${CITL_TTS_MODE:-}" == "cpu" ]]; then
  CANDIDATES=( "tts_cpu" )
else
  CANDIDATES=( "tts_cuda" "tts_cpu" )
fi

for exe in "${CANDIDATES[@]}"; do
  if [[ -x "${BIN_DIR}/${exe}" ]]; then
    if [[ "${exe}" == "tts_cuda" ]]; then
      export CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-0}"
    fi
    exec "${BIN_DIR}/${exe}" "$@"
  fi
done

echo "[CITL] No TTS backend found under: ${BIN_DIR}"
echo "[CITL] Expected tts_cpu or tts_cuda. If using Python, install Coqui TTS:"
echo "  pip install TTS"
exit 1
