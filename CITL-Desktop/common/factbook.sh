#!/usr/bin/env bash
set -euo pipefail

# Determine installation base if run directly or via wrapper
if [[ -z "${DST_BASE:-}" ]]; then
  # Try common locations
  if [[ -d "/c/opt/citl-tools/common" ]]; then
    DST_BASE="/c/opt/citl-tools"
  else
    DST_BASE="/opt/citl-tools"
  fi
fi

# ...existing code...
# Example behavior: print a sample fact or load data from DST_BASE/resources/factbook.json
echo "[CITL] Running Factbook (base: ${DST_BASE})"
# If resource file exists use it, otherwise fallback to built-in sample
FACT_FILE="${DST_BASE}/common/resources/factbook.json"
if [[ -f "${FACT_FILE}" ]]; then
  # minimal safe jq-free cat; consumers can adapt to parse JSON as needed
  cat "${FACT_FILE}"
else
  echo '{"sample_fact":"Citl Factbook not installed; please populate '"${FACT_FILE}"'"}'
fi
