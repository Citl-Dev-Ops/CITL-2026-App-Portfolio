"""
citl_audio_devices.py — Cross-platform audio input enumeration.

Device dict schema:
    {
        "id":         str,   # stable identifier (dshow alt-name, pulse source, "sd:N")
        "name":       str,   # human-readable display name
        "is_default": bool,
        "backend":    str,   # "ffmpeg_dshow" | "pulse" | "alsa" | "sounddevice"
    }

Usage:
    from citl_audio_devices import list_audio_inputs, get_default_input
    devices = list_audio_inputs()          # -> list[dict]
    default = get_default_input()          # -> dict | None
"""

import os
import re
import sys
from typing import Optional

# ---------------------------------------------------------------------------
# Platform capability probes
# ---------------------------------------------------------------------------

def supports_dshow() -> bool:
    """True when running on Windows and ffmpeg is available."""
    if os.name != "nt":
        return False
    return _find_ffmpeg() is not None

def supports_pulse() -> bool:
    import shutil
    return os.name != "nt" and shutil.which("pactl") is not None

def supports_alsa() -> bool:
    import shutil
    return os.name != "nt" and shutil.which("arecord") is not None

def _find_ffmpeg(ffmpeg_path: Optional[str] = None) -> Optional[str]:
    if ffmpeg_path:
        return ffmpeg_path
    env = os.environ.get("CITL_FFMPEG_PATH", "").strip()
    if env:
        return env
    from pathlib import Path
    bundled = Path(__file__).resolve().parent / "bin" / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg")
    if bundled.exists():
        return str(bundled)
    import shutil
    return shutil.which("ffmpeg")

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def list_audio_inputs(ffmpeg_path: Optional[str] = None) -> list:
    """Return list of input device dicts, best-available backend first."""
    if os.name == "nt":
        ff = _find_ffmpeg(ffmpeg_path)
        if ff:
            devs = _list_dshow(ff)
            if devs:
                return devs
        # Windows fallback: sounddevice
        return _list_sounddevice()

    # Linux / macOS
    if supports_pulse():
        devs = _list_pulse()
        if devs:
            return devs
    if supports_alsa():
        devs = _list_alsa()
        if devs:
            return devs
    return _list_sounddevice()


def get_default_input(ffmpeg_path: Optional[str] = None) -> Optional[dict]:
    devs = list_audio_inputs(ffmpeg_path)
    for d in devs:
        if d.get("is_default"):
            return d
    return devs[0] if devs else None

# ---------------------------------------------------------------------------
# Windows — DirectShow via ffmpeg
# ---------------------------------------------------------------------------

_DSHOW_DEV_RE  = re.compile(r'^\s*\[dshow[^\]]*\]\s*"(.+?)"\s*\(audio\)\s*$', re.IGNORECASE)
_DSHOW_ALT_RE  = re.compile(r'^\s*\[dshow[^\]]*\]\s*Alternative name\s*"(.+?)"\s*$', re.IGNORECASE)

def _list_dshow(ffmpeg: str) -> list:
    import subprocess
    try:
        p = subprocess.run(
            [ffmpeg, "-hide_banner", "-f", "dshow", "-list_devices", "true", "-i", "dummy"],
            capture_output=True, text=True, timeout=20, errors="replace",
        )
        raw = (p.stderr or "") + "\n" + (p.stdout or "")
    except Exception:
        return []

    devices = []
    last_name = None
    for line in raw.splitlines():
        m = _DSHOW_DEV_RE.match(line)
        if m:
            last_name = m.group(1).strip()
            continue
        m = _DSHOW_ALT_RE.match(line)
        if m and last_name:
            alt = m.group(1).strip()
            devices.append({
                "id":         alt,
                "name":       last_name,
                "is_default": False,
                "backend":    "ffmpeg_dshow",
            })
            last_name = None

    if devices:
        devices[0]["is_default"] = True
    return devices

# ---------------------------------------------------------------------------
# Linux — PulseAudio
# ---------------------------------------------------------------------------

def _list_pulse() -> list:
    import subprocess

    # Get default source name
    default_src = None
    try:
        r = subprocess.run(["pactl", "info"], capture_output=True, text=True, timeout=5)
        for ln in r.stdout.splitlines():
            if ln.strip().startswith("Default Source:"):
                default_src = ln.split(":", 1)[1].strip()
                break
    except Exception:
        pass

    try:
        r = subprocess.run(
            ["pactl", "list", "sources", "short"],
            capture_output=True, text=True, timeout=10,
        )
    except Exception:
        return []

    devices = []
    for line in r.stdout.splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        src_name = parts[1]
        if src_name.endswith(".monitor"):
            continue  # skip loopback monitors
        devices.append({
            "id":         src_name,
            "name":       src_name,
            "is_default": src_name == default_src,
            "backend":    "pulse",
        })
    return devices

# ---------------------------------------------------------------------------
# Linux — ALSA (arecord -l)
# ---------------------------------------------------------------------------

_ALSA_RE = re.compile(r'^card\s+(\d+):\s+(.+?),\s+device\s+(\d+):\s+(.+)', re.IGNORECASE)

def _list_alsa() -> list:
    import subprocess
    try:
        r = subprocess.run(["arecord", "-l"], capture_output=True, text=True, timeout=10)
        raw = r.stdout + r.stderr
    except Exception:
        return []

    devices = []
    for line in raw.splitlines():
        m = _ALSA_RE.match(line)
        if not m:
            continue
        card_n, card_name, dev_n, dev_name = m.groups()
        hw_id = f"hw:{card_n},{dev_n}"
        display = f"{card_name.strip()} / {dev_name.strip()}"
        devices.append({
            "id":         hw_id,
            "name":       display,
            "is_default": False,
            "backend":    "alsa",
        })
    if devices:
        devices[0]["is_default"] = True
    return devices

# ---------------------------------------------------------------------------
# Cross-platform — sounddevice fallback
# ---------------------------------------------------------------------------

def _list_sounddevice() -> list:
    try:
        import sounddevice as sd  # type: ignore
    except Exception:
        return []

    try:
        devs = sd.query_devices()
        default_in = None
        try:
            default_in = sd.default.device[0]
        except Exception:
            pass

        result = []
        for i, d in enumerate(devs):
            if int(d.get("max_input_channels", 0)) <= 0:
                continue
            name = str(d.get("name", "")).strip()
            if not name:
                continue
            result.append({
                "id":         f"sd:{i}",
                "name":       name,
                "is_default": i == default_in,
                "backend":    "sounddevice",
            })
        return result
    except Exception:
        return []
