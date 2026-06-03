#!/usr/bin/env bash
set -euo pipefail
echo "=== FLEX Coach Installer (Lite 2GB profile) ==="
# ... your existing installer steps (apt, build llama.cpp/whisper.cpp) ...
echo "Applying 2GB profile (tiny models + config) ..."
bash app/scripts/get_models_2gb.sh
bash app/scripts/patch_2gb_config.sh
echo "Self-test bundle ..."
bash app/scripts/capture_artifacts.sh || true
echo "Done."
