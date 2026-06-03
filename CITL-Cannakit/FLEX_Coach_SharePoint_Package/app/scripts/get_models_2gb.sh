#!/usr/bin/env bash
set -euo pipefail
TARGET_DIR="/opt/flexcoach/models"
[ -d "$TARGET_DIR" ] || { TARGET_DIR="./models"; mkdir -p "$TARGET_DIR"; }
python3 -m pip install --upgrade pip >/dev/null 2>&1 || true
python3 -m pip install --upgrade "huggingface_hub[cli]" >/dev/null 2>&1 || true
python3 - <<PY
import os
from huggingface_hub import snapshot_download
td=os.environ.get("TARGET_DIR","./models")
snapshot_download("TheBloke/TinyLlama-1.1B-Chat-v1.0-GGUF",
  allow_patterns=["*Q2_K*.gguf"],local_dir=td,local_dir_use_symlinks=False)
snapshot_download("ggerganov/whisper.cpp",
  allow_patterns=["ggml-tiny.en.bin"],local_dir=td,local_dir_use_symlinks=False)
print("Done ->",td)
PY
ls -lh "$TARGET_DIR"
