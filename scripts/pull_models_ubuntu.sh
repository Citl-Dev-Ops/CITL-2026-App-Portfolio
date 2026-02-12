cat > scripts/pull_models_ubuntu.sh <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

if ! command -v ollama >/dev/null 2>&1; then
  echo "ERROR: ollama not found. Install Ollama first."
  exit 1
fi

echo "Pulling recommended models for a CUDA workstation..."

# Fast general assistant
ollama pull llama3.1:8b

# Stronger general (good balance)
ollama pull qwen2.5:14b

# Coding-focused
ollama pull qwen2.5-coder:14b

# Lightweight + long context option
ollama pull phi3:14b

# Small fallback model for CPU / low overhead
ollama pull llama3.2:3b

echo "Done."
EOF
chmod +x scripts/pull_models_ubuntu.sh
