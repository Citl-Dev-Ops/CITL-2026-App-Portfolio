#!/usr/bin/env bash
set -euo pipefail

# Create common/bin and populate with shims or download URLs if provided.

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUT_DIR="${ROOT}/common"
BIN_DIR="${OUT_DIR}/bin"

mkdir -p "${BIN_DIR}"

download_if_set() {
  local url="$1"
  local dest="$2"
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

create_python_tts_shim() {
  local path="$1"
  cat > "${path}" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

# Minimal TTS shim: tries common Python TTS packages (Coqui TTS).

TEXT=""
OUT=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --text) TEXT="$2"; shift 2;;
    --out)  OUT="$2";  shift 2;;
    *)
      if [[ -z "${TEXT}" ]]; then
        TEXT="$1"
      elif [[ -z "${OUT}" ]]; then
        OUT="$1"
      fi
      shift
      ;;
  esac
done

if [[ -z "${TEXT}" ]]; then
  echo "Usage: $(basename "$0") \"Text to speak\" [out.wav] or --text/--out"
  exit 2
fi

CITL_TTS_TEXT="${TEXT}" CITL_TTS_OUT="${OUT}" python3 - <<'PY'
import os, sys
text = os.environ.get("CITL_TTS_TEXT", "")
out = os.environ.get("CITL_TTS_OUT") or None

if not text:
    print("[CITL] No text provided to TTS shim.")
    sys.exit(2)

try:
    from TTS.api import TTS
except Exception as e:
    print("[CITL] TTS Python backend not available.")
    print("  Install Coqui TTS:  pip install TTS")
    print("  Also install a compatible PyTorch for your CPU/GPU.")
    print("  Original error:", e)
    sys.exit(1)

try:
    # Pick first available model
    model_name = TTS.list_models()[0]
    tts = TTS(model_name)
    if out:
        tts.tts_to_file(text=text, file_path=out)
        print(f"[CITL] Wrote speech to: {out}")
    else:
        print("[CITL] TTS synthesis complete. Re-run with --out <file.wav> to save audio.")
    sys.exit(0)
except Exception as e:
    print("[CITL] TTS synthesis failed:", e)
    sys.exit(1)
PY
EOF
  chmod +x "${path}"
}

create_python_stt_shim() {
  local path="$1"
  cat > "${path}" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

# Minimal STT shim: try Vosk; writes transcript to stdout.

INFILE="${1:-}"

if [[ -z "${INFILE}" ]]; then
  echo "Usage: $(basename "$0") <audio.wav>"
  exit 2
fi

if [[ ! -f "${INFILE}" ]]; then
  echo "[CITL] Input file not found: ${INFILE}"
  exit 1
fi

CITL_STT_INFILE="${INFILE}" python3 - <<'PY'
import os, sys, json, wave

infile = os.environ.get("CITL_STT_INFILE")
if not infile:
    print("[CITL] No input file passed to STT shim.")
    sys.exit(2)

try:
    from vosk import Model, KaldiRecognizer
except Exception as e:
    print("[CITL] Vosk STT backend not available.")
    print("  Install vosk:  pip install vosk")
    print("  And download a model, or use Model(lang='en-us') with recent vosk.")
    print("  Original error:", e)
    sys.exit(1)

try:
    wf = wave.open(infile, "rb")
except Exception as e:
    print("[CITL] Could not open audio file:", e)
    sys.exit(1)

if wf.getnchannels() != 1 or wf.getsampwidth() != 2:
    print("[CITL] Expected mono 16-bit WAV. Convert with e.g.:")
    print("  ffmpeg -i input.ext -ac 1 -ar 16000 -sample_fmt s16 output.wav")
    sys.exit(1)

model = Model(lang="en-us")
rec = KaldiRecognizer(model, wf.getframerate())
rec_results = []

while True:
    data = wf.readframes(4000)
    if len(data) == 0:
        break
    if rec.AcceptWaveform(data):
        rec_results.append(json.loads(rec.Result())["text"])

final_json = json.loads(rec.FinalResult())
if final_json.get("text"):
    rec_results.append(final_json["text"])

transcript = " ".join(filter(None, rec_results)).strip()
print(transcript)
PY
EOF
  chmod +x "${path}"
}

# create missing shims
[[ -x "${BIN_DIR}/tts_cpu" ]] || create_python_tts_shim "${BIN_DIR}/tts_cpu"
[[ -x "${BIN_DIR}/tts_cuda" ]] || create_python_tts_shim "${BIN_DIR}/tts_cuda"
[[ -x "${BIN_DIR}/stt_cpu" ]] || create_python_stt_shim "${BIN_DIR}/stt_cpu"
[[ -x "${BIN_DIR}/stt_cuda" ]] || create_python_stt_shim "${BIN_DIR}/stt_cuda"

# --- High-level routing shims (GPU-preferring) ---

# common/tts.sh
cat > "${OUT_DIR}/tts.sh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="${SCRIPT_DIR}/bin"

# Allow override with an explicit backend path.
if [[ -n "${CITL_TTS_BACKEND:-}" ]]; then
  exec "${CITL_TTS_BACKEND}" "$@"
fi

# Default preference: GPU if present, else CPU; override with CITL_TTS_MODE=cpu
if [[ "${CITL_TTS_MODE:-}" == "cpu" ]]; then
  CANDIDATES=( "tts_cpu" )
else
  CANDIDATES=( "tts_cuda" "tts_cpu" )
fi

for exe in "${CANDIDATES[@]}"; do
  if [[ -x "${BIN_DIR}/${exe}" ]]; then
    if [[ "${exe}" == "tts_cuda" ]]; then
      export CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-0}"
    fi
    exec "${BIN_DIR}/${exe}" "$@"
  fi
done

echo "[CITL] No TTS backend found under: ${BIN_DIR}"
echo "[CITL] Expected tts_cpu or tts_cuda. If using Python, install Coqui TTS:"
echo "  pip install TTS"
exit 1
EOF
chmod +x "${OUT_DIR}/tts.sh"

# common/speech_to_text.sh
cat > "${OUT_DIR}/speech_to_text.sh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="${SCRIPT_DIR}/bin"

if [[ -n "${CITL_STT_BACKEND:-}" ]]; then
  exec "${CITL_STT_BACKEND}" "$@"
fi

if [[ "${CITL_STT_MODE:-}" == "cpu" ]]; then
  CANDIDATES=( "stt_cpu" )
else
  CANDIDATES=( "stt_cuda" "stt_cpu" )
fi

for exe in "${CANDIDATES[@]}"; do
  if [[ -x "${BIN_DIR}/${exe}" ]]; then
    if [[ "${exe}" == "stt_cuda" ]]; then
      export CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-0}"
    fi
    exec "${BIN_DIR}/${exe}" "$@"
  fi
done

echo "[CITL] No STT backend found under: ${BIN_DIR}"
echo "[CITL] Expected stt_cpu or stt_cuda. If using Python, install Vosk:"
echo "  pip install vosk"
echo "and install a compatible language model."
exit 1
EOF
chmod +x "${OUT_DIR}/speech_to_text.sh"

# Also ensure factbook script placeholder exists
if [[ ! -f "${OUT_DIR}/factbook.sh" ]]; then
  cat > "${OUT_DIR}/factbook.sh" <<'EOF'
#!/usr/bin/env bash
echo '{"sample_fact":"This is a packaged Factbook placeholder. Replace with your data at common/resources/factbook.json"}'
EOF
  chmod +x "${OUT_DIR}/factbook.sh"
fi

# Create zip archive for installer consumption
cd "${ROOT}"

if command -v zip >/dev/null 2>&1; then
  # Normal path: zip is available in this environment
  zip -r -q "${ROOT}/common-binaries.zip" common
else
  echo "[CITL] 'zip' command not found, using PowerShell Compress-Archive instead..."
  # Use Windows PowerShell to create the archive
  powershell.exe -NoLogo -NonInteractive -Command "Compress-Archive -Path 'common\*' -DestinationPath 'common-binaries.zip' -Force"
fi

echo "[CITL] Packaged common-binaries.zip created at ${ROOT}/common-binaries.zip"
