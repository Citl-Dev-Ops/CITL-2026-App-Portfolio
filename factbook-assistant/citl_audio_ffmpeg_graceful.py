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
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace"
    )
    return p.stdout or ""

def list_dshow_audio_devices(ffmpeg_path: str) -> list[str]:
    out = dshow_diagnostics(ffmpeg_path)
    lines = out.splitlines()
    devices = []
    in_audio = False
    for line in lines:
        if re.search(r"DirectShow audio devices", line, re.IGNORECASE):
            in_audio = True
            continue
        if re.search(r"DirectShow video devices", line, re.IGNORECASE):
            break
        if in_audio:
            if "Alternative name" in line:
                continue
            m = re.search(r'"([^"]+)"', line)
            if m:
                name = m.group(1).strip()
                if name and not name.startswith("@") and name not in devices:
                    devices.append(name)
    return devices

def start_recording(ffmpeg_path: str, device_name: str, out_wav: str, samplerate: int = 16000) -> subprocess.Popen:
    # Always quote device name for dshow
    dshow_in = f'audio="{device_name}"'

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

    # stdin=PIPE so we can send 'q' for a clean stop (finalizes WAV header)
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
    )

    # If FFmpeg exits immediately, show its output instead of pretending we recorded.
    time.sleep(0.35)
    if proc.poll() is not None:
        try:
            out = proc.communicate(timeout=1)[0]
        except Exception:
            out = ""
        raise RuntimeError("FFmpeg exited immediately. Output:\n\n" + (out or "(no output)"))

    return proc

def stop_recording(proc: subprocess.Popen, wait_sec: float = 6.0) -> str:
    if proc is None:
        return ""

    # Graceful stop
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
