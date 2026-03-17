import os
import re
import time
import shutil
import wave
import queue
import threading
from pathlib import Path
from typing import List, Optional, Tuple

# ---------------------------
# FFmpeg discovery (kept for diagnostics)
# ---------------------------
def find_ffmpeg() -> Optional[str]:
    here = Path(__file__).resolve().parent
    bundled = here / "bin" / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg")
    if bundled.exists():
        return str(bundled)
    p = shutil.which("ffmpeg")
    return p if p else None

# ---------------------------
# Windows device listing (human-friendly)
# ---------------------------
_SD_TAG = re.compile(r"\[Device\s+(\d+)\]\s*$", re.I)

def _try_sounddevice_list() -> Tuple[List[str], str]:
    """
    Returns (labels, diagnostics_text).
    Labels are human-readable and device-agnostic:
      '<device name> [Device <index>]'
    """
    try:
        import sounddevice as sd  # type: ignore
    except Exception as e:
        return [], f"sounddevice import failed: {e}"

    try:
        devs = sd.query_devices()
        default_in = None
        try:
            default_in = sd.default.device[0]
        except Exception:
            default_in = None

        labels: List[str] = []
        for i, d in enumerate(devs):
            try:
                if int(d.get("max_input_channels", 0)) <= 0:
                    continue
                name = str(d.get("name", "")).strip()
                if not name:
                    continue
                labels.append(f"{name} [Device {i}]")
            except Exception:
                continue

        diag_lines = []
        diag_lines.append(f"Audio devices detected: {len(labels)} input(s)")
        diag_lines.append(f"Default input index: {default_in}")
        # Show a short list
        for lab in labels[:60]:
            diag_lines.append(f"  - {lab}")
        return labels, "\n".join(diag_lines)

    except Exception as e:
        return [], f"sounddevice query failed: {e}"

def list_audio_devices(ffmpeg: Optional[str] = None) -> List[str]:
    """
    Primary: sounddevice (Windows) -> auto-populated list of input devices.
    Fallback: empty list (GUI still allows manual typing if needed).
    """
    labels, _diag = _try_sounddevice_list()
    return labels

# ---------------------------
# FFmpeg DirectShow diagnostics (optional)
# ---------------------------
_DSHOW_PREFIX = re.compile(r'^\s*\[dshow @ [0-9A-Fa-f]+\]\s*')

def _run_ffmpeg_text(ffmpeg: str, args: List[str], timeout: int = 20) -> Tuple[int, str]:
    import subprocess
    p = subprocess.run(
        [ffmpeg] + args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        errors="replace",
        timeout=timeout,
        check=False,
    )
    txt = (p.stdout or "") + "\n" + (p.stderr or "")
    return p.returncode, txt

def dshow_diagnostics(ffmpeg: Optional[str]) -> str:
    if not ffmpeg:
        return "FFmpeg not found."
    code, txt = _run_ffmpeg_text(
        ffmpeg,
        ["-hide_banner", "-list_devices", "true", "-f", "dshow", "-i", "dummy"],
        timeout=20,
    )
    lines = []
    lines.append("=== FFmpeg DirectShow Diagnostics ===")
    lines.append(f"FFmpeg: {ffmpeg}")
    lines.append(f"Exit code: {code} (non-zero is NORMAL for listing)")
    lines.append("")
    lines.append("---- Raw output (truncated) ----")
    raw = txt.splitlines()
    for ln in raw[:220]:
        lines.append(ln[:300])
    if len(raw) > 220:
        lines.append("... (truncated) ...")
    return "\n".join(lines)

# ---------------------------
# Recording via sounddevice (NO FFmpeg needed)
# ---------------------------
class _SDRec:
    def __init__(self, stream, wf, q: "queue.Queue[bytes]", t: threading.Thread, samplerate: int, channels: int):
        self.kind = "sounddevice"
        self.stream = stream
        self.wf = wf
        self.q = q
        self.t = t
        self.samplerate = int(samplerate)
        self.channels = int(channels)

def _parse_sd_index(label: str) -> Optional[int]:
    m = _SD_TAG.search((label or "").strip())
    if not m:
        return None
    try:
        return int(m.group(1))
    except Exception:
        return None

def _build_rate_candidates(requested: int, default_sr: Optional[float]) -> List[int]:
    out: List[int] = []

    def add(x) -> None:
        try:
            r = int(float(x))
        except Exception:
            return
        if r > 0 and r not in out:
            out.append(r)

    add(requested)
    add(default_sr)
    for r in (48000, 44100, 32000, 24000, 22050, 16000, 11025, 8000):
        add(r)
    return out

def _open_compatible_input_stream(sd, device_index: int, requested_sr: int, callback):
    """
    Open a RawInputStream using a compatible (samplerate, channels) pair.
    Returns: (stream, chosen_samplerate, chosen_channels, attempts)
    """
    info = sd.query_devices(device_index, "input")
    max_in = int(info.get("max_input_channels", 0) or 0)
    if max_in <= 0:
        raise RuntimeError("Selected device has no input channels.")

    default_sr = info.get("default_samplerate")
    rates = _build_rate_candidates(requested_sr, default_sr)
    channel_candidates: List[int] = [1]
    if max_in >= 2:
        channel_candidates.append(2)

    attempts: List[str] = []
    last_err: Optional[Exception] = None

    for ch in channel_candidates:
        for rate in rates:
            try:
                sd.check_input_settings(device=device_index, samplerate=rate, channels=ch, dtype="int16")
                stream = sd.RawInputStream(
                    device=device_index,
                    samplerate=rate,
                    channels=ch,
                    dtype="int16",
                    callback=callback,
                    blocksize=0,
                )
                return stream, int(rate), int(ch), attempts
            except Exception as e:
                attempts.append(f"{rate}Hz/{ch}ch -> {e}")
                last_err = e
                continue

    msg = "No supported input format found."
    if attempts:
        msg += "\nTried:\n  - " + "\n  - ".join(attempts[:12])
    raise RuntimeError(msg) from last_err

def start_recording(ffmpeg: Optional[str], device_name: str, out_wav: str, samplerate: int = 16000):
    """
    Start recording from the selected device label '<name> [Device N]'.
    Writes PCM16 mono WAV at samplerate.
    Returns an opaque handle used by stop_recording().
    """
    device_name = (device_name or "").strip()
    if not device_name:
        raise RuntimeError("No device selected.")

    idx = _parse_sd_index(device_name)
    if idx is None:
        raise RuntimeError("Selected device label is invalid. Please Refresh Device List and select a device.")

    try:
        import sounddevice as sd  # type: ignore
    except Exception as e:
        raise RuntimeError(f"sounddevice is not available: {e}")

    out_path = Path(out_wav)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    q: "queue.Queue[bytes]" = queue.Queue()
    active_channels = 1

    def callback(indata, frames, time_info, status):
        if status:
            # keep going; status is often harmless (xruns)
            pass
        try:
            if active_channels == 1:
                q.put(bytes(indata))
            else:
                # Keep output WAV mono by taking the first channel.
                mono = indata[:, 0:1]
                q.put(mono.tobytes())
        except Exception:
            q.put(bytes(indata))

    try:
        stream, chosen_sr, chosen_ch, attempts = _open_compatible_input_stream(
            sd=sd,
            device_index=idx,
            requested_sr=int(samplerate),
            callback=callback,
        )
    except Exception as e:
        raise RuntimeError(f"Could not open selected input device.\n\n{e}")

    active_channels = int(chosen_ch)

    # Open WAV once the actual capture format has been negotiated.
    wf = wave.open(str(out_path), "wb")
    wf.setnchannels(1)
    wf.setsampwidth(2)  # int16
    wf.setframerate(int(chosen_sr))

    def writer():
        while True:
            b = q.get()
            if b is None:  # type: ignore[comparison-overlap]
                break
            wf.writeframes(b)
        wf.close()

    t = threading.Thread(target=writer, daemon=True)
    t.start()

    try:
        stream.start()
    except Exception as e:
        try:
            stream.close()
        except Exception:
            pass
        try:
            q.put(None)  # type: ignore[arg-type]
        except Exception:
            pass
        try:
            wf.close()
        except Exception:
            pass
        raise RuntimeError(f"Could not start recording on selected device.\n\n{e}")

    return _SDRec(stream, wf, q, t, samplerate=chosen_sr, channels=chosen_ch)

def stop_recording(handle) -> str:
    """
    Stops recording. Works with the _SDRec handle.
    Returns a short log string.
    """
    if handle is None:
        return ""
    if getattr(handle, "kind", "") != "sounddevice":
        return "(unknown handle type)"

    try:
        handle.stream.stop()
        handle.stream.close()
    except Exception:
        pass

    try:
        handle.q.put(None)  # type: ignore[arg-type]
    except Exception:
        pass

    try:
        handle.t.join(timeout=3)
    except Exception:
        pass

    return "Stopped (sounddevice)."
# ---------------------------
# Compatibility exports (GUI expects these names)
# ---------------------------

def audio_diagnostics(ffmpeg: Optional[str]) -> str:
    """Returns combined sounddevice + DirectShow diagnostics."""
    parts = []

    # sounddevice
    try:
        _, sd_text = _try_sounddevice_list()
        if sd_text:
            parts.append(sd_text)
    except Exception as e:
        parts.append(f"(sounddevice diagnostics failed: {e})")

    # DirectShow
    try:
        parts.append(dshow_diagnostics(ffmpeg))
    except Exception as e:
        parts.append(f"(DirectShow diagnostics failed: {e})")

    out = "\n\n".join([p for p in parts if p]).strip()
    return out or "(no diagnostics)"
