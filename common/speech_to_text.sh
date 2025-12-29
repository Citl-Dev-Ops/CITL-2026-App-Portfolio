#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="${SCRIPT_DIR}/bin"

if [[ -n "${CITL_STT_BACKEND:-}" ]]; then
  exec "${CITL_STT_BACKEND}" "$@"
fi

if [[ "${CITL_STT_MODE:-}" == "cpu" ]]; then
  CANDIDATES=( "stt_cpu" )
else
  CANDIDATES=( "stt_cuda" "stt_cpu" )
fi

for exe in "${CANDIDATES[@]}"; do
  if [[ -x "${BIN_DIR}/${exe}" ]]; then
    if [[ "${exe}" == "stt_cuda" ]]; then
      export CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-0}"
    fi
    exec "${BIN_DIR}/${exe}" "$@"
  fi
done

echo "[CITL] No STT backend found under: ${BIN_DIR}"
echo "[CITL] Expected stt_cpu or stt_cuda. If using Python, install Vosk:"
echo "  pip install vosk"
echo "and install a compatible language model."
exit 1
