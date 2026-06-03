#!/usr/bin/env bash
set -euo pipefail
OUT_BASE="${OUT_BASE:-$HOME/FLEX_showkit_artifacts}"
STAMP=$(date +%Y%m%d-%H%M%S); HOST_IP=$(hostname -I | awk "{print \$1}")
OUT="$OUT_BASE/$STAMP"; mkdir -p "$OUT"
curl -s -X POST "http://localhost:7860/bringup" -H "accept: application/json" > "$OUT/bringup.json" || true
curl -s -X POST "http://localhost:7860/zoomcoach" -H "accept: application/json" > "$OUT/zoomcoach.json" || true
curl -s "http://localhost:7860/metrics" | head -n 100 > "$OUT/metrics.txt" || true
for f in /opt/flexcoach/export/bringup.csv /opt/flexcoach/export/zoomcoach.csv /opt/flexcoach/export/transcribe.csv; do
  [ -f "$f" ] && cp "$f" "$OUT/" || true
done
{ echo "timestamp=$STAMP"; echo "host_ip=$HOST_IP"; echo "ui=http://$HOST_IP:7860"; } > "$OUT/metadata.txt"
echo "Bundle: $OUT"
