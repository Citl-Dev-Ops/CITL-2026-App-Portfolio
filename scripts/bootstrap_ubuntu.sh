#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

echo "== CITL Bootstrap (Ubuntu) =="
echo "Repo: $REPO_ROOT"

if command -v apt-get >/dev/null 2>&1; then
  if command -v sudo >/dev/null 2>&1; then
    sudo apt-get update -y
    sudo apt-get install -y \
      python3 python3-venv python3-pip python3-dev python3-tk \
      ffmpeg \
      libportaudio2 portaudio19-dev \
      alsa-utils pulseaudio-utils \
      xdg-utils curl git ca-certificates \
      build-essential
  else
    echo "WARN: sudo not available. Install manually."
  fi
fi

if [[ ! -d ".venv" ]]; then
  python3 -m venv .venv
fi

. .venv/bin/activate
python -m pip install -U pip setuptools wheel

if [[ -f "$REPO_ROOT/requirements-linux.txt" ]]; then
  python -m pip install -r "$REPO_ROOT/requirements-linux.txt"
elif [[ -f "$REPO_ROOT/requirements.txt" ]]; then
  python -m pip install -r "$REPO_ROOT/requirements.txt"
fi

if command -v ollama >/dev/null 2>&1; then
  echo "Ollama: OK"
else
  echo "Ollama: missing (optional). Install: curl -fsSL https://ollama.com/install.sh | sh"
fi

DESK="$HOME/.local/share/applications/citl-assistant.desktop"
mkdir -p "$HOME/.local/share/applications"

GUI="$REPO_ROOT/factbook-assistant/factbook_assistant_gui.py"
if [[ ! -f "$GUI" ]]; then
  GUI="$REPO_ROOT/factbook_assistant_gui.py"
fi

cat > "$DESK" <<DESK_EOF
[Desktop Entry]
Version=1.0
Name=CITL Desktop LLM Assistant
Comment=Factbook RAG + Transcription + Translation (local)
Exec=bash -lc 'cd "$REPO_ROOT" && . .venv/bin/activate && python3 "$GUI"'
Icon=utilities-terminal
Terminal=false
Type=Application
Categories=Education;Science;
StartupNotify=true
DESK_EOF

update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true
echo "Launcher installed: $DESK"
echo "Done."
