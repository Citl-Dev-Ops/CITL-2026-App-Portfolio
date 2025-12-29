import os, sys, json, time, threading, queue, shutil, wave
from pathlib import Path
import numpy as np
import sounddevice as sd
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
try:
    import whisper
except Exception:
    whisper = None
DEFAULT_SAMPLE_RATE = 16000
DEFAULT_CHANNELS = 1
DEFAULT_MAX_MINUTES = 90
DEFAULT_RESERVE_GB = 5
def bytes_per_second(sample_rate: int, channels: int) -> int:
    return sample_rate * channels * 2  # 16-bit PCM
def disk_free_bytes(path: Path) -> int:
    return shutil.disk_usage(str(path)).free
def format_gb(b: int) -> str:
    return f"{b/1024/1024/1024:.1f} GB"
def safe_name(s: str) -> str:
    s = (s or "").strip().replace(" ", "_")
    keep = "".join(ch for ch in s if ch.isalnum() or ch in ("_", "-", "."))
    return keep[:80] or "Session"
def list_input_devices():
    devs = sd.query_devices()
    out = []
    for i, d in enumerate(devs):
        if d.get("max_input_channels", 0) > 0:
            out.append((i, d.get("name", f"Device {i}"), int(d.get("max_input_channels", 1)), int(d.get("default_samplerate", DEFAULT_SAMPLE_RATE))))
    return out
class WavRecorder:
    def __init__(self, device_index: int, sample_rate: int, channels: int, out_wav: Path):
        self.device_index = device_index
        self.sample_rate = sample_rate
        self.channels = channels
        self.out_wav = out_wav
        self._q = queue.Queue()
        self._stop = threading.Event()
        self._paused = threading.Event()
        self._paused.clear()
        self.frames_written = 0
        self.start_time = None
        self._stream = None
        self._writer_thread = None
        self._wf = None
    def _callback(self, indata, frames, time_info, status):
        if self._stop.is_set() or self._paused.is_set():
            return
        self._q.put(indata.copy())
    def start(self):
        self.out_wav.parent.mkdir(parents=True, exist_ok=True)
        self._wf = wave.open(str(self.out_wav), "wb")
        self._wf.setnchannels(self.channels)
        self._wf.setsampwidth(2)
        self._wf.setframerate(self.sample_rate)
        self._stop.clear()
        self._paused.clear()
        self.frames_written = 0
        self.start_time = time.time()
        self._writer_thread = threading.Thread(target=self._writer_loop, daemon=True)
        self._writer_thread.start()
        self._stream = sd.InputStream(
            device=self.device_index,
            samplerate=self.sample_rate,
            channels=self.channels,
            dtype="float32",
            callback=self._callback,
        )
        self._stream.start()
    def _writer_loop(self):
        while not self._stop.is_set() or not self._q.empty():
            try:
                block = self._q.get(timeout=0.25)
            except queue.Empty:
                continue
            block = np.clip(block, -1.0, 1.0)
            pcm = (block * 32767).astype(np.int16)
            self._wf.writeframes(pcm.tobytes())
            self.frames_written += pcm.shape[0]
        try:
            self._wf.close()
        except Exception:
            pass
    def pause(self): self._paused.set()
    def resume(self): self._paused.clear()
    def stop(self):
        self._stop.set()
        try:
            if self._stream:
                self._stream.stop()
                self._stream.close()
        except Exception:
            pass
        if self._writer_thread:
            self._writer_thread.join(timeout=5)
    def elapsed_seconds(self) -> int:
        if not self.start_time:
            return 0
        return int(time.time() - self.start_time)
def _fmt_ts(sec: float) -> str:
    ms = int(round((sec - int(sec)) * 1000))
    s = int(sec) % 60
    m = (int(sec) // 60) % 60
    h = int(sec) // 3600
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"
def transcribe_whisper(wav_path: Path, out_txt: Path, out_vtt: Path, model_name: str):
    if whisper is None:
        raise RuntimeError("whisper is not installed. pip install openai-whisper")
    model = whisper.load_model(model_name)
    try:
        import torch
        fp16 = bool(torch.cuda.is_available())
    except Exception:
        fp16 = False
    result = model.transcribe(str(wav_path), fp16=fp16)
    text = (result.get("text") or "").strip()
    out_txt.write_text(text + "\n", encoding="utf-8")
    segs = result.get("segments", []) or []
    lines = ["WEBVTT", ""]
    for s in segs:
        st = float(s.get("start", 0))
        et = float(s.get("end", 0))
        t  = (s.get("text") or "").strip()
        lines.append(f"{_fmt_ts(st)} --> {_fmt_ts(et)}")
        lines.append(t)
        lines.append("")
    out_vtt.write_text("\n".join(lines), encoding="utf-8")
class ClassCaptureWindow(tk.Toplevel):
    def __init__(self, parent, recordings_root: Path):
        super().__init__(parent)
        self.title("CITL Class Capture (Record + Transcribe)")
        self.geometry("980x560")
        self.recordings_root = recordings_root
        self.recorder = None
        self.session_dir = None
        self.room_var = tk.StringVar(value="Room_Unknown")
        self.instructor_var = tk.StringVar(value="")
        self.session_title_var = tk.StringVar(value="")
        self.device_var = tk.StringVar()
        self.samplerate_var = tk.StringVar(value=str(DEFAULT_SAMPLE_RATE))
        self.channels_var = tk.StringVar(value=str(DEFAULT_CHANNELS))
        self.max_minutes_var = tk.StringVar(value=str(DEFAULT_MAX_MINUTES))
        self.reserve_gb_var = tk.StringVar(value=str(DEFAULT_RESERVE_GB))
        self.whisper_model_var = tk.StringVar(value="base")
        self.auto_transcribe_var = tk.BooleanVar(value=True)
        self.status_var = tk.StringVar(value="Ready")
        self.timer_var = tk.StringVar(value="00:00:00")
        self.disk_var = tk.StringVar(value="Free: ?")
        self.remaining_var = tk.StringVar(value="Remaining: ?")
        self._build_ui()
        self._load_devices()
        self._tick()
    def _build_ui(self):
        frm = ttk.Frame(self, padding=10)
        frm.pack(fill="both", expand=True)
        r1 = ttk.Frame(frm); r1.pack(fill="x", pady=4)
        ttk.Label(r1, text="Room:").pack(side="left")
        ttk.Entry(r1, textvariable=self.room_var, width=18).pack(side="left", padx=6)
        ttk.Label(r1, text="Instructor:").pack(side="left")
        ttk.Entry(r1, textvariable=self.instructor_var, width=18).pack(side="left", padx=6)
        ttk.Label(r1, text="Session Title:").pack(side="left")
        ttk.Entry(r1, textvariable=self.session_title_var, width=30).pack(side="left", padx=6)
        r2 = ttk.Frame(frm); r2.pack(fill="x", pady=4)
        ttk.Label(r2, text="Mic Device:").pack(side="left")
        self.device_combo = ttk.Combobox(r2, textvariable=self.device_var, width=70, state="readonly")
        self.device_combo.pack(side="left", padx=6)
        ttk.Button(r2, text="Refresh Devices", command=self._load_devices).pack(side="left", padx=6)
        ttk.Label(r2, text="Rate:").pack(side="left", padx=(12,0))
        ttk.Entry(r2, textvariable=self.samplerate_var, width=7).pack(side="left", padx=6)
        ttk.Label(r2, text="Ch:").pack(side="left")
        ttk.Entry(r2, textvariable=self.channels_var, width=3).pack(side="left", padx=6)
        r3 = ttk.Frame(frm); r3.pack(fill="x", pady=4)
        ttk.Label(r3, text="Max minutes:").pack(side="left")
        ttk.Entry(r3, textvariable=self.max_minutes_var, width=6).pack(side="left", padx=6)
        ttk.Label(r3, text="Reserve disk (GB):").pack(side="left")
        ttk.Entry(r3, textvariable=self.reserve_gb_var, width=5).pack(side="left", padx=6)
        ttk.Label(r3, text="Whisper:").pack(side="left", padx=(12,0))
        ttk.Combobox(r3, textvariable=self.whisper_model_var, width=10, state="readonly",
                     values=["tiny","base","small","medium","large"]).pack(side="left", padx=6)
        ttk.Checkbutton(r3, text="Auto-transcribe on Stop", variable=self.auto_transcribe_var).pack(side="left", padx=10)
        ttk.Button(r3, text="Choose Recordings Folder", command=self._choose_root).pack(side="right")
        r4 = ttk.Frame(frm); r4.pack(fill="x", pady=10)
        self.btn_start = ttk.Button(r4, text="Start", command=self.start_recording)
        self.btn_pause = ttk.Button(r4, text="Pause", command=self.pause_recording, state="disabled")
        self.btn_resume = ttk.Button(r4, text="Resume", command=self.resume_recording, state="disabled")
        self.btn_stop = ttk.Button(r4, text="Stop", command=self.stop_recording, state="disabled")
        self.btn_start.pack(side="left")
        self.btn_pause.pack(side="left", padx=6)
        self.btn_resume.pack(side="left", padx=6)
        self.btn_stop.pack(side="left", padx=6)
        ttk.Label(r4, textvariable=self.timer_var, font=("Consolas", 14)).pack(side="left", padx=20)
        ttk.Label(r4, textvariable=self.disk_var).pack(side="left", padx=10)
        ttk.Label(r4, textvariable=self.remaining_var).pack(side="left", padx=10)
        self.log = tk.Text(frm, height=14, wrap="word", font=("Consolas", 10))
        self.log.pack(fill="both", expand=True)
        ttk.Label(frm, textvariable=self.status_var).pack(anchor="w", pady=(8,0))
    def _log(self, msg: str):
        self.log.insert("end", msg + "\n")
        self.log.see("end")
    def _choose_root(self):
        p = filedialog.askdirectory(title="Choose recordings folder", initialdir=str(self.recordings_root))
        if p:
            self.recordings_root = Path(p)
            self._log(f"Recordings root set to: {self.recordings_root}")
    def _load_devices(self):
        devs = list_input_devices()
        self._devices = devs
        items = [f"{i} - {name} (max_in={ch}, default_rate={rate})" for (i, name, ch, rate) in devs]
        self.device_combo["values"] = items
        if items:
            self.device_var.set(items[0])
    def _selected_device_index(self) -> int:
        return int(self.device_var.get().split("-")[0].strip())
    def _make_session_dir(self) -> Path:
        date = time.strftime("%Y-%m-%d")
        stamp = time.strftime("%Y-%m-%d_%H-%M-%S")
        room = safe_name(self.room_var.get())
        instr = safe_name(self.instructor_var.get() or "Instructor")
        title = safe_name(self.session_title_var.get() or "Class")
        folder = self.recordings_root / date / room / f"{stamp}_{instr}_{title}"
        folder.mkdir(parents=True, exist_ok=True)
        return folder
    def start_recording(self):
        try:
            device_index = self._selected_device_index()
            sr = int(self.samplerate_var.get() or DEFAULT_SAMPLE_RATE)
            ch = int(self.channels_var.get() or DEFAULT_CHANNELS)
            self.session_dir = self._make_session_dir()
            wav_path = self.session_dir / "audio.wav"
            meta = {
                "room": self.room_var.get(),
                "instructor": self.instructor_var.get(),
                "title": self.session_title_var.get(),
                "device_index": device_index,
                "sample_rate": sr,
                "channels": ch,
                "start_local": time.strftime("%Y-%m-%d %H:%M:%S"),
            }
            (self.session_dir / "session_meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
            self.recorder = WavRecorder(device_index, sr, ch, wav_path)
            self.recorder.start()
            self.status_var.set(f"Recording... {wav_path}")
            self._log(f"START -> {wav_path}")
            self.btn_start.config(state="disabled")
            self.btn_pause.config(state="normal")
            self.btn_stop.config(state="normal")
        except Exception as e:
            messagebox.showerror("Start failed", str(e))
            self.status_var.set("Start failed")
    def pause_recording(self):
        if self.recorder:
            self.recorder.pause()
            self.status_var.set("Paused")
            self._log("PAUSE")
            self.btn_pause.config(state="disabled")
            self.btn_resume.config(state="normal")
    def resume_recording(self):
        if self.recorder:
            self.recorder.resume()
            self.status_var.set("Recording...")
            self._log("RESUME")
            self.btn_resume.config(state="disabled")
            self.btn_pause.config(state="normal")
    def stop_recording(self):
        if not self.recorder:
            return
        self.status_var.set("Stopping...")
        self._log("STOP requested")
        rec = self.recorder
        self.recorder = None
        def run():
            try:
                rec.stop()
                self._log("STOP complete")
                self.status_var.set("Stopped")
                self.btn_start.config(state="normal")
                self.btn_pause.config(state="disabled")
                self.btn_resume.config(state="disabled")
                self.btn_stop.config(state="disabled")
                if self.auto_transcribe_var.get():
                    self._transcribe_latest()
            except Exception as e:
                self._log(f"Stop error: {e}")
                self.status_var.set("Stop error")
        threading.Thread(target=run, daemon=True).start()
    def _transcribe_latest(self):
        if not self.session_dir:
            return
        wav_path = self.session_dir / "audio.wav"
        out_txt = self.session_dir / "transcript.txt"
        out_vtt = self.session_dir / "transcript.vtt"
        model = self.whisper_model_var.get().strip() or "base"
        if whisper is None:
            self._log("Whisper not installed - transcription skipped.")
            self.status_var.set("Transcription unavailable")
            return
        def run():
            try:
                self.status_var.set(f"Transcribing ({model})...")
                self._log(f"TRANSCRIBE ({model}) -> {wav_path.name}")
                transcribe_whisper(wav_path, out_txt, out_vtt, model)
                self._log(f"DONE -> {out_txt.name}, {out_vtt.name}")
                self.status_var.set("Transcription complete")
            except Exception as e:
                self._log(f"Transcribe failed: {e}")
                self.status_var.set("Transcription failed")
        threading.Thread(target=run, daemon=True).start()
    def _tick(self):
        try:
            free = disk_free_bytes(self.recordings_root)
            self.disk_var.set(f"Free: {format_gb(free)}")
            if self.recorder:
                elapsed = self.recorder.elapsed_seconds()
                self.timer_var.set(time.strftime("%H:%M:%S", time.gmtime(elapsed)))
                sr = int(self.samplerate_var.get() or DEFAULT_SAMPLE_RATE)
                ch = int(self.channels_var.get() or DEFAULT_CHANNELS)
                reserve_gb = float(self.reserve_gb_var.get() or DEFAULT_RESERVE_GB)
                reserve_bytes = int(reserve_gb * 1024 * 1024 * 1024)
                usable = max(0, free - reserve_bytes)
                est_seconds = int(usable / bytes_per_second(sr, ch)) if sr > 0 else 0
                max_minutes = int(self.max_minutes_var.get() or DEFAULT_MAX_MINUTES)
                remaining = max(0, min(est_seconds, max_minutes * 60 - elapsed))
                self.remaining_var.set("Remaining: " + time.strftime("%H:%M:%S", time.gmtime(remaining)))
                if elapsed >= max_minutes * 60:
                    self._log("AUTO-STOP: max duration reached.")
                    self.stop_recording()
                elif free <= reserve_bytes:
                    self._log("AUTO-STOP: disk reserve reached.")
                    self.stop_recording()
            else:
                self.timer_var.set("00:00:00")
                self.remaining_var.set("Remaining: -")
        except Exception:
            pass
        self.after(500, self._tick)
def open_class_capture(parent, recordings_root: Path):
    return ClassCaptureWindow(parent, recordings_root)