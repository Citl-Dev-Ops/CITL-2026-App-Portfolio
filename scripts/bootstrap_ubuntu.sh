mkdir -p scripts results models
cat > scripts/bootstrap_ubuntu.sh <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

echo "== CITL Bootstrap (Ubuntu) =="
echo "Repo: $REPO_ROOT"

# ---- System deps (Ubuntu 24.04 / Noble) ----
# NOTE: python3-venv is the correct fix for the 'ensurepip not available' venv error on Ubuntu.
sudo apt update
sudo apt install -y \
  python3 python3-venv python3-pip python3-dev \
  python3-pyqt6 \
  ffmpeg \
  pciutils xdg-utils curl git \
  ca-certificates

# ---- Python venv (avoids PEP 668 externally-managed-environment) ----
if [[ ! -d ".venv" ]]; then
  echo "Creating venv..."
  python3 -m venv .venv
fi

echo "Upgrading pip tooling inside venv..."
. .venv/bin/activate
python -m pip install -U pip setuptools wheel

# ---- Install Python deps (if requirements.txt exists) ----
if [[ -f "requirements.txt" ]]; then
  echo "Installing requirements.txt into venv..."
  python -m pip install -r requirements.txt
else
  echo "WARNING: requirements.txt not found at repo root. Skipping pip install."
fi

# ---- Ollama presence check (do not auto-install unless you choose to) ----
if command -v ollama >/dev/null 2>&1; then
  echo "Ollama: OK ($(ollama --version 2>/dev/null || echo 'version unknown'))"
else
  echo "Ollama: MISSING"
  echo "Install Ollama on Linux (official): curl -fsSL https://ollama.com/install.sh | sh"
  echo "Docs: https://docs.ollama.com/linux"
  echo "NOTE: we are not auto-installing Ollama here to avoid changing your machine unexpectedly."
fi

# ---- GPU visibility check (optional) ----
if command -v nvidia-smi >/dev/null 2>&1; then
  echo "nvidia-smi: OK"
  nvidia-smi --query-gpu=index,name,memory.total,driver_version --format=csv,noheader || true
else
  echo "nvidia-smi: not found (GPU inventory will be limited)."
fi

# ---- Desktop launcher (GNOME favorites are separate; this creates the app entry) ----
DESK="$HOME/.local/share/applications/citl-run.desktop"
mkdir -p "$HOME/.local/share/applications"

cat > "$DESK" <<DESK_EOF
[Desktop Entry]
Name=CITL Run (Factbook + Transcribe)
Comment=Launch CITL local tools (uses venv)
Exec=sh -lc 'cd "$REPO_ROOT" && . .venv/bin/activate && python3 -m apps.launcher'
Icon=utilities-terminal
Terminal=false
Type=Application
Categories=Development;Education;
DESK_EOF

echo "Launcher written: $DESK"
echo "Bootstrap complete."
echo "Next: run ->  ./scripts/run_ubuntu.sh"
EOF

chmod +x scripts/bootstrap_ubuntu.sh