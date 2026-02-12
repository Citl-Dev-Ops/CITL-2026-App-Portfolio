cat > scripts/run_ubuntu.sh <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"
. .venv/bin/activate
python3 -m apps.launcher
EOF
chmod +x scripts/run_ubuntu.sh
