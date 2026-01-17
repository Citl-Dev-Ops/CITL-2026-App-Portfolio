import os
import sys
import json
import time
import shutil
import subprocess
from pathlib import Path
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, filedialog

from citl_audio_ffmpeg import (
    find_ffmpeg,
    list_dshow_audio_devices,
    start_recording,
    stop_recording,
    dshow_diagnostics,
    supports_dshow,
)

# -------------------------
# Data folders (no admin)
# -------------------------
IS_FROZEN = getattr(sys, "frozen", False)
APP_DIR = Path(sys.executable).resolve().parent if IS_FROZEN else Path(__file__).resolve().parent

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
CORPUS_DIR = DATA_DIR / "corpus"
CORPUS_DIR.mkdir(parents=True, exist_ok=True)
CONFIG_PATH = DATA_DIR / "config.json"

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

# -------------------------
# Factbook query (existing code)
# -------------------------
def query_script() -> Path:
    return Path(__file__).resolve().parent / "query_factbook.py"

def run_factbook_query(query: str, use_regex: bool, topk: int, maxctx: int) -> str:
    qs = query_script()
    if not qs.exists():
        return f"ERROR: query_factbook.py not found at:\n{qs}"

    cmd = [sys.executable, str(qs)]
    if use_regex:
        cmd.append("--regex")
    cmd += ["-k", str(int(topk)), "--maxctx", str(int(maxctx)), query]

    try:
        out = subprocess.check_output(cmd, stderr=subprocess.STDOUT, text=True, env=os.environ.copy())
        return out
    except subprocess.CalledProcessError as e:
        return e.output

# -------------------------
# Transcription (offline, no torch)
# -------------------------
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

# -------------------------
# Windows PnP fallback (for suggesting device strings)
# -------------------------
def pnp_yeti_suggestions() -> list[str]:
    try:
        cmd = [
            "powershell",
            "-NoProfile",
            "-Command",
            "Get-PnpDevice -PresentOnly | Where-Object { $_.FriendlyName -match 'Yeti|Blue' } | ForEach-Object { $_.FriendlyName }"
        ]
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
        out = (p.stdout or "").splitlines()
        out = [x.strip() for x in out if x.strip()]
        # Keep likely mic endpoint strings
        keep = []
        for x in out:
            if "Microphone" in x or "mic" in x.lower() or "Yeti" in x:
                keep.append(x)
        return keep
    except Exception:
        return []

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("CITL Factbook GUI (FFmpeg / DirectShow)")
        self.geometry("1200x780")

        self.cfg = load_config()
        self.ffmpeg = find_ffmpeg()
        self.proc = None
        self.last_wav = None

        self.build_ui()
        self.refresh_devices()

    def build_ui(self):
        outer = ttk.Frame(self, padding=8)
        outer.pack(fill="both", expand=True)

        paned = ttk.Panedwindow(outer, orient="horizontal")
        paned.pack(fill="both", expand=True)

        left = ttk.Frame(paned, padding=8)
        right = ttk.Frame(paned, padding=8)
        paned.add(left, weight=3)
        paned.add(right, weight=2)

        # ---- Factbook ----
        ttk.Label(left, text="Factbook Query", font=("Segoe UI", 12, "bold")).pack(anchor="w")
        qrow = ttk.Frame(left); qrow.pack(fill="x", pady=(6, 2))
        ttk.Label(qrow, text="Query:").pack(side="left")
        self.query_var = tk.StringVar(value="")
        ttk.Entry(qrow, textvariable=self.query_var).pack(side="left", fill="x", expand=True, padx=6)
        self.regex_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(qrow, text="Regex mode", variable=self.regex_var).pack(side="left")

        opts = ttk.Frame(left); opts.pack(fill="x", pady=(2, 6))
        self.topk_var = tk.IntVar(value=8)
        self.maxctx_var = tk.IntVar(value=2400)
        ttk.Label(opts, text="TopK:").pack(side="left")
        ttk.Spinbox(opts, from_=1, to=30, textvariable=self.topk_var, width=5).pack(side="left", padx=(4, 14))
        ttk.Label(opts, text="MaxCtx:").pack(side="left")
        ttk.Spinbox(opts, from_=500, to=12000, increment=100, textvariable=self.maxctx_var, width=7).pack(side="left", padx=(4, 14))
        ttk.Button(opts, text="Run Query", command=self.on_run_query).pack(side="left")

        self.factbook_out = scrolledtext.ScrolledText(left, height=24, wrap="word")
        self.factbook_out.pack(fill="both", expand=True, pady=(6, 6))

        corpus = ttk.LabelFrame(left, text="Load .txt documents (copied into %APPDATA%\\CITL\\corpus)", padding=8)
        corpus.pack(fill="x")
        ttk.Label(corpus, text=f"Corpus folder: {CORPUS_DIR}").pack(anchor="w")
        btns = ttk.Frame(corpus); btns.pack(fill="x", pady=(6,0))
        ttk.Button(btns, text="Add Text Files…", command=self.on_add_text_files).pack(side="left")
        ttk.Button(btns, text="Open Data Folder", command=self.on_open_data_folder).pack(side="left", padx=8)

        # ---- Audio ----
        ttk.Label(right, text="Recording + Transcription (FFmpeg)", font=("Segoe UI", 12, "bold")).pack(anchor="w")

        devbox = ttk.LabelFrame(right, text="Microphone (DirectShow)", padding=8)
        devbox.pack(fill="x", pady=(6, 6))

        # IMPORTANT: editable combobox (manual typing allowed)
        self.device_combo = ttk.Combobox(devbox, state="normal")
        self.device_combo.pack(fill="x")
        self.device_combo.bind("<<ComboboxSelected>>", self.on_device_selected)

        dbtns = ttk.Frame(devbox); dbtns.pack(fill="x", pady=(6, 0))
        ttk.Button(dbtns, text="Refresh Device List", command=self.refresh_devices).pack(side="left")
        ttk.Button(dbtns, text="Diagnostics", command=self.on_diagnostics).pack(side="left", padx=8)

        self.diag_out = scrolledtext.ScrolledText(devbox, height=10, wrap="word")
        self.diag_out.pack(fill="both", expand=True, pady=(6, 0))

        rec = ttk.Frame(right); rec.pack(fill="x", pady=(6, 6))
        ttk.Button(rec, text="Start Recording", command=self.on_start).pack(side="left")
        ttk.Button(rec, text="Stop Recording", command=self.on_stop).pack(side="left", padx=8)

        trans = ttk.LabelFrame(right, text="Transcription (offline)", padding=8)
        trans.pack(fill="x", pady=(6, 6))
        self.lang_var = tk.StringVar(value="Auto")
        ttk.Label(trans, text="Language:").pack(side="left")
        ttk.Combobox(trans, textvariable=self.lang_var, state="readonly",
                     values=["Auto", "English", "Spanish"], width=10).pack(side="left", padx=6)
        ttk.Button(trans, text="Transcribe Last WAV", command=self.on_transcribe).pack(side="left", padx=6)

        self.status_var = tk.StringVar(value="Ready.")
        ttk.Label(right, textvariable=self.status_var, foreground="#006").pack(anchor="w", pady=(6, 0))

        self.transcript_out = scrolledtext.ScrolledText(right, height=12, wrap="word")
        self.transcript_out.pack(fill="both", expand=True, pady=(6, 0))

    def on_diagnostics(self):
        self.diag_out.delete("1.0", "end")
        if not self.ffmpeg:
            self.diag_out.insert("end", "FFmpeg not found. Put ffmpeg.exe in factbook-assistant\\bin\\ffmpeg.exe\n")
            return

        out = dshow_diagnostics(self.ffmpeg)
        self.diag_out.insert("end", f"FFmpeg path: {self.ffmpeg}\n\n")
        self.diag_out.insert("end", out if out else "(no output)\n")

        if not supports_dshow(self.ffmpeg):
            self.status_var.set("FFmpeg build may not support DirectShow (dshow). See Diagnostics output.")

    def refresh_devices(self):
        self.diag_out.delete("1.0", "end")

        if not self.ffmpeg:
            self.device_combo["values"] = ["(ffmpeg missing)"]
            self.device_combo.set("(ffmpeg missing)")
            self.status_var.set("FFmpeg missing.")
            return

        devs = []
        try:
            devs = list_dshow_audio_devices(self.ffmpeg)
        except Exception as e:
            self.device_combo["values"] = [f"(error listing devices: {e})"]
            self.device_combo.set(self.device_combo["values"][0])
            self.status_var.set("Device list error. Click Diagnostics.")
            return

        saved = self.cfg.get("dshow_audio_device", "").strip()

        # If FFmpeg returns no devices, we still allow manual typing + show suggestions
        if not devs:
            sug = pnp_yeti_suggestions()
            vals = []
            if saved:
                vals.append(saved)
            vals += [s for s in sug if s not in vals]
            if not vals:
                vals = ["Microphone (Yeti Stereo Microphone)"]  # common endpoint label
            self.device_combo["values"] = vals
            self.device_combo.set(vals[0])
            self.status_var.set("No DirectShow devices enumerated. Type a device name or click Diagnostics.")
            return

        self.device_combo["values"] = devs
        if saved in devs:
            self.device_combo.set(saved)
        else:
            self.device_combo.set(devs[0])
            self.cfg["dshow_audio_device"] = self.device_combo.get()
            save_config(self.cfg)

        self.status_var.set("Device list loaded.")

    def on_device_selected(self, _evt=None):
        self.cfg["dshow_audio_device"] = self.device_combo.get()
        save_config(self.cfg)

    def on_start(self):
        if not self.ffmpeg:
            messagebox.showerror("FFmpeg missing", "ffmpeg.exe not found.")
            return
        if self.proc is not None:
            return

        dev = (self.device_combo.get() or "").strip()
        if not dev or dev.startswith("("):
            messagebox.showerror("No device", "Select or type a valid microphone device name.")
            return

        # Save whatever the user typed/selected
        self.cfg["dshow_audio_device"] = dev
        save_config(self.cfg)

        ts = time.strftime("%Y%m%d_%H%M%S")
        out = str(RECORD_DIR / f"recording_{ts}.wav")

        try:
            self.proc = start_recording(self.ffmpeg, dev, out, samplerate=16000)
            self.last_wav = out
            self.status_var.set(f"Recording… saving to {out}")
        except Exception as e:
            messagebox.showerror("Start failed", str(e))
            self.proc = None
            self.last_wav = None

    def on_stop(self):
        if self.proc is None:
            self.status_var.set("Not recording.")
            return
        stop_recording(self.proc)
        self.proc = None
        if self.last_wav and Path(self.last_wav).exists():
            self.status_var.set(f"Saved WAV: {self.last_wav}")
            self.transcript_out.insert("end", f"\n[SAVED] {self.last_wav}\n")
            self.transcript_out.see("end")
        else:
            self.status_var.set("Stopped, but WAV not found (check device name).")

    def on_transcribe(self):
        if not self.last_wav or not Path(self.last_wav).exists():
            messagebox.showinfo("No WAV", "Record and stop first.")
            return
        try:
            self.status_var.set("Transcribing…")
            self.update_idletasks()
            detected, text = transcribe_wav(self.last_wav, self.lang_var.get())
            self.status_var.set(f"Done. lang={detected}")
            self.transcript_out.insert("end", f"\n[TRANSCRIPT lang={detected}]\n{text}\n")
            self.transcript_out.see("end")
        except Exception as e:
            messagebox.showerror("Transcription failed", str(e))
            self.status_var.set("Transcription failed.")

    def on_run_query(self):
        q = self.query_var.get().strip()
        if not q:
            return
        out = run_factbook_query(q, bool(self.regex_var.get()), int(self.topk_var.get()), int(self.maxctx_var.get()))
        self.factbook_out.delete("1.0", "end")
        self.factbook_out.insert("end", out)

    def on_add_text_files(self):
        paths = filedialog.askopenfilenames(
            title="Select .txt files to add",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")]
        )
        if not paths:
            return
        copied = []
        for p in paths:
            src = Path(p)
            if not src.exists():
                continue
            dst = CORPUS_DIR / src.name
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

def main():
    App().mainloop()

if __name__ == "__main__":
    main()
