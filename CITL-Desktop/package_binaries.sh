#!/usr/bin/env bash
set -euo pipefail

# Create common/bin and populate with shims or download URLs if provided.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUT_DIR="${ROOT}/common"
BIN_DIR="${OUT_DIR}/bin"
mkdir -p "${BIN_DIR}"

download_if_set() {
  local url="$1"; local dest="$2"
  if [[ -n "${url:-}" ]]; then
    echo "[CITL] Downloading ${url} -> ${dest}"
    if command -v curl >/dev/null 2>&1; then
      curl -L --fail -o "${dest}" "${url}"
    elif command -v wget >/dev/null 2>&1; then
      wget -O "${dest}" "${url}"
    else
      echo "[CITL] No downloader (curl/wget). Skipping ${url}"
      return 1
    fi
    chmod +x "${dest}" || true
    return 0
  fi
  return 1
}

# Try downloading if env vars are set (user can set these to real binaries)
download_if_set "${TTS_GPU_URL:-}" "${BIN_DIR}/tts_cuda" || true
download_if_set "${TTS_CPU_URL:-}" "${BIN_DIR}/tts_cpu" || true
download_if_set "${STT_GPU_URL:-}" "${BIN_DIR}/stt_cuda" || true
download_if_set "${STT_CPU_URL:-}" "${BIN_DIR}/stt_cpu" || true

# If any binary missing, create small shim that calls Python backends if available.
create_python_tts_shim() {
  local path="$1"
  cat > "${path}" <<'EOF'
#!/usr/bin/env bash
# Minimal TTS shim: tries common Python TTS packages (Coqui TTS / TTS) in this order.
TEXT=""
OUT=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --text) TEXT="$2"; shift 2;;
    --out) OUT="$2"; shift 2;;
    *) if [[ -z "$TEXT" ]]; then TEXT="$1"; else OUT="$1"; fi; shift;;
  esac
done
if [[ -z "${TEXT}" ]]; then
  echo "Usage: tts_cpu \"Text to speak\" [out.wav] or --text/--out"
  exit 2
fi
python3 - <<PY
import sys, subprocess
text = "${TEXT}"
out = "${OUT}" or None
try:
    # Try Coqui TTS (TTS)
    from TTS.api import TTS
    tts = TTS(list_models()[0])
    if out:
        tts.tts_to_file(text=text, file_path=out)
    else:
        wav = tts.tts(text)
        # write to stdout raw? print info
        print("[CITL] TTS generated; save to file using --out")
        sys.exit(0)
except Exception as e:
    print("[CITL] TTS Python backend not available or failed:", e)
    print("Install Coqui TTS (pip install TTS) or provide native binaries.")
    sys.exit(1)
PY
EOF
  chmod +x "${path}"
}

create_python_stt_shim() {
  local path="$1"
  cat > "${path}" <<'EOF'
#!/usr/bin/env bash
# Minimal STT shim: try Vosk; writes transcript to stdout
INFILE="$1"
if [[ -z "${INFILE}" ]]; then
  echo "Usage: stt_cpu <audio.wav>"
  exit 2
fi
python3 - <<PY
import sys
infile = sys.argv[1]
try:
    from vosk import Model, KaldiRecognizer
    import wave, json
    wf = wave.open(infile, "rb")
    model = Model(lang="en-us")
    rec = KaldiRecognizer(model, wf.getframerate())
    res = []
    while True:
        data = wf.readframes(4000)
        if len(data) == 0:
            break
        if rec.AcceptWaveform(data):
            res.append(rec.Result())
    res.append(rec.FinalResult())
    print("\n".join(res))
except Exception as e:
    print("[CITL] Vosk STT backend not available or failed:", e)
    print("Install vosk (pip install vosk) and a model, or provide native binaries.")
    sys.exit(1)
PY
EOF
  chmod +x "${path}"
}

# create missing shims
[[ -x "${BIN_DIR}/tts_cpu" ]] || create_python_tts_shim "${BIN_DIR}/tts_cpu"
[[ -x "${BIN_DIR}/tts_cuda" ]] || create_python_tts_shim "${BIN_DIR}/tts_cuda"
[[ -x "${BIN_DIR}/stt_cpu" ]] || create_python_stt_shim "${BIN_DIR}/stt_cpu"
[[ -x "${BIN_DIR}/stt_cuda" ]] || create_python_stt_shim "${BIN_DIR}/stt_cuda"

# Also ensure factbook script placeholder exists
if [[ ! -f "${OUT_DIR}/common/factbook.sh" ]]; then
  mkdir -p "${OUT_DIR}/common"
  cat > "${OUT_DIR}/common/factbook.sh" <<'EOF'
#!/usr/bin/env bash
echo '{"sample_fact":"This is a packaged Factbook placeholder. Replace with your data at common/resources/factbook.json"}'
EOF
  chmod +x "${OUT_DIR}/common/factbook.sh"
fi

# Create zip archive for installer consumption
cd "${OUT_DIR}"
zip -r -q "${ROOT}/common-binaries.zip" . || true
echo "[CITL] Packaged common-binaries.zip created at ${ROOT}/common-binaries.zip"