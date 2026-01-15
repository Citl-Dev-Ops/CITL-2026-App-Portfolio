import os
import re
import shutil
import subprocess
from pathlib import Path

def find_ffmpeg() -> str | None:
    env = os.environ.get("CITL_FFMPEG_PATH", "").strip()
    if env and Path(env).exists():
        return env

    here = Path(__file__).resolve().parent
    bundled = here / "bin" / "ffmpeg.exe"
    if bundled.exists():
        return str(bundled)

    exe = shutil.which("ffmpeg")
    return exe

def _run_ffmpeg_text(ffmpeg_path: str, args: list[str]) -> str:
    p = subprocess.run(
        [ffmpeg_path] + args,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return p.stdout or ""

def dshow_diagnostics(ffmpeg_path: str) -> str:
    return _run_ffmpeg_text(ffmpeg_path, ["-hide_banner", "-f", "dshow", "-list_devices", "true", "-i", "dummy"])

def supports_dshow(ffmpeg_path: str) -> bool:
    out = dshow_diagnostics(ffmpeg_path)
    bad = [
        "Unknown input format: 'dshow'",
        "Requested input format 'dshow' is not known",
        "not recognized as an internal or external command",
    ]
    return not any(b in out for b in bad)

def list_dshow_audio_devices(ffmpeg_path: str) -> list[str]:
    out = dshow_diagnostics(ffmpeg_path)

    # If dshow isn't supported, return empty; GUI will show the raw diagnostics.
    if ("Unknown input format" in out) and ("dshow" in out):
        return []

    lines = out.splitlines()

    # Try to parse the official "DirectShow audio devices" section
    devices = []
    in_audio = False
    for line in lines:
        if re.search(r"DirectShow audio devices", line, re.IGNORECASE):
            in_audio = True
            continue
        if re.search(r"DirectShow video devices", line, re.IGNORECASE):
            in_audio = False
            break
        if in_audio:
            m = re.search(r'"([^"]+)"', line)
            if m:
                name = m.group(1).strip()
                # skip alt/internal names
                if name.startswith("@"):
                    continue
                if name and name not in devices:
                    devices.append(name)

    # Fallback: sometimes FFmpeg prints quoted device lines but section markers differ
    if not devices:
        for line in lines:
            # avoid "Alternative name"
            if "Alternative name" in line:
                continue
            m = re.search(r'"([^"]+)"', line)
            if m:
                name = m.group(1).strip()
                if name.startswith("@"):
                    continue
                # heuristic: only keep mic-ish names
                if any(k in name.lower() for k in ["mic", "microphone", "yeti", "blue"]):
                    if name not in devices:
                        devices.append(name)

    return devices

def start_recording(ffmpeg_path: str, device_name: str, out_wav: str, samplerate: int = 16000) -> subprocess.Popen:
    # device_name is a DirectShow audio device string.
    cmd = [
        ffmpeg_path,
        "-y",
        "-hide_banner",
        "-loglevel", "error",
        "-f", "dshow",
        "-i", f"audio={device_name}",
        "-ac", "1",
        "-ar", str(int(samplerate)),
        out_wav,
    ]
    return subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

def stop_recording(proc: subprocess.Popen):
    if proc is None:
        return
    try:
        proc.terminate()
        proc.wait(timeout=3)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass
