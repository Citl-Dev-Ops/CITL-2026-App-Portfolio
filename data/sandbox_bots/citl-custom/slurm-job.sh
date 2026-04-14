#!/usr/bin/env bash
#SBATCH --job-name=citl-custom
#SBATCH --output=slurm-%j.out
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export OLLAMA_HOST="${OLLAMA_HOST:-http://127.0.0.1:11434}"
export OLLAMA_MODEL="${OLLAMA_MODEL:-citl-custom}"
python3 "$DIR/run_demo.py"
