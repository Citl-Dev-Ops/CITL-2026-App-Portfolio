#!/usr/bin/env bash
set -euo pipefail
CFG="/opt/flexcoach/config.yaml"; SERVICE="flexcoach"
[ -f "$CFG" ] || CFG="./config.yaml"
grep -q '^llm_model_path:' "$CFG" 2>/dev/null \
  && sudo sed -i 's#^llm_model_path:.*#llm_model_path: models/tinyllama-1.1b-chat.Q2_K.gguf#' "$CFG" \
  || echo "llm_model_path: models/tinyllama-1.1b-chat.Q2_K.gguf" | sudo tee -a "$CFG" >/dev/null
grep -q '^max_context_chunks:' "$CFG" 2>/dev/null \
  && sudo sed -i 's/^max_context_chunks:.*/max_context_chunks: 4/' "$CFG" \
  || echo "max_context_chunks: 4" | sudo tee -a "$CFG" >/dev/null
grep -q '^max_new_tokens:' "$CFG" 2>/dev/null \
  && sudo sed -i 's/^max_new_tokens:.*/max_new_tokens: 160/' "$CFG" \
  || echo "max_new_tokens: 160" | sudo tee -a "$CFG" >/dev/null
sudo rm -f /opt/flexcoach/models/ggml-base.en.bin 2>/dev/null || true
systemctl list-units --type=service | grep -q "$SERVICE" && sudo systemctl restart "$SERVICE" || true
echo "Patched $CFG for 2GB show kit."
