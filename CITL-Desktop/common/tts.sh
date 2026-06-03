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

# Simple GPU detection
has_gpu() {
  command -v nvidia-smi >/dev/null 2>&1
}

# Usage: citl-tts "Text to speak" [out.wav]
TEXT="${1:-}"
OUT="${2:-}"

if [[ -z "${TEXT}" ]]; then
  echo "Usage: citl-tts \"Text to speak\" [out.wav]"
  exit 2
fi

echo "[CITL] citl-tts invoked (base: ${DST_BASE})"

# Prefer GPU binary if present and GPU is available
GPU_BINARY="${DST_BASE}/common/bin/tts_cuda"   # placeholder path
CPU_BINARY="${DST_BASE}/common/bin/tts_cpu"    # placeholder path

if has_gpu && [[ -x "${GPU_BINARY}" ]]; then
  echo "[CITL] Using GPU-accelerated TTS"
  if [[ -n "${OUT}" ]]; then
    exec "${GPU_BINARY}" --text "${TEXT}" --out "${OUT}"
  else
    exec "${GPU_BINARY}" --text "${TEXT}"
  fi
elif [[ -x "${CPU_BINARY}" ]]; then
  echo "[CITL] Using CPU TTS binary"
  if [[ -n "${OUT}" ]]; then
    exec "${CPU_BINARY}" --text "${TEXT}" --out "${OUT}"
  else
    exec "${CPU_BINARY}" --text "${TEXT}"
  fi
else
  # Minimal fallback: use system say (mac) or speech-dispatcher (Linux) or print
  if command -v say >/dev/null 2>&1; then
    say "${TEXT}"
  elif command -v spd-say >/dev/null 2>&1; then
    spd-say "${TEXT}"
  else
    echo "${TEXT}"
    echo "[CITL] No TTS binary found. Install the TTS binaries into ${DST_BASE}/common/bin or install system TTS."
    exit 1
  fi
fi
