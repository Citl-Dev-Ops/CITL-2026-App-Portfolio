#!/usr/bin/env bash
set -euo pipefail

# Cannakit variant: prefer /opt/citl-tools layout
DST_BASE="${DST_BASE:-/opt/citl-tools}"
RES_DIR="${DST_BASE}/common/resources"
FACT_FILE="${RES_DIR}/factbook.json"

echo "[CITL] Factbook (Cannakit) running (base: ${DST_BASE})"

if [[ -f "${FACT_FILE}" ]]; then
  # print file contents; keep safe for environments without jq
  cat "${FACT_FILE}"
  exit 0
fi

# Fallback: simple built-in JSON
cat <<'JSON'
{"sample_fact":"Cannakit Factbook not installed; place JSON at /opt/citl-tools/common/resources/factbook.json"}
JSON
