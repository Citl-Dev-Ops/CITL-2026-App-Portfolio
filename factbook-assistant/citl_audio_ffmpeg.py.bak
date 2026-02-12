import re
import subprocess
import time
from pathlib import Path
# Robust regex for FFmpeg DirectShow listings
_DEVICE_RE = re.compile(r'^\s*\[dshow[^\]]*\]\s*"(.+?)"\s*\(audio\)\s*$', re.IGNORECASE)
_ALT_RE    = re.compile(r'^\s*\[dshow[^\]]*\]\s*Alternative name\s*"(.+?)"\s*$', re.IGNORECASE)
def _run_ffmpeg_list(ffmpeg_path: str) -> str:
    """
    Runs: ffmpeg -f dshow -list_devices true -i dummy
    Note: ffmpeg exits with error because 'dummy' is not a real input.
    We still want the printed device list (stderr).
    """
    cmd = [
        ffmpeg_path,
        "-hide_banner",
        "-f", "dshow",
        "-list_devices", "true",
        "-i", "dummy",
    ]
    p = subprocess.run(cmd, capture_output=True, text=True)
    # device listing is emitted on stderr; stdout often empty
    return (p.stderr or "") + ("\n" + p.stdout if p.stdout else "")
def list_dshow_audio_devices(ffmpeg_path: str) -> list[str]:
    """
    Returns friendly audio device names like:
      Line In (BEHRINGER USB WDM AUDIO 2.8.40)
      Line In (Realtek(R) Audio)
    """
    out = _run_ffmpeg_list(ffmpeg_path)
    devs: list[str] = []
    for line in out.splitlines():
        m = _DEVICE_RE.match(line)
        if m:
            name = m.group(1).strip()
            if name and name.lower() != "none":
                devs.append(name)
    # de-dupe while preserving order
    seen = set()
    uniq = []
    for d in devs:
        if d not in seen:
            seen.add(d)
            uniq.append(d)
    return uniq
def list_dshow_audio_devices_with_alts(ffmpeg_path: str) -> list[tuple[str, str | None]]:
    """
    Returns list of (friendly_name, alternative_name).
    Alternative names are more stable across systems.
    """
    out = _run_ffmpeg_list(ffmpeg_path)
    pairs: list[tuple[str, str | None]] = []
    last_dev = None
    for line in out.splitlines():
        m = _DEVICE_RE.match(line)
        if m:
            last_dev = m.group(1).strip()
            if last_dev and last_dev.lower() != "none":
                pairs.append((last_dev, None))
            continue
        m2 = _ALT_RE.match(line)
        if m2 and last_dev and pairs:
            alt = m2.group(1).strip()
            # attach to most recent device
            if pairs[-1][0] == last_dev:
                pairs[-1] = (pairs[-1][0], alt)
    # de-dupe by friendly name
    seen = set()
    uniq = []
    for p in pairs:
        if p[0] not in seen:
            seen.add(p[0])
            uniq.append(p)
    return uniq
def _normalize_audio_selector(device_name: str) -> str:
    """
    Converts a dropdown choice into an ffmpeg dshow input selector.
      "Line In (...)" -> "audio=Line In (...)"
      "@device_cm_..." -> 'audio=@device_cm_...'
      "audio=Something" -> "audio=Something"
    """
    d = (device_name or "").strip()
    if not d:
        return ""
    if d.lower().startswith("audio="):
        return d
    return "audio=" + d
def resolve_audio_device(ffmpeg_path: str, requested: str) -> str:
    """
    If requested device isn't present, fallback to first available.
    Returns the actual 'audio=...' string used for ffmpeg.
    """
    devs = list_dshow_audio_devices(ffmpeg_path)
    if not devs:
        return _normalize_audio_selector(requested)
    req = (requested or "").strip()
    # if requested matches friendly list, use it
    if req in devs:
        return _normalize_audio_selector(req)
    # if requested looks like an alt name, allow it
    if req.startswith("@device_") or req.startswith(r"@device_cm_") or req.startswith(r"@device_sw_"):
        return _normalize_audio_selector(req)
    # fallback to first audio device
    return _normalize_audio_selector(devs[0])
def start_recording(ffmpeg_path: str, device_name: str, out_wav: str, samplerate: int = 16000, channels: int = 1):
    """
    Starts ffmpeg recording process. Returns Popen handle.
    """
    out_path = Path(out_wav)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    audio_sel = resolve_audio_device(ffmpeg_path, device_name)
    cmd = [
        ffmpeg_path,
        "-y",
        "-hide_banner",
        "-loglevel", "error",
        "-f", "dshow",
        "-i", audio_sel,
        "-ac", str(int(channels)),
        "-ar", str(int(samplerate)),
        "-acodec", "pcm_s16le",
        str(out_path),
    ]
    # CREATE_NO_WINDOW avoids flashing console on Windows
    CREATE_NO_WINDOW = 0x08000000
    p = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        creationflags=CREATE_NO_WINDOW,
    )
    return p
def stop_recording(proc, timeout: float = 3.0):
    """
    Gracefully stops ffmpeg by sending 'q'. Falls back to terminate.
    """
    if proc is None:
        return
    try:
        if proc.stdin:
            proc.stdin.write("q\n")
            proc.stdin.flush()
    except Exception:
        pass
    t0 = time.time()
    while time.time() - t0 < timeout:
        if proc.poll() is not None:
            return
        time.sleep(0.05)
    try:
        proc.terminate()
    except Exception:
        pass
