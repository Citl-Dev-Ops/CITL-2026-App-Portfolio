#!/usr/bin/env bash
set -euo pipefail

# Desktop Windows variant: prefer Program Files, fall back to ProgramData
DST_BASE="${DST_BASE:-}"
if [[ -z "${DST_BASE}" ]]; then
  if [[ -d "/c/Program Files/citl-tools/common/resources" ]]; then
    DST_BASE="/c/Program Files/citl-tools"
  elif [[ -d "/c/ProgramData/citl-tools/common/resources" ]]; then
    DST_BASE="/c/ProgramData/citl-tools"
  else
    DST_BASE="/c/Program Files/citl-tools"
  fi
fi
RES_DIR="${DST_BASE}/common/resources"
FACT_FILE="${RES_DIR}/factbook.json"

echo "[CITL] Factbook (Desktop) running (base: ${DST_BASE})"

if [[ -f "${FACT_FILE}" ]]; then
  cat "${FACT_FILE}"
  exit 0
fi

# Fallback message for Windows users
cat <<'JSON'
{"sample_fact":"Desktop Factbook not installed; place JSON at %ProgramFiles%\\citl-tools\\common\\resources\\factbook.json or %ProgramData%\\citl-tools\\common\\resources\\factbook.json"}
JSON
