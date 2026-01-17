import os, re, shutil, subprocess, time
from pathlib import Path

def find_ffmpeg() -> str | None:
    env = os.environ.get("CITL_FFMPEG_PATH", "").strip()
    if env and Path(env).exists():
        return env
    bundled = Path(__file__).resolve().parent / "bin" / "ffmpeg.exe"
    if bundled.exists():
        return str(bundled)
    return shutil.which("ffmpeg")

def dshow_diagnostics(ffmpeg_path: str) -> str:
    p = subprocess.run(
        [ffmpeg_path, "-hide_banner", "-f", "dshow", "-list_devices", "true", "-i", "dummy"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace"
    )
    return p.stdout or ""

def list_dshow_audio_devices(ffmpeg_path: str) -> list[str]:
    """
    Returns BOTH friendly names and @device_cm alternative names.
    """
    out = dshow_diagnostics(ffmpeg_path)
    lines = out.splitlines()
    devs = []
    in_audio = False
    last_friendly = None

    for line in lines:
        if re.search(r"DirectShow audio devices", line, re.IGNORECASE):
            in_audio = True
            continue
        if re.search(r"DirectShow video devices", line, re.IGNORECASE):
            break

        if not in_audio:
            continue

        # Friendly name line: [dshow]  "Microphone (Yeti...)"
        m = re.search(r'"([^"]+)"', line)
        if m and "Alternative name" not in line:
            last_friendly = m.group(1).strip()
            if last_friendly and last_friendly not in devs:
                devs.append(last_friendly)
            continue

        # Alternative name line: Alternative name "@device_cm_...\wave_{...}"
        if "Alternative name" in line:
            m2 = re.search(r'"([^"]+)"', line)
            if m2:
                alt = m2.group(1).strip()
                if alt and alt not in devs:
                    devs.append(alt)

    return devs

def _normalize_dshow_input(device_name: str) -> str:
    """
    KEY FIX: Do NOT embed quotes inside the argument when using subprocess(list).
    Accepts:
      - Friendly name: Microphone (Yeti Stereo Microphone)
      - Alternative name: @device_cm_...\wave_{...}
      - Full spec: audio=...
    """
    s = (device_name or "").strip()

    # If user already typed full spec
    if s.lower().startswith("audio="):
        return s

    # If they pasted the @device alternative
    if s.startswith("@"):
        return "audio=" + s

    # Normal friendly name
    return "audio=" + s

def start_recording(ffmpeg_path: str, device_name: str, out_wav: str, samplerate: int = 16000) -> subprocess.Popen:
    dshow_in = _normalize_dshow_input(device_name)

    cmd = [
        ffmpeg_path,
        "-y",
        "-hide_banner",
        "-loglevel", "info",
        "-f", "dshow",
        "-i", dshow_in,
        "-ac", "1",
        "-ar", str(int(samplerate)),
        "-acodec", "pcm_s16le",
        out_wav,
    ]

    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,                  # send 'q' for graceful finalize
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace",
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
    )

    # Detect immediate exit and show output
    time.sleep(0.35)
    if proc.poll() is not None:
        try:
            out = proc.communicate(timeout=1)[0] or ""
        except Exception:
            out = ""
        raise RuntimeError("FFmpeg exited immediately. Output:\n\n" + (out or "(no output)"))

    return proc

def stop_recording(proc: subprocess.Popen, wait_sec: float = 6.0) -> str:
    if proc is None:
        return ""

    # Graceful stop (finalizes WAV header)
    try:
        if proc.stdin:
            proc.stdin.write("q\n")
            proc.stdin.flush()
    except Exception:
        pass

    t0 = time.time()
    out = ""
    while time.time() - t0 < wait_sec:
        if proc.poll() is not None:
            try:
                out = proc.communicate(timeout=1)[0] or ""
            except Exception:
                out = ""
            return out
        time.sleep(0.1)

    # Fallback
    try:
        proc.terminate()
        out = proc.communicate(timeout=2)[0] or ""
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass
    return out or ""
