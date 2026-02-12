# factbook_assistant_gui.py
# CITL Factbook + Audio Capture GUI (robust device selection, no torch import at startup)

import os
import sys
import json
import time
import queue
import wave
import shutil
import subprocess
from pathlib import Path
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, filedialog

# -------------------------
# Optional deps
# -------------------------
try:
    import numpy as np
except Exception:
    np = None

try:
    import sounddevice as sd
except Exception:
    sd = None


# -------------------------
# App Paths (portable + writable)
# -------------------------
IS_FROZEN = getattr(sys, "frozen", False)
APP_DIR = Path(sys.executable).resolve().parent if IS_FROZEN else Path(__file__).resolve().parent

def _is_writable_dir(p: Path) -> bool:
    try:
        p.mkdir(parents=True, exist_ok=True)
        t = p / ".__write_test__"
        t.write_text("ok", encoding="utf-8")
        t.unlink(missing_ok=True)
        return True
    except Exception:
        return False

def _pick_data_dir() -> Path:
    # Priority:
    # 1) CITL_DATA_DIR (explicit override)
    # 2) APP_DIR\data if writable
    # 3) %APPDATA%\CITL
    env = os.environ.get("CITL_DATA_DIR", "").strip()
    if env:
        p = Path(env).expanduser()
        if _is_writable_dir(p):
            return p

    p2 = APP_DIR / "data"
    if _is_writable_dir(p2):
        return p2

    appdata = os.environ.get("APPDATA", str(Path.home()))
    p3 = Path(appdata) / "CITL"
    p3.mkdir(parents=True, exist_ok=True)
    return p3

DATA_DIR = _pick_data_dir()
RECORD_DIR = DATA_DIR / "recordings"
RECORD_DIR.mkdir(parents=True, exist_ok=True)
CONFIG_PATH = DATA_DIR / "config.json"


# -------------------------
# Config
# -------------------------
def load_config() -> dict:
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}

def save_config(cfg: dict) -> None:
    try:
        CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    except Exception:
        pass


# -------------------------
# Factbook query wiring
# -------------------------
def _python_exe_for_subprocess() -> str:
    # Use current interpreter (venv) for subprocess calls
    return sys.executable

def _query_script_path() -> Path:
    # query_factbook.py sits next to this GUI in factbook-assistant
    return (Path(__file__).resolve().parent / "query_factbook.py")

def run_factbook_query(query: str, use_regex: bool, topk: int, maxctx: int) -> str:
    qs = _query_script_path()
    if not qs.exists():
        return f"ERROR: query_factbook.py not found at:\n{qs}"

    cmd = [_python_exe_for_subprocess(), str(qs)]
    if use_regex:
        cmd.append("--regex")
    # Some versions have -k / --topk. We'll send -k and --maxctx only.
    cmd += ["-k", str(int(topk)), "--maxctx", str(int(maxctx)), query]

    env = os.environ.copy()
    try:
        out = subprocess.check_output(cmd, stderr=subprocess.STDOUT, text=True, env=env)
        return out
    except subprocess.CalledProcessError as e:
        return e.output


# -------------------------
# Audio device logic (FIXES -9996)
# -------------------------
def list_input_devices():
    """Return list of (index, name, hostapi, max_in, default_sr)."""
    if sd is None:
        return []
    devs = sd.query_devices()
    out = []
    for i, d in enumerate(devs):
        if int(d.get("max_input_channels", 0)) > 0:
            out.append((i, d.get("name", ""), d.get("hostapi", ""), int(d.get("max_input_channels", 0)), float(d.get("default_samplerate", 48000))))
    return out

def format_device_row(row):
    i, name, hostapi, max_in, sr = row
    # display includes index at the front so we can parse it reliably
    return f"{i} - {name}"

def parse_device_index(display: str):
    if not display:
        return None
    head = display.split("-", 1)[0].strip()
    return int(head) if head.isdigit() else None

def pick_device_index_from_env():
    """PowerShell injection: $env:CITL_AUDIO_IN_DEVICE='7' or '5'."""
    env = os.environ.get("CITL_AUDIO_IN_DEVICE", "").strip()
    if env.isdigit():
        idx = int(env)
        try:
            d = sd.query_devices(idx)
            if int(d.get("max_input_channels", 0)) > 0:
                return idx
        except Exception:
            return None
    return None

def first_working_input_device(prefer_keywords=("frontmic", "microphone", "mic")):
    """Try to find a device that can actually open an InputStream."""
    if sd is None:
        return None, None, None

    candidates = list_input_devices()
    if not candidates:
        return None, None, None

    def score(row):
        name = (row[1] or "").lower()
        for j, k in enumerate(prefer_keywords):
            if k in name:
                return j
        return 999

    candidates.sort(key=score)

    common_rates = [48000, 44100, 16000]
    for (idx, name, hostapi, max_in, default_sr) in candidates:
        # safest
        channels = 1
        rates_to_try = [int(default_sr)] + [r for r in common_rates if r != int(default_sr)]
        for sr in rates_to_try:
            try:
                sd.check_input_settings(device=idx, channels=channels, samplerate=sr)
                s = sd.InputStream(device=idx, channels=channels, samplerate=sr, dtype="float32", blocksize=0)
                s.start()
                s.stop()
                s.close()
                return idx, sr, channels
            except Exception:
                continue

    return None, None, None

def open_input_stream(device_idx: int):
    """Open a stream robustly; NEVER pass -1."""
    if sd is None:
        raise RuntimeError("sounddevice not installed.")
    if device_idx is None or device_idx < 0:
        raise RuntimeError(f"Invalid input device index: {device_idx}")

    devinfo = sd.query_devices(device_idx, "input")
    default_sr = int(devinfo.get("default_samplerate", 48000))
    channels = 1

    # validate default samplerate; if it fails, try common rates
    for sr in [default_sr, 48000, 44100, 16000]:
        try:
            sd.check_input_settings(device=device_idx, channels=channels, samplerate=sr)
            stream = sd.InputStream(
                device=device_idx,
                samplerate=sr,
                channels=channels,
                dtype="float32",
                blocksize=0,
            )
            stream.start()
            return stream, sr, channels
        except Exception:
            continue

    raise RuntimeError(f"Could not open input stream on device {device_idx}. Try a different device.")


# -------------------------
# Recording engine
# -------------------------
class Recorder:
    def __init__(self):
        self.stream = None
        self.samplerate = None
        self.channels = None
        self.device_idx = None
        self.q = queue.Queue()
        self.frames = []
        self.recording = False
        self.last_saved_wav = None

    def _callback(self, indata, frames, time_info, status):
        if status:
            # don't crash on status; just note
            pass
        if self.recording:
            self.q.put(indata.copy())

    def start(self, device_idx: int):
        if sd is None or np is None:
            raise RuntimeError("Recording requires sounddevice + numpy installed.")

        if self.recording:
            return

        self.stream, self.samplerate, self.channels = open_input_stream(device_idx)
        self.device_idx = device_idx

        # replace callback stream (we opened without callback)
        # Stop existing stream and reopen with callback using same settings
        self.stream.stop()
        self.stream.close()

        self.stream = sd.InputStream(
            device=device_idx,
            samplerate=self.samplerate,
            channels=self.channels,
            dtype="float32",
            callback=self._callback,
            blocksize=0,
        )
        self.frames = []
        self.recording = True
        self.stream.start()

    def poll(self):
        """Drain queue into frames list."""
        while True:
            try:
                block = self.q.get_nowait()
                self.frames.append(block)
            except queue.Empty:
                break

    def stop_and_save(self, out_path: Path):
        if not self.recording:
            return None

        self.recording = False
        try:
            if self.stream:
                self.stream.stop()
                self.stream.close()
        finally:
            self.stream = None

        # drain any leftover
        self.poll()

        if not self.frames:
            raise RuntimeError("No audio captured. Try a different input device.")

        audio = np.concatenate(self.frames, axis=0)  # float32 [-1..1]
        # convert to int16
        audio_i16 = np.clip(audio, -1.0, 1.0)
        audio_i16 = (audio_i16 * 32767.0).astype(np.int16)

        out_path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(out_path), "wb") as wf:
            wf.setnchannels(self.channels)
            wf.setsampwidth(2)  # int16
            wf.setframerate(int(self.samplerate))
            wf.writeframes(audio_i16.tobytes())

        self.last_saved_wav = str(out_path)
        return str(out_path)


# -------------------------
# Transcription (English/Spanish/Auto) using faster-whisper (NO TORCH)
# -------------------------
def transcribe_wav(path: str, lang_mode: str) -> tuple[str, str]:
    """
    lang_mode: "Auto", "English", "Spanish"
    Returns: (detected_lang, text)
    """
    try:
        from faster_whisper import WhisperModel
    except Exception:
        raise RuntimeError("Transcription requires: pip install faster-whisper")

    # CPU-friendly; good enough for demos
    model = WhisperModel("small", device="cpu", compute_type="int8")

    if lang_mode == "English":
        language = "en"
    elif lang_mode == "Spanish":
        language = "es"
    else:
        language = None  # auto

    segments, info = model.transcribe(path, language=language)

    detected = getattr(info, "language", None) or (language or "unknown")

    # Clamp if Auto detects something else (optional policy)
    if lang_mode == "Auto" and detected not in ("en", "es"):
        # Force English as fallback (change to "es" if your campus is mostly Spanish)
        segments, info = model.transcribe(path, language="en")
        detected = "en"

    text = "".join([seg.text for seg in segments]).strip()
    return detected, text


# -------------------------
# GUI
# -------------------------
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("CITL Factbook Assistant (Audio + RAG)")
        self.geometry("1100x720")

        self.cfg = load_config()
        self.rec = Recorder()

        self._build_ui()
        self._init_devices()

        # periodic poll for audio buffers
        self.after(200, self._tick)

    def _build_ui(self):
        # Top split: Factbook left, Audio right
        outer = ttk.Frame(self, padding=8)
        outer.pack(fill="both", expand=True)

        paned = ttk.Panedwindow(outer, orient="horizontal")
        paned.pack(fill="both", expand=True)

        left = ttk.Frame(paned, padding=8)
        right = ttk.Frame(paned, padding=8)
        paned.add(left, weight=3)
        paned.add(right, weight=2)

        # ---------- Factbook panel ----------
        ttk.Label(left, text="Factbook Query", font=("Segoe UI", 12, "bold")).pack(anchor="w")

        qrow = ttk.Frame(left)
        qrow.pack(fill="x", pady=(6, 2))

        ttk.Label(qrow, text="Query:").pack(side="left")
        self.query_var = tk.StringVar(value="")
        self.query_entry = ttk.Entry(qrow, textvariable=self.query_var)
        self.query_entry.pack(side="left", fill="x", expand=True, padx=6)

        self.regex_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(qrow, text="Regex mode", variable=self.regex_var).pack(side="left")

        opts = ttk.Frame(left)
        opts.pack(fill="x", pady=(2, 6))

        ttk.Label(opts, text="TopK:").pack(side="left")
        self.topk_var = tk.IntVar(value=8)
        ttk.Spinbox(opts, from_=1, to=30, textvariable=self.topk_var, width=5).pack(side="left", padx=(4, 14))

        ttk.Label(opts, text="MaxCtx:").pack(side="left")
        self.maxctx_var = tk.IntVar(value=2400)
        ttk.Spinbox(opts, from_=500, to=12000, increment=100, textvariable=self.maxctx_var, width=7).pack(side="left", padx=(4, 14))

        run_btn = ttk.Button(opts, text="Run Query", command=self.on_run_query)
        run_btn.pack(side="left")

        self.factbook_out = scrolledtext.ScrolledText(left, height=22, wrap="word")
        self.factbook_out.pack(fill="both", expand=True, pady=(6, 6))

        # ---------- File loader panel ----------
        fpanel = ttk.LabelFrame(left, text="Load .txt documents (copy into data folder for parsing)", padding=8)
        fpanel.pack(fill="x", pady=(6, 0))

        ttk.Label(fpanel, text=f"Data folder: {DATA_DIR}").pack(anchor="w")
        btns = ttk.Frame(fpanel)
        btns.pack(fill="x", pady=(6, 0))
        ttk.Button(btns, text="Add Text Files…", command=self.on_add_text_files).pack(side="left")
        ttk.Button(btns, text="Open Data Folder", command=self.on_open_data_folder).pack(side="left", padx=8)

        # ---------- Audio panel ----------
        ttk.Label(right, text="Audio Capture + Transcription", font=("Segoe UI", 12, "bold")).pack(anchor="w")

        dev_frame = ttk.LabelFrame(right, text="Input Device", padding=8)
        dev_frame.pack(fill="x", pady=(6, 6))

        self.device_combo = ttk.Combobox(dev_frame, state="readonly")
        self.device_combo.pack(fill="x")
        self.device_combo.bind("<<ComboboxSelected>>", self.on_device_selected)

        hint = ("Tip: FrontMic is device 7 on your machine. "
                "You can also override at launch with:\n"
                "$env:CITL_AUDIO_IN_DEVICE='7'  (mic)  or  '5' (stereo mix)")
        ttk.Label(dev_frame, text=hint, foreground="#444", wraplength=360).pack(anchor="w", pady=(6, 0))

        rec_frame = ttk.Frame(right)
        rec_frame.pack(fill="x", pady=(6, 6))

        self.btn_start = ttk.Button(rec_frame, text="Start Recording", command=self.on_start_recording)
        self.btn_stop = ttk.Button(rec_frame, text="Stop & Save WAV", command=self.on_stop_and_save)
        self.btn_start.pack(side="left")
        self.btn_stop.pack(side="left", padx=8)

        trans_frame = ttk.LabelFrame(right, text="Transcription (offline)", padding=8)
        trans_frame.pack(fill="x", pady=(6, 6))

        self.lang_var = tk.StringVar(value="Auto")
        ttk.Label(trans_frame, text="Language:").pack(side="left")
        ttk.Combobox(trans_frame, textvariable=self.lang_var, state="readonly",
                     values=["Auto", "English", "Spanish"], width=10).pack(side="left", padx=6)

        ttk.Button(trans_frame, text="Transcribe Last WAV", command=self.on_transcribe_last).pack(side="left", padx=6)

        self.audio_status = tk.StringVar(value="Ready.")
        ttk.Label(right, textvariable=self.audio_status, foreground="#006").pack(anchor="w", pady=(6, 0))

        self.transcript_out = scrolledtext.ScrolledText(right, height=16, wrap="word")
        self.transcript_out.pack(fill="both", expand=True, pady=(6, 0))

    def _init_devices(self):
        if sd is None:
            self.device_combo["values"] = ["(sounddevice not installed)"]
            self.device_combo.current(0)
            self.btn_start["state"] = "disabled"
            self.btn_stop["state"] = "disabled"
            return

        devices = list_input_devices()
        if not devices:
            self.device_combo["values"] = ["(no input devices found)"]
            self.device_combo.current(0)
            self.btn_start["state"] = "disabled"
            self.btn_stop["state"] = "disabled"
            return

        display = [format_device_row(d) for d in devices]
        self.device_combo["values"] = display

        # Priority selection:
        # 1) env override
        env_idx = pick_device_index_from_env()
        if env_idx is not None:
            # select matching row
            for n, row in enumerate(display):
                if parse_device_index(row) == env_idx:
                    self.device_combo.current(n)
                    self.cfg["audio_in_device"] = row
                    save_config(self.cfg)
                    return

        # 2) config
        saved = self.cfg.get("audio_in_device", "")
        if saved in display:
            self.device_combo.set(saved)
            return

        # 3) auto scan a working device
        idx, sr, ch = first_working_input_device()
        if idx is not None:
            for n, row in enumerate(display):
                if parse_device_index(row) == idx:
                    self.device_combo.current(n)
                    self.cfg["audio_in_device"] = row
                    save_config(self.cfg)
                    return

        # 4) first item
        self.device_combo.current(0)
        self.cfg["audio_in_device"] = self.device_combo.get()
        save_config(self.cfg)

    def on_device_selected(self, _evt=None):
        choice = self.device_combo.get()
        self.cfg["audio_in_device"] = choice
        save_config(self.cfg)
        self.audio_status.set(f"Selected input device: {choice}")

    def _current_device_index(self):
        choice = self.device_combo.get()
        idx = parse_device_index(choice)
        return idx

    def on_start_recording(self):
        if sd is None or np is None:
            messagebox.showerror("Audio unavailable", "Recording requires sounddevice + numpy.")
            return

        idx = self._current_device_index()
        if idx is None:
            messagebox.showerror("No device", "Select a valid input device.")
            return

        try:
            self.rec.start(idx)
            self.audio_status.set(f"Recording… device {idx}. (Stop to save WAV)")
        except Exception as e:
            # This is where -9996 used to occur; now we show device guidance
            devs = "\n".join([format_device_row(d) for d in list_input_devices()])
            messagebox.showerror(
                "Start failed",
                f"{e}\n\nAvailable input devices:\n{devs}\n\n"
                f"On this laptop, try device 7 (FrontMic) or 5 (Stereo Mix).\n"
                f"You can also launch with PowerShell override:\n"
                f"$env:CITL_AUDIO_IN_DEVICE='7'"
            )

    def on_stop_and_save(self):
        if not self.rec.recording:
            self.audio_status.set("Not recording.")
            return

        ts = time.strftime("%Y%m%d_%H%M%S")
        out = RECORD_DIR / f"recording_{ts}.wav"

        try:
            path = self.rec.stop_and_save(out)
            self.audio_status.set(f"Saved WAV: {path}")
            self.transcript_out.insert("end", f"\n[SAVED] {path}\n")
            self.transcript_out.see("end")
        except Exception as e:
            messagebox.showerror("Save failed", str(e))

    def on_transcribe_last(self):
        last = self.rec.last_saved_wav
        if not last or not Path(last).exists():
            messagebox.showinfo("No audio", "No saved WAV found. Record and save first.")
            return

        mode = self.lang_var.get()
        self.audio_status.set("Transcribing… (offline)")
        self.update_idletasks()

        try:
            detected, text = transcribe_wav(last, mode)
            self.audio_status.set(f"Transcription complete. Language={detected}")
            self.transcript_out.insert("end", f"\n[TRANSCRIPT lang={detected}]\n{text}\n")
            self.transcript_out.see("end")
        except Exception as e:
            messagebox.showerror("Transcription failed", str(e))
            self.audio_status.set("Transcription failed.")

    def on_run_query(self):
        q = self.query_var.get().strip()
        if not q:
            return

        use_regex = bool(self.regex_var.get())
        topk = int(self.topk_var.get())
        maxctx = int(self.maxctx_var.get())

        self.factbook_out.delete("1.0", "end")
        self.factbook_out.insert("end", "[RUNNING]\n")
        self.update_idletasks()

        out = run_factbook_query(q, use_regex, topk, maxctx)
        self.factbook_out.delete("1.0", "end")
        self.factbook_out.insert("end", out)

    def on_add_text_files(self):
        paths = filedialog.askopenfilenames(
            title="Select .txt files to add",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")]
        )
        if not paths:
            return

        dest = DATA_DIR / "corpus"
        dest.mkdir(parents=True, exist_ok=True)

        copied = []
        for p in paths:
            src = Path(p)
            if not src.exists():
                continue
            dst = dest / src.name
            try:
                shutil.copy2(src, dst)
                copied.append(str(dst))
            except Exception:
                pass

        messagebox.showinfo("Loaded", "Copied:\n" + ("\n".join(copied) if copied else "(none)"))

    def on_open_data_folder(self):
        try:
            os.startfile(str(DATA_DIR))
        except Exception:
            messagebox.showinfo("Data folder", str(DATA_DIR))

    def _tick(self):
        # Drain audio queue periodically (keeps memory stable)
        try:
            if self.rec.recording:
                self.rec.poll()
        except Exception:
            pass
        self.after(200, self._tick)


def main():
    # HARD FAIL if recording requested but deps missing
    if sd is None:
        print("WARNING: sounddevice not installed; audio features disabled.")
    if np is None:
        print("WARNING: numpy not installed; audio features disabled.")

    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
