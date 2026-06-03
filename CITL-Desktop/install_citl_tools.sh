#!/usr/bin/env bash
set -euo pipefail

# ...existing code...

# Determine project root (this script location)
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Autodetect environment: prefer explicit INSTALL_TARGET env var
INSTALL_TARGET="${INSTALL_TARGET:-auto}"  # "desktop", "cannakit", or "auto"

detect_target() {
  if [[ "${INSTALL_TARGET}" != "auto" ]]; then
    echo "${INSTALL_TARGET}"
    return
  fi

  uname_s="$(uname -s 2>/dev/null || echo unknown)"
  # Git Bash / MSYS / MINGW -> treat as desktop Windows
  if echo "${uname_s}" | grep -iqE "mingw|msys|cygwin"; then
    echo "desktop"
    return
  fi

  # If /etc/os-release contains "cannakit" or a lightweight marker, prefer cannakit
  if [[ -f /etc/os-release ]] && grep -iq "cannakit" /etc/os-release; then
    echo "cannakit"
    return
  fi

  # Fallback: if nvidia-smi exists -> desktop, else cannakit
  if command -v nvidia-smi >/dev/null 2>&1; then
    echo "desktop"
  else
    echo "cannakit"
  fi
}

TARGET="$(detect_target)"
echo "[CITL] Install target: ${TARGET}"

# Set destination base depending on target
if [[ "${TARGET}" == "desktop" ]]; then
  DST_BASE="/c/Program Files/citl-tools"
  # prefer ProgramData if permissions needed to write without elevated Git Bash:
  DST_BASE_FALLBACK="/c/ProgramData/citl-tools"
  SUDO_CMD=""   # avoid sudo on Windows
else
  DST_BASE="/opt/citl-tools"
  SUDO_CMD="sudo"
fi

COMMON_SRC="${PROJECT_ROOT}/common"
mkdir -p "${COMMON_SRC}" # ensure common exists (no-op if present)

# If archive exists at PROJECT_ROOT/common-binaries.zip, prefer extracting it
if [[ -f "${PROJECT_ROOT}/common-binaries.zip" ]]; then
  echo "[CITL] Found prebuilt archive: ${PROJECT_ROOT}/common-binaries.zip"
  if [[ "${SUDO_CMD}" != "" ]]; then
    ${SUDO_CMD} mkdir -p "${DST_BASE}"
    ${SUDO_CMD} unzip -o "${PROJECT_ROOT}/common-binaries.zip" -d "${DST_BASE}" >/dev/null
    ${SUDO_CMD} chmod -R a+rX "${DST_BASE}"
  else
    mkdir -p "${DST_BASE}" 2>/dev/null || mkdir -p "${DST_BASE_FALLBACK}"
    if [[ -d "${DST_BASE}" ]]; then
      unzip -o "${PROJECT_ROOT}/common-binaries.zip" -d "${DST_BASE}" >/dev/null
      chmod -R a+rX "${DST_BASE}"
    else
      unzip -o "${PROJECT_ROOT}/common-binaries.zip" -d "${DST_BASE_FALLBACK}" >/dev/null
      chmod -R a+rX "${DST_BASE_FALLBACK}"
      DST_BASE="${DST_BASE_FALLBACK}"
    fi
  fi
else
  echo "[CITL] No prebuilt archive found. Running packaging step to create common/bin..."
  # run packaging helper (creates common/bin and common-binaries.zip)
  if command -v bash >/dev/null 2>&1 && [[ -x "${PROJECT_ROOT}/package_binaries.sh" ]]; then
    bash "${PROJECT_ROOT}/package_binaries.sh"
    # extract into DST_BASE
    if [[ "${SUDO_CMD}" != "" ]]; then
      ${SUDO_CMD} mkdir -p "${DST_BASE}"
      ${SUDO_CMD} unzip -o "${PROJECT_ROOT}/common-binaries.zip" -d "${DST_BASE}" >/dev/null
      ${SUDO_CMD} chmod -R a+rX "${DST_BASE}"
    else
      mkdir -p "${DST_BASE}" 2>/dev/null || mkdir -p "${DST_BASE_FALLBACK}"
      if [[ -d "${DST_BASE}" ]]; then
        unzip -o "${PROJECT_ROOT}/common-binaries.zip" -d "${DST_BASE}" >/dev/null
        chmod -R a+rX "${DST_BASE}"
      else
        unzip -o "${PROJECT_ROOT}/common-binaries.zip" -d "${DST_BASE_FALLBACK}" >/dev/null
        chmod -R a+rX "${DST_BASE_FALLBACK}"
        DST_BASE="${DST_BASE_FALLBACK}"
      fi
    fi
  else
    echo "[CITL] ERROR: packaging helper missing: ${PROJECT_ROOT}/package_binaries.sh"
    exit 1
  fi
fi

# --- begin inserted snippet: select appropriate factbook variant for target ---
echo "[CITL] Selecting factbook variant for target: ${TARGET}"
# installed common dir under DST_BASE
INST_COMMON_DIR="${DST_BASE}/common"

# If both variants were packaged, pick the appropriate one and place it as factbook.sh
if [[ -d "${INST_COMMON_DIR}" ]]; then
  if [[ "${TARGET}" == "desktop" ]]; then
    if [[ -f "${INST_COMMON_DIR}/factbook_windows.sh" ]]; then
      echo "[CITL] Installing Windows factbook variant"
      ${SUDO_CMD:+${SUDO_CMD}} mv -f "${INST_COMMON_DIR}/factbook_windows.sh" "${INST_COMMON_DIR}/factbook.sh" 2>/dev/null || mv -f "${INST_COMMON_DIR}/factbook_windows.sh" "${INST_COMMON_DIR}/factbook.sh"
    fi
  else
    if [[ -f "${INST_COMMON_DIR}/factbook_cannakit.sh" ]]; then
      echo "[CITL] Installing Cannakit factbook variant"
      ${SUDO_CMD:+${SUDO_CMD}} mv -f "${INST_COMMON_DIR}/factbook_cannakit.sh" "${INST_COMMON_DIR}/factbook.sh" 2>/dev/null || mv -f "${INST_COMMON_DIR}/factbook_cannakit.sh" "${INST_COMMON_DIR}/factbook.sh"
    fi
  fi

  # Make sure factbook is executable and readable
  if [[ -f "${INST_COMMON_DIR}/factbook.sh" ]]; then
    ${SUDO_CMD:+${SUDO_CMD}} chmod a+rX "${INST_COMMON_DIR}/factbook.sh" 2>/dev/null || chmod a+rX "${INST_COMMON_DIR}/factbook.sh"
  else
    echo "[CITL] WARNING: No factbook variant found in ${INST_COMMON_DIR}"
  fi

  # Optional cleanup: remove the other variant if present
  if [[ "${TARGET}" == "desktop" ]]; then
    ${SUDO_CMD:+${SUDO_CMD}} rm -f "${INST_COMMON_DIR}/factbook_cannakit.sh" 2>/dev/null || true
  else
    ${SUDO_CMD:+${SUDO_CMD}} rm -f "${INST_COMMON_DIR}/factbook_windows.sh" 2>/dev/null || true
  fi
fi
# --- end inserted snippet ---

# Ensure wrapper targets point to installed location under DST_BASE
BIN_DIR_UNIX="/usr/local/bin"
BIN_DIR_WIN="${DST_BASE}/bin"   # Windows wrapper folder (Program Files or ProgramData)/bin

echo "[CITL] Creating CLI wrappers"

# Unix wrappers (existing behavior)
write_wrapper_unix() {
  local name="$1"
  local target_rel="$2"
  local dest="${BIN_DIR_UNIX}/citl-${name}"
  if [[ -w "${BIN_DIR_UNIX}" ]] || [[ "${SUDO_CMD}" == "" ]]; then
    tee "${dest}" >/dev/null <<EOF
#!/usr/bin/env bash
set -euo pipefail
DST_BASE="${DST_BASE}"
exec "\${DST_BASE}/${target_rel}" "\$@"
EOF
    if [[ "${SUDO_CMD}" != "" ]]; then
      ${SUDO_CMD} chmod +x "${dest}"
    else
      chmod +x "${dest}"
    fi
  else
    echo "[CITL] INFO: Unable to write ${dest} (insufficient permissions)."
  fi
}

write_wrapper_unix "factbook" "common/factbook.sh"
write_wrapper_unix "tts" "common/tts.sh"
write_wrapper_unix "stt" "common/speech_to_text.sh"

# Windows wrappers: .cmd (for cmd.exe) and .ps1 (for PowerShell)
if [[ "${TARGET}" == "desktop" ]]; then
  mkdir -p "${BIN_DIR_WIN}"
  # helper to write .cmd and .ps1 wrappers
  write_windows_wrappers() {
    local name="$1"
    local rel="$2"   # relative target under DST_BASE
    local cmd_path="${BIN_DIR_WIN}/citl-${name}.cmd"
    local ps1_path="${BIN_DIR_WIN}/citl-${name}.ps1"
    # .cmd wrapper: attempt to run native exe if present, else try bash (Git Bash)
    cat > "${cmd_path}" <<'EOF'
@echo off
REM Wrapper for citl-%NAME% (cmd)
SET DST_BASE=%~dp0\..
REM first try an .exe in DST_BASE\%REL%
IF EXIST "%DST_BASE%\%REL%.exe" (
  "%DST_BASE%\%REL%.exe" %*
  EXIT /B %ERRORLEVEL%
)
REM fallback: try bash if available (Git Bash)
where bash >nul 2>nul
IF %ERRORLEVEL%==0 (
  bash -lc "%DST_BASE%/%REL% %*"
  EXIT /B %ERRORLEVEL%
)
ECHO [CITL] No native executable or bash found to run citl-%NAME%
EXIT /B 1
EOF
    # replace placeholders
    sed -e "s|%NAME%|${name}|g" -e "s|%REL%|${rel}|g" "${cmd_path}" > "${cmd_path}.tmp" && mv "${cmd_path}.tmp" "${cmd_path}"
    # .ps1 wrapper: prefer native exe, else try to start bash or run PowerShell script to call sh
    cat > "${ps1_path}" <<'EOF'
# Wrapper for citl-%NAME% (PowerShell)
param([Parameter(ValueFromRemainingArguments=$true)]$args)
$dst = Split-Path -Parent $MyInvocation.MyCommand.Path
$targetExe = Join-Path (Join-Path $dst '..') '%REL%.exe'
if (Test-Path $targetExe) {
  & $targetExe @args
  exit $LASTEXITCODE
}
# Try bash if available
$bash = & where.exe bash 2>$null
if ($LASTEXITCODE -eq 0) {
  & bash -lc ('"' + (Join-Path (Join-Path $dst '..') '%REL%') + '" ' + ($args -join ' '))
  exit $LASTEXITCODE
}
Write-Host "[CITL] No native executable or bash found to run citl-%NAME%"
exit 1
EOF
    sed -e "s|%NAME%|${name}|g" -e "s|%REL%|${rel}|g" "${ps1_path}" > "${ps1_path}.tmp" && mv "${ps1_path}.tmp" "${ps1_path}"
    # no chmod on Windows paths; for Git Bash accessibility, also write a small shim to /usr/local/bin if writable
  }

  write_windows_wrappers "factbook" "common/factbook.sh"
  write_windows_wrappers "tts" "common/tts.sh"
  write_windows_wrappers "stt" "common/speech_to_text.sh"

  echo "[CITL] Windows wrappers written to ${BIN_DIR_WIN}. Add this folder to your PATH in PowerShell:"
  echo "  [Environment]::SetEnvironmentVariable('Path', \$env:Path + ';${BIN_DIR_WIN}', 'User')"
fi

echo "[CITL] Install complete. You can run: citl-factbook, citl-tts, citl-stt (unix) or citl-tts.ps1 / citl-tts.cmd on Windows"
