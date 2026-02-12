import os, json, time, platform
from pathlib import Path
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox

from citl_audio_ffmpeg_graceful_v2 import (
    find_ffmpeg,
    list_audio_devices,
    start_recording,
    stop_recording,
    audio_diagnostics,
)

def pick_data_dir() -> Path:
    env = os.environ.get("CITL_DATA_DIR", "").strip()
    if env:
        p = Path(env).expanduser()
        p.mkdir(parents=True, exist_ok=True)
        return p
    appdata = os.environ.get("APPDATA", str(Path.home()))
    p = Path(appdata) / "CITL"
    p.mkdir(parents=True, exist_ok=True)
    return p

DATA_DIR = pick_data_dir()
RECORD_DIR = DATA_DIR / "recordings"
RECORD_DIR.mkdir(parents=True, exist_ok=True)

# per-machine config so copied kits don't keep a "sticky" mic from another PC
_MACHINE = (os.environ.get("COMPUTERNAME") or platform.node() or "machine").strip().replace(" ", "_")
CONFIG_PATH = DATA_DIR / f"config_{_MACHINE}.json"

def load_config():
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}

def save_config(cfg):
    try:
        CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    except Exception:
        pass

def transcribe_wav(path: str, lang_mode: str):
    from faster_whisper import WhisperModel
    model = WhisperModel("small", device="cpu", compute_type="int8")

    if lang_mode == "English":
        language = "en"
    elif lang_mode == "Spanish":
        language = "es"
    else:
        language = None

    segments, info = model.transcribe(path, language=language)
    detected = getattr(info, "language", None) or (language or "unknown")

    if lang_mode == "Auto" and detected not in ("en", "es"):
        segments, info = model.transcribe(path, language="en")
        detected = "en"

    text = "".join(seg.text for seg in segments).strip()
    return detected, text

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Recording + Transcription (Device-Agnostic)")
        self.geometry("1100x760")

        self.cfg = load_config()
        self.ffmpeg = find_ffmpeg()
        self.handle = None
        self.last_wav = None

        self.build_ui()
        self.refresh_devices(first_load=True)

    def build_ui(self):
        root = ttk.Frame(self, padding=8); root.pack(fill="both", expand=True)

        box = ttk.LabelFrame(root, text="Microphone (auto-detect)", padding=8)
        box.pack(fill="x")

        self.device_combo = ttk.Combobox(box, state="readonly")
        self.device_combo.pack(fill="x")
        self.device_combo.bind("<<ComboboxSelected>>", self.on_device_selected)

        btns = ttk.Frame(box); btns.pack(fill="x", pady=(6,0))
        ttk.Button(btns, text="Refresh Device List", command=self.refresh_devices).pack(side="left")
        ttk.Button(btns, text="Reset Saved Device", command=self.reset_saved_device).pack(side="left", padx=8)
        ttk.Button(btns, text="Diagnostics", command=self.on_diagnostics).pack(side="left", padx=8)

        self.diag_out = scrolledtext.ScrolledText(box, height=10, wrap="word")
        self.diag_out.pack(fill="both", expand=True, pady=(6,0))

        rec = ttk.Frame(root); rec.pack(fill="x", pady=(10,6))
        ttk.Button(rec, text="Start Recording", command=self.on_start).pack(side="left")
        ttk.Button(rec, text="Stop Recording", command=self.on_stop).pack(side="left", padx=8)

        trans = ttk.LabelFrame(root, text="Transcription (offline)", padding=8)
        trans.pack(fill="x", pady=(6,6))
        self.lang_var = tk.StringVar(value="English")
        ttk.Label(trans, text="Language:").pack(side="left")
        ttk.Combobox(trans, textvariable=self.lang_var, state="readonly",
                     values=["Auto","English","Spanish"], width=10).pack(side="left", padx=6)
        ttk.Button(trans, text="Transcribe Last WAV", command=self.on_transcribe).pack(side="left", padx=6)

        self.status_var = tk.StringVar(value="Ready.")
        ttk.Label(root, textvariable=self.status_var).pack(anchor="w", pady=(8,0))

        self.out = scrolledtext.ScrolledText(root, height=18, wrap="word")
        self.out.pack(fill="both", expand=True, pady=(6,0))

    def set_status(self, msg: str):
        self.status_var.set(msg)
        self.update_idletasks()

    def reset_saved_device(self):
        self.cfg.pop("audio_device", None)
        save_config(self.cfg)
        self.refresh_devices(first_load=False)

    def refresh_devices(self, first_load: bool = False):
        devs = list_audio_devices(self.ffmpeg)

        saved = (self.cfg.get("audio_device","") or "").strip()

        # Clear stale saved device if it doesn't exist here
        if saved and saved not in devs:
            saved = ""
            self.cfg["audio_device"] = ""
            save_config(self.cfg)

        self.device_combo["values"] = tuple(devs)

        if devs:
            pick = saved if saved in devs else devs[0]  # auto-select best choice
            self.device_combo.set(pick)
            self.cfg["audio_device"] = pick
            save_config(self.cfg)
            self.set_status(f"{'Loaded' if first_load else 'Refreshed'} {len(devs)} device(s). Config: {CONFIG_PATH.name}")
        else:
            self.device_combo.set("")
            self.set_status("No devices detected. Click Diagnostics.")

    def on_device_selected(self, _evt=None):
        v = self.device_combo.get().strip()
        self.cfg["audio_device"] = v
        save_config(self.cfg)

    def on_diagnostics(self):
        self.diag_out.delete("1.0","end")
        self.diag_out.insert("end", audio_diagnostics(self.ffmpeg) + "\n")

    def on_start(self):
        if self.handle is not None:
            return

        dev = self.device_combo.get().strip()
        if not dev:
            messagebox.showerror("No device","Click Refresh Device List, then select a device.")
            return

        ts = time.strftime("%Y%m%d_%H%M%S")
        out = str(RECORD_DIR / f"recording_{ts}.wav")

        try:
            self.handle = start_recording(self.ffmpeg, dev, out, samplerate=16000)
            self.last_wav = out
            self.set_status(f"Recording saving to {out}")
        except Exception as e:
            messagebox.showerror("Start failed", str(e))
            self.handle = None
            self.last_wav = None
            self.refresh_devices(first_load=False)

    def on_stop(self):
        if self.handle is None:
            self.set_status("Not recording.")
            return

        out = stop_recording(self.handle)
        self.handle = None

        for _ in range(25):
            if self.last_wav and Path(self.last_wav).exists():
                break
            time.sleep(0.1)

        if self.last_wav and Path(self.last_wav).exists():
            self.set_status(f"Saved WAV: {self.last_wav}")
            self.out.insert("end", f"\n[SAVED] {self.last_wav}\n")
            self.out.see("end")
        else:
            self.set_status("Stopped, but WAV not found. Showing recorder output.")
            self.out.insert("end", "\n[OUTPUT]\n" + (out or "(no output)") + "\n")
            self.out.see("end")

    def on_transcribe(self):
        if not self.last_wav or not Path(self.last_wav).exists():
            messagebox.showinfo("No WAV","Record and stop first.")
            return
        detected, text = transcribe_wav(self.last_wav, self.lang_var.get())
        self.out.insert("end", f"\n[TRANSCRIPT lang={detected}]\n{text}\n")
        self.out.see("end")

def main():
    App().mainloop()

if __name__ == "__main__":
    main()
