#!/usr/bin/env bash
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export OLLAMA_HOST="${OLLAMA_HOST:-http://127.0.0.1:11434}"
export OLLAMA_MODEL="${OLLAMA_MODEL:-citl-custom}"
export PROMPT_FILE="${PROMPT_FILE:-$DIR/demo_prompt.txt}"
python3 "$DIR/run_demo.py"
