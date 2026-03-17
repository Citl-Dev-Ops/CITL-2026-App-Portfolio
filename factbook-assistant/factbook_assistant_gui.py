"""
CITL Factbook + Transcription + Translation GUI
PLUS: Library/Index management + Modelfile/Ollama grafting (restored)

Tabs:
  1) Factbook
  2) Audio / Transcribe
  3) Translate
  4) Library / Models   <-- restored controls

Portable conventions:
  - Modelfiles default dir: ~/CITL_Modelfiles
  - Runs fine if some modules absent; shows actionable errors instead of crashing.
"""
import os
import sys
import json
import re
import time
import platform
import threading
import subprocess
import shutil
import wave
import audioop
import math
from pathlib import Path
from typing import Optional, List
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, filedialog
from urllib.request import Request, urlopen

# ── Optional CITL modules (graceful degradation) ────────────────────────────
try:
    from citl_audio_ffmpeg_graceful_v2 import (
        find_ffmpeg, list_audio_devices, start_recording, stop_recording, audio_diagnostics,
    )
    _HAS_AUDIO = True
except Exception:
    _HAS_AUDIO = False

try:
    import citl_theme as _theme
    _HAS_THEME = True
except Exception:
    _HAS_THEME = False

try:
    import citl_modelfile as _mf
    _HAS_MODELFILE = True
except Exception:
    _HAS_MODELFILE = False

try:
    import citl_translation as _tr
    _HAS_TR = True
except Exception:
    _HAS_TR = False

try:
    from citl_app_sync import discover_sync_targets as _discover_sync_targets
    _HAS_APP_SYNC = True
except Exception:
    _HAS_APP_SYNC = False

try:
    import citl_corpus_health as _ch
    _HAS_CORPUS_HEALTH = True
except Exception:
    _HAS_CORPUS_HEALTH = False

# ── Repo paths ─────────────────────────────────────────────────────────────
HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent  # .../CITL
MODELFILES_DIR = Path(os.path.expanduser("~/CITL_Modelfiles"))

DEFAULT_MODEFILE_SYSTEM_PROMPT = """You are CITL Assistant, a professional academic support and fact-checking assistant.

Operational rules:
1. Use only verified information from the supplied local corpus/context.
2. If the context is missing, ambiguous, or weak, say you do not have enough verified context.
3. Do not invent facts, citations, policies, names, dates, or numbers.
4. Keep answers concise, structured, and classroom-ready.
5. When making factual claims, include source identifiers when available.

Style:
- Professional, direct, and calm.
- Prefer short paragraphs and bullet points.
- Avoid filler language and speculation.
"""

# ── Data dir ───────────────────────────────────────────────────────────────
def _pick_data_dir() -> Path:
    env = os.environ.get("CITL_DATA_DIR", "").strip()
    if env:
        p = Path(env).expanduser()
        p.mkdir(parents=True, exist_ok=True)
        return p
    appdata = os.environ.get("APPDATA", str(Path.home()))
    p = Path(appdata) / "CITL"
    p.mkdir(parents=True, exist_ok=True)
    return p

DATA_DIR   = _pick_data_dir()
RECORD_DIR = DATA_DIR / "recordings"
RECORD_DIR.mkdir(parents=True, exist_ok=True)

_MACHINE    = (os.environ.get("COMPUTERNAME") or platform.node() or "machine").strip().replace(" ", "_")
CONFIG_PATH = DATA_DIR / f"config_{_MACHINE}.json"

def _load_cfg() -> dict:
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}

def _save_cfg(cfg: dict) -> None:
    try:
        CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    except Exception:
        pass

# ── Transcription (Whisper) ────────────────────────────────────────────────
def _transcribe_wav(path: str, lang_mode: str) -> tuple:
    from faster_whisper import WhisperModel
    model = WhisperModel("small", device="cpu", compute_type="int8")
    lang_map = {"English": "en", "Spanish": "es", "Arabic": "ar"}
    language = lang_map.get(lang_mode) if lang_mode != "Auto" else None
    segments, info = model.transcribe(
        path,
        language=language,
        vad_filter=True,
        condition_on_previous_text=False,
    )
    detected = getattr(info, "language", None) or (language or "unknown")
    seg_texts: List[str] = []
    seg_count = 0
    for seg in segments:
        seg_count += 1
        seg_texts.append(seg.text)
    text = "".join(seg_texts).strip()
    return detected, text, seg_count

# ── Factbook query ─────────────────────────────────────────────────────────
def _query_factbook(question: str, model: str, host: str) -> str:
    try:
        from citl_factbook_query import answer_question
        return answer_question(question, model=model, ollama_host=host)
    except Exception as e:
        return f"[Factbook error: {e}]"
# ── Utilities ──────────────────────────────────────────────────────────────
def _which_ollama() -> Optional[str]:
    return shutil.which("ollama")

_ANSI_ESCAPE_RE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")

def _clean_cli_text(s: str) -> str:
    if not s:
        return ""
    s = s.replace("\r", "\n")
    s = _ANSI_ESCAPE_RE.sub("", s)
    return s

def _run_threaded(self, title: str, cmd: list, cwd: Path, out: tk.Text) -> None:
    """
    Run a command and stream stdout/stderr into a text widget.
    """
    out.configure(state="normal")
    out.insert("end", f"\n== {title} ==\n$ {' '.join(cmd)}\n(cwd={cwd})\n")
    out.see("end")
    out.configure(state="disabled")

    def _worker():
        try:
            p = subprocess.Popen(
                cmd, cwd=str(cwd),
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1
            )
            assert p.stdout is not None
            for line in p.stdout:
                cleaned = _clean_cli_text(line)
                if cleaned:
                    self.after(0, lambda s=cleaned: _append(out, s))
            rc = p.wait()
            self.after(0, lambda: _append(out, f"\n[exit {rc}]\n"))
        except Exception as e:
            self.after(0, lambda: _append(out, f"\n[error] {e}\n"))

    threading.Thread(target=_worker, daemon=True).start()

def _append(out: tk.Text, s: str) -> None:
    out.configure(state="normal")
    out.insert("end", s)
    out.see("end")
    out.configure(state="disabled")

# ═══════════════════════════════════════════════════════════════════════════
class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("CITL Desktop LLM Assistant")
        self.geometry("1200x860")
        self.minsize(900, 650)

        self.cfg = _load_cfg()
        self.ffmpeg = find_ffmpeg() if _HAS_AUDIO else None
        self.handle = None
        self.last_wav: Optional[str] = None
        self._live_translate_id: Optional[str] = None
        self.modelfiles_dir = self._pick_modelfiles_dir()

        self._build_ui()
        self._apply_saved_theme()
        self._restore_last_session_profile()
        self.refresh_devices(first_load=True)
        self._tick()
        self._usb_sync_offer_done = False
        self._corpus_health_report = None
        self.after(1800, self._maybe_offer_usb_sync)
        self.after(2200, self._auto_index_on_startup)

    # ── UI ────────────────────────────────────────────────────────────────
    def _build_ui(self) -> None:
        self._build_toolbar()
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True, padx=4, pady=(0, 4))
        self._build_factbook_tab()
        self._build_audio_tab()
        self._build_translate_tab()
        self._build_library_models_tab()  # RESTORED
        self._build_corpus_health_tab()

    def _build_toolbar(self) -> None:
        bar = ttk.Frame(self)
        bar.pack(fill="x", padx=4, pady=(4, 2))

        ttk.Label(bar, text="Bot:").pack(side="left")
        self.botname_var = tk.StringVar(value=self.cfg.get("botname", "CITL Assistant"))
        ttk.Label(bar, textvariable=self.botname_var, font=("TkDefaultFont", 10, "bold")).pack(side="left", padx=(2, 12))

        ttk.Button(bar, text="Load Modelfile", command=self.on_load_modelfile).pack(side="left", padx=4)
        if _HAS_APP_SYNC:
            ttk.Button(bar, text="USB Sync", command=self.on_open_usb_sync).pack(side="left", padx=4)
        ttk.Separator(bar, orient="vertical").pack(side="left", fill="y", padx=6)

        ttk.Label(bar, text="Theme:").pack(side="left")
        themes = list(_theme.PALETTE_DISPLAY.values()) if _HAS_THEME else ["Default"]
        self.theme_display_var = tk.StringVar(value=self._saved_theme_display())
        self.theme_combo = ttk.Combobox(bar, textvariable=self.theme_display_var, values=themes, state="readonly", width=34)
        self.theme_combo.pack(side="left", padx=4)
        self.theme_combo.bind("<<ComboboxSelected>>", self.on_theme_changed)

    def _saved_theme_display(self) -> str:
        if not _HAS_THEME:
            return "Default"
        key = self.cfg.get("theme", "ops")
        return _theme.PALETTE_DISPLAY.get(key, _theme.PALETTE_DISPLAY["ops"])

    def _pick_modelfiles_dir(self) -> Path:
        # Prefer configured/env/default path, but survive broken symlinks/non-dir paths.
        cands: List[Path] = []
        cfg_dir = str(self.cfg.get("modelfiles_dir", "") or "").strip()
        env_dir = str(os.environ.get("CITL_MODELFILES_DIR", "") or "").strip()
        for raw in (cfg_dir, env_dir):
            if raw:
                cands.append(Path(raw).expanduser())
        cands.extend([MODELFILES_DIR, DATA_DIR / "modelfiles", Path.home() / ".citl_modelfiles"])

        seen = set()
        uniq: List[Path] = []
        for p in cands:
            key = str(p)
            if key in seen:
                continue
            seen.add(key)
            uniq.append(p)

        for p in uniq:
            try:
                # Broken symlink like ~/CITL_Modelfiles -> missing USB path.
                if p.is_symlink() and not p.exists():
                    continue
                if p.exists():
                    if p.is_dir():
                        return p
                    continue
                p.mkdir(parents=True, exist_ok=True)
                if p.is_dir():
                    return p
            except Exception:
                continue

        fallback = DATA_DIR / "modelfiles_fallback"
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback

    def _modelfiles_dir(self) -> Path:
        p = self._pick_modelfiles_dir()
        if getattr(self, "modelfiles_dir", None) != p:
            self.modelfiles_dir = p
            self.cfg["modelfiles_dir"] = str(p)
            _save_cfg(self.cfg)
            if hasattr(self, "mdl_log"):
                _append(self.mdl_log, f"[PATH] Using Modelfiles dir: {p}\n")
        return p

    def _sync_script_path(self) -> Path:
        return HERE / "citl_app_sync.py"

    def on_open_usb_sync(self) -> None:
        script = self._sync_script_path()
        if not script.exists():
            messagebox.showerror("USB Sync", f"Sync utility not found: {script}")
            return
        try:
            subprocess.Popen([sys.executable, str(script), "--source", "auto"])
        except Exception as e:
            messagebox.showerror("USB Sync", f"Failed to launch sync utility: {e}")

    def _maybe_offer_usb_sync(self) -> None:
        if not _HAS_APP_SYNC:
            return
        if getattr(self, "_usb_sync_offer_done", False):
            return
        self._usb_sync_offer_done = True

        auto = str(self.cfg.get("auto_offer_usb_sync", "1")).strip().lower()
        if auto in ("0", "false", "no", "off"):
            return

        today = time.strftime("%Y-%m-%d")

        def _worker():
            try:
                targets = _discover_sync_targets(REPO_ROOT)
            except Exception:
                return
            if not targets:
                return

            paths = [str(getattr(t, "path", t)) for t in targets[:3]]
            offer_key = "|".join(paths)
            if (
                str(self.cfg.get("usb_sync_last_offer_date", "")) == today
                and str(self.cfg.get("usb_sync_last_offer_key", "")) == offer_key
            ):
                return

            def _prompt():
                preview = "\n".join(f"- {p}" for p in paths)
                ok = messagebox.askyesno(
                    "USB CITL Sync",
                    (
                        f"Detected {len(targets)} external CITL repo target(s):\n\n"
                        f"{preview}\n\n"
                        "Open CITL App Sync utility now?"
                    ),
                )
                self.cfg["usb_sync_last_offer_date"] = today
                self.cfg["usb_sync_last_offer_key"] = offer_key
                _save_cfg(self.cfg)
                if ok:
                    self.on_open_usb_sync()

            self.after(0, _prompt)

        threading.Thread(target=_worker, daemon=True).start()

    # ── Tab 1: Factbook ────────────────────────────────────────────────────
    def _build_factbook_tab(self) -> None:
        tab = ttk.Frame(self.notebook, padding=8)
        self.notebook.add(tab, text=" Factbook ")

        top = ttk.LabelFrame(tab, text="Query", padding=6)
        top.pack(fill="x")

        ttk.Label(top, text="Ollama model:").grid(row=0, column=0, sticky="w")
        self.fb_model_var = tk.StringVar(value=self.cfg.get("ollama_model", "mistral:7b-instruct"))
        self.fb_model_combo = ttk.Combobox(
            top,
            textvariable=self.fb_model_var,
            state="readonly",
            width=34,
            values=(self.fb_model_var.get(),),
        )
        self.fb_model_combo.grid(row=0, column=1, sticky="ew", padx=4)
        self.fb_model_combo.bind("<<ComboboxSelected>>", self.on_operational_model_selected)
        ttk.Button(top, text="Refresh Models", command=self.on_refresh_models).grid(row=0, column=2, sticky="w", padx=(8, 0))
        ttk.Button(top, text="Load Model JSON", command=self.on_load_model_json).grid(row=0, column=3, sticky="w", padx=4)

        ttk.Label(top, text="Host:").grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.fb_host_var = tk.StringVar(value=self.cfg.get("ollama_host", "http://localhost:11434"))
        ttk.Entry(top, textvariable=self.fb_host_var, width=28).grid(row=1, column=1, columnspan=3, sticky="ew", padx=4, pady=(6, 0))

        top.columnconfigure(1, weight=1)
        top.columnconfigure(3, weight=1)

        ttk.Label(top, text="Question:").grid(row=2, column=0, sticky="nw", pady=(6, 0))
        self.fb_question = tk.Text(top, height=3, wrap="word")
        self.fb_question.grid(row=2, column=1, columnspan=3, sticky="ew", padx=4, pady=(6, 0))

        btn_row = ttk.Frame(top)
        btn_row.grid(row=3, column=0, columnspan=4, sticky="w", pady=(4, 0))
        ttk.Button(btn_row, text="Ask Factbook", command=self.on_ask_factbook).pack(side="left")
        ttk.Button(btn_row, text="→ Translate Answer", command=self.on_send_factbook_to_translate).pack(side="left", padx=8)

        self.fb_status_var = tk.StringVar(value="Ready.")
        ttk.Label(tab, textvariable=self.fb_status_var).pack(anchor="w", pady=(6, 0))

        # Corpus health badge — updated after every health scan
        self.fb_health_var = tk.StringVar(value="Corpus: not yet scanned  |  run Corpus Health tab to validate")
        self.fb_health_label = ttk.Label(tab, textvariable=self.fb_health_var,
                                         foreground="gray")
        self.fb_health_label.pack(anchor="w", pady=(0, 2))

        self.fb_out = scrolledtext.ScrolledText(tab, height=22, wrap="word")
        self.fb_out.pack(fill="both", expand=True, pady=(4, 0))

        # Optional JSON model list persisted in config.
        self._json_model_path = (self.cfg.get("model_list_json", "") or "").strip()
        self._json_model_names: List[str] = []
        if self._json_model_path:
            self._json_model_names = self._extract_model_names_from_json(self._json_model_path)
        self.on_refresh_models()

    def _normalize_host(self, host: str) -> str:
        host = (host or "").strip() or "http://127.0.0.1:11434"
        if "://" not in host:
            host = "http://" + host
        return host.rstrip("/")

    def _fetch_ollama_model_names(self, host: str) -> List[str]:
        url = f"{self._normalize_host(host)}/api/tags"
        req = Request(url, headers={"Accept": "application/json"})
        with urlopen(req, timeout=3.5) as r:
            data = json.loads(r.read().decode("utf-8", errors="ignore"))
        out: List[str] = []
        if isinstance(data, dict):
            for item in (data.get("models") or []):
                if isinstance(item, dict):
                    name = (item.get("name") or "").strip()
                    if name:
                        out.append(name)
        return out

    def _extract_model_names_obj(self, obj) -> List[str]:
        out: List[str] = []
        if isinstance(obj, str):
            s = obj.strip()
            if s:
                out.append(s)
            return out
        if isinstance(obj, list):
            for item in obj:
                out.extend(self._extract_model_names_obj(item))
            return out
        if isinstance(obj, dict):
            for key in ("name", "model", "id"):
                val = obj.get(key)
                if isinstance(val, str) and val.strip():
                    out.append(val.strip())
            for key in ("models", "model_names", "names", "items", "data"):
                if key in obj:
                    out.extend(self._extract_model_names_obj(obj.get(key)))
        return out

    def _extract_model_names_from_json(self, path: str) -> List[str]:
        try:
            raw = json.loads(Path(path).read_text(encoding="utf-8"))
        except Exception:
            return []
        names = self._extract_model_names_obj(raw)
        cleaned: List[str] = []
        seen = set()
        for name in names:
            key = name.lower()
            if key in seen:
                continue
            seen.add(key)
            cleaned.append(name)
        return cleaned

    def _rank_model_name(self, name: str) -> tuple:
        low = name.lower()
        # Keep AllenAI models at the top when present.
        return (0 if "allenai" in low else 1, low)

    def on_load_model_json(self) -> None:
        path = filedialog.askopenfilename(
            title="Select model list JSON",
            filetypes=[("JSON", "*.json"), ("All files", "*.*")],
        )
        if not path:
            return
        names = self._extract_model_names_from_json(path)
        if not names:
            messagebox.showerror("Model JSON", "No model names found in that JSON file.")
            return
        self._json_model_path = path
        self._json_model_names = names
        self.cfg["model_list_json"] = path
        _save_cfg(self.cfg)
        self.on_refresh_models()
        self.fb_status_var.set(f"Loaded {len(names)} model name(s) from JSON.")

    def on_refresh_models(self) -> None:
        host = self.fb_host_var.get().strip()
        current = self.fb_model_var.get().strip()
        json_names = list(self._json_model_names)

        self.fb_status_var.set("Loading model list...")

        def _worker():
            fetched: List[str] = []
            err = ""
            try:
                fetched = self._fetch_ollama_model_names(host)
            except Exception as e:
                err = str(e)

            merged = fetched + json_names
            if current:
                merged.append(current)
            merged.append(str(self.cfg.get("last_custom_model", "") or ""))
            merged.append(str(self.cfg.get("last_base_model", "") or ""))
            for saved in (self.cfg.get("saved_grafted_models", []) or []):
                merged.append(str(saved or "").strip())
            if hasattr(self, "m_from"):
                merged.append(self.m_from.get().strip())
            if hasattr(self, "m_name"):
                merged.append(self.m_name.get().strip())

            # De-dup while keeping preferred ordering.
            unique = {}
            for name in merged:
                n = (name or "").strip()
                if not n:
                    continue
                key = n.lower()
                if key not in unique:
                    unique[key] = n

            final = sorted(unique.values(), key=self._rank_model_name)
            if not final:
                final = [current or "mistral:7b-instruct"]

            def _apply():
                self.fb_model_combo["values"] = tuple(final)
                if hasattr(self, "m_from_combo"):
                    self.m_from_combo["values"] = tuple(final)
                if hasattr(self, "m_operational_combo"):
                    self.m_operational_combo["values"] = tuple(final)
                now = self.fb_model_var.get().strip()
                if not now or now not in final:
                    self.fb_model_var.set(final[0])
                if hasattr(self, "m_from"):
                    base_now = self.m_from.get().strip()
                    if not base_now or base_now not in final:
                        self.m_from.set(final[0])
                if err and not fetched:
                    self.fb_status_var.set(f"Model list loaded from JSON/current value only ({err}).")
                else:
                    src = "Ollama"
                    if json_names:
                        src += " + JSON"
                    self.fb_status_var.set(f"Loaded {len(final)} model(s) from {src}.")

            self.after(0, _apply)

        threading.Thread(target=_worker, daemon=True).start()

    def on_operational_model_selected(self, _evt=None) -> None:
        model = self.fb_model_var.get().strip()
        if not model:
            return
        self.cfg["ollama_model"] = model
        self.cfg["last_custom_model"] = model
        self._remember_grafted_model(model)
        _save_cfg(self.cfg)

    def on_base_model_selected(self, _evt=None) -> None:
        base = self.m_from.get().strip()
        if not base:
            return
        self.cfg["last_base_model"] = base
        _save_cfg(self.cfg)

    def on_set_operational_from_new_name(self) -> None:
        name = self.m_name.get().strip()
        if not name:
            return
        self.fb_model_var.set(name)
        self.on_operational_model_selected()

    def _remember_grafted_model(self, model_name: str) -> None:
        name = (model_name or "").strip()
        if not name:
            return
        models = [str(x).strip() for x in (self.cfg.get("saved_grafted_models", []) or []) if str(x).strip()]
        keyset = {m.lower() for m in models}
        if name.lower() not in keyset:
            models.append(name)
        self.cfg["saved_grafted_models"] = models

    def _model_name_from_modelfile_path(self, path: str) -> str:
        name = Path(path).name
        if name.lower().startswith("modelfile."):
            return name.split(".", 1)[1].strip()
        if name.lower() == "modelfile":
            return ""
        return Path(path).stem.strip()

    def _apply_modelfile_profile(self, path: str, content: str, meta: dict) -> None:
        self.m_path.set(path)

        base = _mf.get_model_base(content) if _HAS_MODELFILE else None
        system = _mf.get_system_prompt(content) if _HAS_MODELFILE else None
        guessed_name = self._model_name_from_modelfile_path(path)

        if guessed_name:
            self.m_name.set(guessed_name)
            self.fb_model_var.set(guessed_name)
            self.cfg["ollama_model"] = guessed_name
            self.cfg["last_custom_model"] = guessed_name
            self._remember_grafted_model(guessed_name)

        if base:
            self.m_from.set(base)
        if system:
            self.m_system.delete("1.0", "end")
            self.m_system.insert("end", system.rstrip() + "\n")

        if meta.get("botname"):
            self.botname_var.set(meta["botname"])
            self.m_bot.set(meta["botname"])
            self.cfg["botname"] = meta["botname"]
        if _HAS_THEME and meta.get("color"):
            key = meta["color"].lower()
            if key in _theme.PALETTE_NAMES:
                self.theme_display_var.set(_theme.PALETTE_DISPLAY[key])
                _theme.apply_theme(self, key)
                self.m_color.set(key)
                self.cfg["theme"] = key
        if _HAS_TR and meta.get("lang"):
            lang_name = _tr.LANGUAGES.get(meta["lang"].lower())
            if lang_name:
                self.tr_from_var.set(lang_name)
            self.m_lang.set(meta["lang"].lower())

        self.cfg["last_modelfile_path"] = path
        if base:
            self.cfg["last_base_model"] = base
        if guessed_name:
            self.cfg["last_custom_model"] = guessed_name
        if system:
            self.cfg["last_system_prompt"] = system
        _save_cfg(self.cfg)

    def _auto_graft_last_model_if_needed(self, model_name: str, modelfile_path: str) -> None:
        auto = str(self.cfg.get("auto_graft_last_session", "1")).strip().lower()
        if auto in ("0", "false", "no", "off"):
            return
        if not model_name or not modelfile_path:
            return
        if not Path(modelfile_path).exists():
            return

        def _worker():
            try:
                models = self._fetch_ollama_model_names(self.fb_host_var.get().strip())
            except Exception as e:
                self.after(0, lambda: _append(self.mdl_log, f"\nAuto-graft skipped: cannot list models ({e}).\n"))
                return

            if model_name in models:
                return

            exe = _which_ollama()
            if not exe:
                self.after(0, lambda: _append(self.mdl_log, "\nAuto-graft skipped: ollama not found in PATH.\n"))
                return

            self.after(
                0,
                lambda: _run_threaded(
                    self,
                    f"Auto-graft last session model: {model_name}",
                    [exe, "create", model_name, "-f", modelfile_path],
                    REPO_ROOT,
                    self.mdl_log,
                ),
            )

        threading.Thread(target=_worker, daemon=True).start()

    def _restore_last_session_profile(self) -> None:
        # Restore basic model/session fields first.
        if self.cfg.get("last_base_model"):
            self.m_from.set(str(self.cfg.get("last_base_model")).strip())
        if self.cfg.get("last_custom_model"):
            self.m_name.set(str(self.cfg.get("last_custom_model")).strip())
        if self.cfg.get("last_modelfile_path"):
            self.m_path.set(str(self.cfg.get("last_modelfile_path")).strip())
        if self.cfg.get("last_system_prompt"):
            self.m_system.delete("1.0", "end")
            self.m_system.insert("end", str(self.cfg.get("last_system_prompt")).rstrip() + "\n")

        model = (self.cfg.get("ollama_model") or self.cfg.get("last_custom_model") or "").strip()
        if model:
            self.fb_model_var.set(model)

        path = str(self.cfg.get("last_modelfile_path", "") or "").strip()
        if path and _HAS_MODELFILE and Path(path).exists():
            try:
                content, meta = _mf.load_modelfile(path)
                self._apply_modelfile_profile(path, content, meta)
            except Exception:
                pass

        self.on_refresh_models()

        model_name = self.fb_model_var.get().strip() or self.m_name.get().strip()
        self._auto_graft_last_model_if_needed(model_name, self.m_path.get().strip())

    def on_ask_factbook(self) -> None:
        q = self.fb_question.get("1.0", "end").strip()
        if not q:
            return
        model = self.fb_model_var.get().strip()
        host  = self.fb_host_var.get().strip()
        self.fb_status_var.set("Querying Ollama...")
        self.cfg["ollama_model"] = model
        self.cfg["ollama_host"]  = host
        _save_cfg(self.cfg)

        def _run():
            result = _query_factbook(q, model, host)
            self.after(0, lambda: self._show_factbook(q, result))

        threading.Thread(target=_run, daemon=True).start()

    def _show_factbook(self, q: str, text: str) -> None:
        self.fb_out.insert("end", f"\n[Q] {q}\n\n{text}\n{'─'*60}\n")
        self.fb_out.see("end")
        self.fb_status_var.set("Done.")

    def on_send_factbook_to_translate(self) -> None:
        text = self.fb_out.get("1.0", "end").strip()
        if text:
            self.tr_source.delete("1.0", "end")
            self.tr_source.insert("end", text)
        self.notebook.select(2)

    # ── Tab 2: Audio / Transcribe ──────────────────────────────────────────
    def _build_audio_tab(self) -> None:
        tab = ttk.Frame(self.notebook, padding=8)
        self.notebook.add(tab, text=" Audio / Transcribe ")

        mic_box = ttk.LabelFrame(tab, text="Microphone (auto-detect)", padding=8)
        mic_box.pack(fill="x")

        self.device_combo = ttk.Combobox(mic_box, state="readonly")
        self.device_combo.pack(fill="x")
        self.device_combo.bind("<<ComboboxSelected>>", self.on_device_selected)

        btns = ttk.Frame(mic_box)
        btns.pack(fill="x", pady=(6, 0))
        ttk.Button(btns, text="Refresh", command=self.refresh_devices).pack(side="left")
        ttk.Button(btns, text="Reset Saved", command=self.reset_saved_device).pack(side="left", padx=6)
        ttk.Button(btns, text="Diagnostics", command=self.on_diagnostics).pack(side="left", padx=6)

        self.diag_out = scrolledtext.ScrolledText(mic_box, height=6, wrap="word")
        self.diag_out.pack(fill="both", expand=False, pady=(6, 0))

        rec = ttk.Frame(tab)
        rec.pack(fill="x", pady=(10, 6))
        ttk.Button(rec, text="⏺  Start Recording", command=self.on_start).pack(side="left")
        ttk.Button(rec, text="⏹  Stop Recording",  command=self.on_stop).pack(side="left", padx=8)
        ttk.Button(rec, text="Open Recordings Folder", command=self.on_open_recordings_folder).pack(side="left", padx=8)
        ttk.Button(rec, text="Open Last WAV", command=self.on_open_last_wav).pack(side="left", padx=6)

        trans_box = ttk.LabelFrame(tab, text="Transcription (offline Whisper)", padding=8)
        trans_box.pack(fill="x", pady=(6, 6))
        self.lang_var = tk.StringVar(value="English")
        ttk.Label(trans_box, text="Language:").pack(side="left")
        ttk.Combobox(trans_box, textvariable=self.lang_var, state="readonly",
                     values=["Auto", "English", "Spanish", "Arabic"], width=10).pack(side="left", padx=6)
        ttk.Button(trans_box, text="Transcribe Last WAV", command=self.on_transcribe).pack(side="left", padx=6)
        ttk.Button(trans_box, text="→ Translate Transcript", command=self.on_send_transcript_to_translate).pack(side="left", padx=6)

        self.audio_status_var = tk.StringVar(value="Ready.")
        ttk.Label(tab, textvariable=self.audio_status_var).pack(anchor="w", pady=(4, 0))

        self.audio_out = scrolledtext.ScrolledText(tab, height=16, wrap="word")
        self.audio_out.pack(fill="both", expand=True, pady=(4, 0))

    def refresh_devices(self, first_load: bool = False) -> None:
        if not _HAS_AUDIO:
            self.device_combo["values"] = ()
            self.audio_status_var.set("Audio module unavailable.")
            return
        devs = list_audio_devices(self.ffmpeg)
        saved = (self.cfg.get("audio_device", "") or "").strip()

        if saved and saved not in devs:
            saved = ""
            self.cfg["audio_device"] = ""
            _save_cfg(self.cfg)

        self.device_combo["values"] = tuple(devs)
        if devs:
            pick = saved if saved in devs else devs[0]
            self.device_combo.set(pick)
            self.cfg["audio_device"] = pick
            _save_cfg(self.cfg)
            label = "Loaded" if first_load else "Refreshed"
            self.audio_status_var.set(f"{label} {len(devs)} device(s). Config: {CONFIG_PATH.name}")
        else:
            self.device_combo.set("")
            self.audio_status_var.set("No devices detected. Click Diagnostics.")

    def reset_saved_device(self) -> None:
        self.cfg.pop("audio_device", None)
        _save_cfg(self.cfg)
        self.refresh_devices(first_load=False)

    def on_device_selected(self, _evt=None) -> None:
        v = self.device_combo.get().strip()
        self.cfg["audio_device"] = v
        _save_cfg(self.cfg)

    def on_diagnostics(self) -> None:
        self.diag_out.delete("1.0", "end")
        # On Linux, dshow is Windows-only; print a clean note and still show audio_diagnostics.
        if os.name != "nt":
            self.diag_out.insert("end", "NOTE: DirectShow (dshow) is Windows-only; ignore dshow errors on Linux.\n\n")
        if _HAS_AUDIO:
            self.diag_out.insert("end", (audio_diagnostics(self.ffmpeg) or "") + "\n")
        else:
            self.diag_out.insert("end", "Audio diagnostics unavailable.\n")

    def on_start(self) -> None:
        if self.handle is not None:
            return
        if not _HAS_AUDIO:
            messagebox.showerror("Unavailable", "Audio module not installed.")
            return
        dev = self.device_combo.get().strip()
        if not dev:
            messagebox.showerror("No device", "Select a microphone first.")
            return
        ts  = time.strftime("%Y%m%d_%H%M%S")
        out = str(RECORD_DIR / f"recording_{ts}.wav")
        try:
            self.handle   = start_recording(self.ffmpeg, dev, out, samplerate=16000)
            self.last_wav = out
            actual_sr = int(getattr(self.handle, "samplerate", 16000))
            actual_ch = int(getattr(self.handle, "channels", 1))
            self.audio_status_var.set(f"Recording ({actual_sr} Hz, {actual_ch} ch input) → {out}")
        except Exception as e:
            messagebox.showerror("Start failed", str(e))
            self.handle = None
            self.last_wav = None

    def _wav_evidence(self, wav_path: str) -> dict:
        p = Path(wav_path)
        with wave.open(str(p), "rb") as wf:
            channels = int(wf.getnchannels())
            sr = int(wf.getframerate())
            sampwidth = int(wf.getsampwidth())
            nframes = int(wf.getnframes())
            duration = (float(nframes) / float(sr)) if sr > 0 else 0.0

            peak = 0
            rms_peak = 0
            while True:
                data = wf.readframes(4096)
                if not data:
                    break
                if channels > 1:
                    try:
                        data = audioop.tomono(data, sampwidth, 1.0, 0.0)
                    except Exception:
                        pass
                try:
                    peak = max(peak, int(audioop.max(data, sampwidth)))
                    rms_peak = max(rms_peak, int(audioop.rms(data, sampwidth)))
                except Exception:
                    pass

            full_scale = float((1 << (8 * sampwidth - 1)) - 1) if sampwidth > 0 else 32767.0
            peak_dbfs = 20.0 * math.log10(max(1.0, float(peak)) / full_scale)
            rms_dbfs = 20.0 * math.log10(max(1.0, float(rms_peak)) / full_scale)
            return {
                "channels": channels,
                "samplerate": sr,
                "sampwidth": sampwidth,
                "nframes": nframes,
                "duration_sec": duration,
                "peak_dbfs": peak_dbfs,
                "rms_dbfs": rms_dbfs,
                "file_size": p.stat().st_size if p.exists() else 0,
            }

    def on_open_recordings_folder(self) -> None:
        try:
            RECORD_DIR.mkdir(parents=True, exist_ok=True)
            subprocess.Popen(["xdg-open", str(RECORD_DIR)])
        except Exception as e:
            messagebox.showerror("Open folder failed", str(e))

    def on_open_last_wav(self) -> None:
        if not self.last_wav or not Path(self.last_wav).exists():
            messagebox.showinfo("No recording", "No recorded WAV found yet.")
            return
        try:
            subprocess.Popen(["xdg-open", str(self.last_wav)])
        except Exception as e:
            messagebox.showerror("Open WAV failed", str(e))

    def on_stop(self) -> None:
        if self.handle is None:
            self.audio_status_var.set("Not recording.")
            return
        stop_recording(self.handle)
        self.handle = None
        for _ in range(25):
            if self.last_wav and Path(self.last_wav).exists():
                break
            time.sleep(0.1)
        if self.last_wav and Path(self.last_wav).exists():
            try:
                ev = self._wav_evidence(self.last_wav)
                self.audio_status_var.set(
                    f"Saved WAV ({ev['duration_sec']:.1f}s, peak {ev['peak_dbfs']:.1f} dBFS): {self.last_wav}"
                )
                self.audio_out.insert(
                    "end",
                    (
                        f"\n[SAVED] {self.last_wav}\n"
                        f"[WAV] {ev['duration_sec']:.2f}s, {ev['samplerate']} Hz, {ev['channels']} ch, "
                        f"peak {ev['peak_dbfs']:.1f} dBFS, rms {ev['rms_dbfs']:.1f} dBFS, {ev['file_size']} bytes\n"
                    ),
                )
            except Exception:
                self.audio_status_var.set(f"Saved: {self.last_wav}")
                self.audio_out.insert("end", f"\n[SAVED] {self.last_wav}\n")
            self.audio_out.see("end")
        else:
            self.audio_status_var.set("Stopped — WAV not found. Check Diagnostics.")

    def on_transcribe(self) -> None:
        if not self.last_wav or not Path(self.last_wav).exists():
            messagebox.showinfo("No WAV", "Record and stop first.")
            return
        self.audio_status_var.set("Transcribing...")
        def _run():
            try:
                detected, text, seg_count = _transcribe_wav(self.last_wav, self.lang_var.get())
                self.after(0, lambda: self._show_transcript(detected, text, seg_count))
            except Exception as e:
                self.after(0, lambda msg=str(e): self.audio_status_var.set(f"Transcription error: {msg}"))
        threading.Thread(target=_run, daemon=True).start()

    def _show_transcript(self, detected: str, text: str, seg_count: int) -> None:
        transcript_path = None
        if self.last_wav:
            transcript_path = str(Path(self.last_wav).with_suffix(".txt"))
            try:
                Path(transcript_path).write_text(text or "", encoding="utf-8")
            except Exception:
                transcript_path = None

        if text.strip():
            self.audio_out.insert("end", f"\n[TRANSCRIPT lang={detected} segments={seg_count}]\n{text}\n")
            if transcript_path:
                self.audio_out.insert("end", f"[TRANSCRIPT FILE] {transcript_path}\n")
            self.audio_status_var.set(f"Transcribed (lang={detected}, segments={seg_count}).")
        else:
            self.audio_out.insert(
                "end",
                (
                    f"\n[TRANSCRIPT lang={detected} segments={seg_count}]\n"
                    "[No speech detected in recording]\n"
                    "Tip: verify mic gain and that speech level reaches at least around -35 dBFS peak.\n"
                ),
            )
            if transcript_path:
                self.audio_out.insert("end", f"[TRANSCRIPT FILE] {transcript_path}\n")
            self.audio_status_var.set("Transcription complete: no speech detected.")
        self.audio_out.see("end")

    def on_send_transcript_to_translate(self) -> None:
        text = self.audio_out.get("1.0", "end").strip()
        if text:
            self.tr_source.delete("1.0", "end")
            self.tr_source.insert("end", text)
        self.notebook.select(2)

    # ── Tab 3: Translate ───────────────────────────────────────────────────
    def _build_translate_tab(self) -> None:
        tab = ttk.Frame(self.notebook, padding=8)
        self.notebook.add(tab, text=" Translate ")

        lang_names = list(_tr.LANGUAGES.values()) if _HAS_TR else ["English", "Spanish", "Arabic"]

        ctrl = ttk.Frame(tab); ctrl.pack(fill="x")
        ttk.Label(ctrl, text="From:").pack(side="left")
        self.tr_from_var = tk.StringVar(value="English")
        ttk.Combobox(ctrl, textvariable=self.tr_from_var, values=lang_names, state="readonly", width=16).pack(side="left", padx=4)

        ttk.Button(ctrl, text="⇄", width=3, command=self.on_swap_languages).pack(side="left")
        ttk.Label(ctrl, text="To:").pack(side="left", padx=(8, 0))
        self.tr_to_var = tk.StringVar(value="Spanish")
        ttk.Combobox(ctrl, textvariable=self.tr_to_var, values=lang_names, state="readonly", width=16).pack(side="left", padx=4)

        ttk.Separator(ctrl, orient="vertical").pack(side="left", fill="y", padx=8)
        ttk.Button(ctrl, text="▶ Translate", command=self.on_translate).pack(side="left")
        ttk.Button(ctrl, text="Install Pack", command=self.on_install_lang_pack).pack(side="left", padx=6)
        ttk.Button(ctrl, text="Clear", command=self.on_clear_translate).pack(side="left")

        live_frame = ttk.Frame(tab); live_frame.pack(fill="x", pady=(4, 0))
        self.live_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(live_frame, text="Live translation (800 ms debounce)", variable=self.live_var).pack(side="left")

        self.tr_status_var = tk.StringVar(value="")
        ttk.Label(tab, textvariable=self.tr_status_var).pack(anchor="w")

        pane = ttk.PanedWindow(tab, orient="horizontal"); pane.pack(fill="both", expand=True, pady=(4, 0))
        left = ttk.LabelFrame(pane, text="Source text", padding=4); pane.add(left, weight=1)
        self.tr_source = scrolledtext.ScrolledText(left, wrap="word"); self.tr_source.pack(fill="both", expand=True)
        self.tr_source.bind("<KeyRelease>", self._on_tr_source_keyrelease)

        right = ttk.LabelFrame(pane, text="Translation", padding=4); pane.add(right, weight=1)
        self.tr_result = scrolledtext.ScrolledText(right, wrap="word", state="disabled"); self.tr_result.pack(fill="both", expand=True)

        vocab = ttk.LabelFrame(tab, text="Vocabulary / Study Pairs", padding=4); vocab.pack(fill="x", pady=(6, 0))
        self.tr_vocab = scrolledtext.ScrolledText(vocab, height=5, wrap="word", state="disabled"); self.tr_vocab.pack(fill="both", expand=True)

    def _code_for(self, display_name: str) -> str:
        if not _HAS_TR:
            return display_name[:2].lower()
        return next((k for k, v in _tr.LANGUAGES.items() if v == display_name), "en")

    def on_translate(self) -> None:
        if not _HAS_TR:
            messagebox.showinfo("Unavailable", "citl_translation / argostranslate not installed.")
            return
        text = self.tr_source.get("1.0", "end").strip()
        if not text:
            return
        from_code = self._code_for(self.tr_from_var.get())
        to_code   = self._code_for(self.tr_to_var.get())
        self.tr_status_var.set("Translating...")
        def _run():
            try:
                result = _tr.translate(text, from_code, to_code)
                self.after(0, lambda: self._display_translation(text, result))
            except Exception as e:
                self.after(0, lambda msg=str(e): self._translation_error(msg))
        threading.Thread(target=_run, daemon=True).start()

    def _display_translation(self, source: str, result: str) -> None:
        self.tr_result.configure(state="normal")
        self.tr_result.delete("1.0", "end")
        self.tr_result.insert("end", result)
        self.tr_result.configure(state="disabled")
        self.tr_status_var.set("Translation complete.")
        try:
            pairs = _tr.build_study_pairs(source, result) if _HAS_TR else []
            self.tr_vocab.configure(state="normal")
            self.tr_vocab.delete("1.0", "end")
            for a, b in pairs:
                self.tr_vocab.insert("end", f"{a}\n  → {b}\n\n")
            self.tr_vocab.configure(state="disabled")
        except Exception:
            pass

    def _translation_error(self, msg: str) -> None:
        self.tr_status_var.set(f"Error: {msg}")

    def on_swap_languages(self) -> None:
        a, b = self.tr_from_var.get(), self.tr_to_var.get()
        self.tr_from_var.set(b); self.tr_to_var.set(a)

    def on_clear_translate(self) -> None:
        self.tr_source.delete("1.0", "end")
        self.tr_result.configure(state="normal"); self.tr_result.delete("1.0", "end"); self.tr_result.configure(state="disabled")
        self.tr_vocab.configure(state="normal"); self.tr_vocab.delete("1.0", "end"); self.tr_vocab.configure(state="disabled")
        self.tr_status_var.set("")

    def on_install_lang_pack(self) -> None:
        if not _HAS_TR:
            messagebox.showinfo("Unavailable", "citl_translation / argostranslate not installed.")
            return
        from_code = self._code_for(self.tr_from_var.get())
        to_code   = self._code_for(self.tr_to_var.get())
        self.tr_status_var.set(f"Installing {from_code} → {to_code} ...")
        def _run():
            status = _tr.install_pair(from_code, to_code, progress_cb=lambda m: self.after(0, lambda msg=m: self.tr_status_var.set(msg)))
            self.after(0, lambda: self.tr_status_var.set(status))
        threading.Thread(target=_run, daemon=True).start()

    def _on_tr_source_keyrelease(self, _evt=None) -> None:
        if not getattr(self, "live_var", tk.BooleanVar(value=False)).get():
            return
        if self._live_translate_id:
            self.after_cancel(self._live_translate_id)
        self._live_translate_id = self.after(800, self._live_translate_debounced)

    def _live_translate_debounced(self) -> None:
        self._live_translate_id = None
        self.on_translate()

    # ── Tab 4: Library / Models (RESTORED) ──────────────────────────────────
    def _build_library_models_tab(self) -> None:
        tab = ttk.Frame(self.notebook, padding=8)
        self.notebook.add(tab, text=" Library / Models ")

        # ---- Index management ----
        idx = ttk.LabelFrame(tab, text="RAG Index / Corpus", padding=8)
        idx.pack(fill="x")

        row = ttk.Frame(idx); row.pack(fill="x")
        ttk.Button(row, text="Add Books (txt/docx/pdf)", command=self.on_add_books).pack(side="left")
        ttk.Button(row, text="Refresh Library Index", command=self.on_refresh_library_index).pack(side="left", padx=6)
        ttk.Button(row, text="Rebuild Factbook Index", command=self.on_rebuild_factbook_index).pack(side="left", padx=6)
        ttk.Button(row, text="Rebuild Corpus Index", command=self.on_rebuild_corpus_index).pack(side="left", padx=6)
        ttk.Button(row, text="Verify Index Health", command=self.on_verify_index).pack(side="left", padx=6)
        ttk.Button(row, text="Export Sandbox Bundle", command=self.on_export_sandbox_bundle).pack(side="left", padx=6)
        if _HAS_APP_SYNC:
            ttk.Button(row, text="USB App Sync", command=self.on_open_usb_sync).pack(side="left", padx=6)

        self.idx_log = scrolledtext.ScrolledText(idx, height=10, wrap="word", state="disabled")
        self.idx_log.pack(fill="both", expand=False, pady=(6, 0))

        # ---- Modelfile + Ollama ----
        mdl = ttk.LabelFrame(tab, text="Modelfile → Ollama grafting", padding=8)
        mdl.pack(fill="both", expand=True, pady=(10, 0))

        form = ttk.Frame(mdl); form.pack(fill="x")
        ttk.Label(form, text="Bot name:").grid(row=0, column=0, sticky="w")
        self.m_bot = tk.StringVar(value=self.cfg.get("botname", "CITL Assistant"))
        ttk.Entry(form, textvariable=self.m_bot, width=28).grid(row=0, column=1, sticky="ew", padx=4)

        ttk.Label(form, text="CITL-COLOR:").grid(row=0, column=2, sticky="w", padx=(10,0))
        self.m_color = tk.StringVar(value=self.cfg.get("theme","ops"))
        colors = list(_theme.PALETTE_NAMES) if _HAS_THEME else ["ops","amber","green","c64","sinclair","cga"]
        ttk.Combobox(form, textvariable=self.m_color, values=colors, state="readonly", width=14).grid(row=0, column=3, sticky="w", padx=4)

        ttk.Label(form, text="CITL-LANG:").grid(row=0, column=4, sticky="w", padx=(10,0))
        self.m_lang = tk.StringVar(value="en")
        ttk.Entry(form, textvariable=self.m_lang, width=6).grid(row=0, column=5, sticky="w", padx=4)

        ttk.Label(form, text="Operational model:").grid(row=1, column=0, sticky="w", pady=(6,0))
        self.m_operational_combo = ttk.Combobox(
            form,
            textvariable=self.fb_model_var,
            state="readonly",
            width=28,
            values=(self.fb_model_var.get(),),
        )
        self.m_operational_combo.grid(row=1, column=1, sticky="ew", padx=4, pady=(6,0))
        self.m_operational_combo.bind("<<ComboboxSelected>>", self.on_operational_model_selected)

        self.m_from = tk.StringVar(value=self.fb_model_var.get() if hasattr(self,"fb_model_var") else "mistral:7b-instruct")
        ttk.Label(form, text="Base model (FROM):").grid(row=2, column=0, sticky="w", pady=(6,0))
        self.m_from_combo = ttk.Combobox(
            form,
            textvariable=self.m_from,
            state="readonly",
            width=28,
            values=(self.m_from.get(),),
        )
        self.m_from_combo.grid(row=2, column=1, sticky="ew", padx=4, pady=(6,0))
        self.m_from_combo.bind("<<ComboboxSelected>>", self.on_base_model_selected)

        ttk.Label(form, text="New model name:").grid(row=2, column=2, sticky="w", padx=(10,0), pady=(6,0))
        self.m_name = tk.StringVar(value="citl-custom")
        ttk.Entry(form, textvariable=self.m_name, width=22).grid(row=2, column=3, sticky="w", padx=4, pady=(6,0))
        ttk.Button(form, text="Set As Operational", command=self.on_set_operational_from_new_name).grid(row=2, column=4, sticky="w", padx=4, pady=(6,0))

        ttk.Label(form, text="Modelfile path:").grid(row=3, column=0, sticky="w", pady=(6,0))
        self.m_path = tk.StringVar(value=str(self._modelfiles_dir() / "Modelfile.sample"))
        ttk.Entry(form, textvariable=self.m_path).grid(row=3, column=1, columnspan=3, sticky="ew", padx=4, pady=(6,0))
        ttk.Button(form, text="Browse", command=self.on_browse_modelfile).grid(row=3, column=4, sticky="w", padx=4, pady=(6,0))
        ttk.Button(form, text="Open Folder", command=self.on_open_modelfiles_dir).grid(row=3, column=5, sticky="w", padx=4, pady=(6,0))

        form.columnconfigure(1, weight=1)
        form.columnconfigure(3, weight=0)

        sysbox = ttk.LabelFrame(mdl, text="SYSTEM prompt (written into Modelfile)", padding=6)
        sysbox.pack(fill="both", expand=True, pady=(10, 0))
        self.m_system = scrolledtext.ScrolledText(sysbox, height=7, wrap="word")
        self.m_system.pack(fill="both", expand=True)
        if not self.m_system.get("1.0","end").strip():
            seed = (self.cfg.get("last_system_prompt", "") or "").strip()
            self.m_system.insert("end", (seed or DEFAULT_MODEFILE_SYSTEM_PROMPT).rstrip() + "\n")

        btnrow = ttk.Frame(mdl); btnrow.pack(fill="x", pady=(8,0))
        ttk.Button(btnrow, text="Write Modelfile", command=self.on_write_modelfile).pack(side="left")
        ttk.Button(btnrow, text="Ollama: List", command=self.on_ollama_list).pack(side="left", padx=6)
        ttk.Button(btnrow, text="Ollama: Pull FROM", command=self.on_ollama_pull_from).pack(side="left", padx=6)
        ttk.Button(btnrow, text="Ollama: Create/Update", command=self.on_ollama_create).pack(side="left", padx=6)

        self.mdl_log = scrolledtext.ScrolledText(mdl, height=10, wrap="word", state="disabled")
        self.mdl_log.pack(fill="both", expand=False, pady=(8,0))
        self.on_refresh_models()

    def on_add_books(self) -> None:
        # Canonical home for all library documents.
        lib = HERE / "data" / "library_raw"
        lib.mkdir(parents=True, exist_ok=True)

        files = filedialog.askopenfilenames(
            title="Select books to add to corpus",
            initialdir=str(lib),          # always opens to the library home
            filetypes=[
                ("Text/Docs", "*.txt *.docx *.pdf *.md"),
                ("All files", "*.*"),
            ],
        )
        if not files:
            return

        copied = 0
        new_paths: List[Path] = []
        for f in files:
            try:
                src = Path(f)
                dst = lib / src.name
                if not dst.exists():
                    shutil.copy2(src, dst)
                    copied += 1
                new_paths.append(dst)
            except Exception as e:
                _append(self.idx_log, f"  [WARN] Could not copy {Path(f).name}: {e}\n")

        _append(self.idx_log,
                f"\nAdded {copied} file(s) to: {lib}\n"
                "Auto-indexing new files...\n")

        # Immediately build deterministic JSONL indexes for the new books.
        def _index_worker():
            try:
                from citl_auto_index import index_file
                total = 0
                for p in new_paths:
                    n = index_file(p, force=True)
                    if n:
                        self.after(0, lambda name=p.name, c=n:
                            _append(self.idx_log, f"  Indexed {name}: {c} chunks\n"))
                        total += n
                if total:
                    self.after(0, lambda t=total:
                        _append(self.idx_log,
                                f"Auto-index complete: {t} total chunks ready.\n"))
            except Exception as e:
                self.after(0, lambda: _append(self.idx_log,
                                              f"  [WARN] Auto-index error: {e}\n"))

        threading.Thread(target=_index_worker, daemon=True).start()

    def on_refresh_library_index(self) -> None:
        """Force-rebuild JSONL indexes for every file in data/library_raw/."""
        _append(self.idx_log, "\n== Refresh Library Index ==\n")

        def _worker():
            try:
                from citl_auto_index import auto_index_library, LIB_RAW, IDX_DIR
                results = auto_index_library(lib_dir=LIB_RAW, idx_dir=IDX_DIR, force=True)
                if results:
                    self.after(0, lambda: _append(
                        self.idx_log,
                        "".join(f"  {n}: {c} chunks\n" for n, c in results.items())
                        + f"Done. {sum(results.values())} total chunks indexed.\n",
                    ))
                else:
                    self.after(0, lambda: _append(
                        self.idx_log, "All indexes are current — nothing rebuilt.\n"))
            except Exception as e:
                self.after(0, lambda: _append(self.idx_log, f"[ERROR] {e}\n"))

        threading.Thread(target=_worker, daemon=True).start()

    def on_rebuild_factbook_index(self) -> None:
        script = HERE / "build_factbook_index.py"
        if not script.exists():
            _append(self.idx_log, "\nERROR: build_factbook_index.py not found.\n")
            return
        _run_threaded(self, "Rebuild Factbook Index", [sys.executable, str(script)], HERE, self.idx_log)

    def on_rebuild_corpus_index(self) -> None:
        script = HERE / "build_corpus_index.py"
        if not script.exists():
            _append(self.idx_log, "\nERROR: build_corpus_index.py not found.\n")
            return
        _run_threaded(self, "Rebuild Corpus Index", [sys.executable, str(script)], HERE, self.idx_log)

    def on_verify_index(self) -> None:
        # Quick sanity check of common embedding files
        candidates = [
            HERE / "factbook_embeddings.json",
            HERE / "dictionary_embeddings.json",
            HERE / "law_embeddings.json",
            HERE / "nursing_embeddings.json",
        ]
        _append(self.idx_log, "\n== Index Health ==\n")
        for p in candidates:
            if not p.exists():
                _append(self.idx_log, f"Missing: {p.name}\n")
                continue
            try:
                import numpy as np
                obj = json.loads(p.read_text(encoding="utf-8"))
                # best-effort shape detection
                emb = obj.get("embeddings") if isinstance(obj, dict) else None
                if emb is None and isinstance(obj, list):
                    emb = obj
                if emb:
                    a = np.array(emb, dtype=float)
                    _append(self.idx_log, f"{p.name}: OK shape={a.shape}\n")
                else:
                    _append(self.idx_log, f"{p.name}: present but embeddings not detected\n")
            except Exception as e:
                _append(self.idx_log, f"{p.name}: ERROR {e}\n")

    def on_export_sandbox_bundle(self) -> None:
        script = REPO_ROOT / "scripts" / "demo" / "hive_off_bot_cli.py"
        if not script.exists():
            _append(self.idx_log, "\nERROR: scripts/demo/hive_off_bot_cli.py not found.\n")
            return

        model = (self.m_name.get().strip() if hasattr(self, "m_name") else "") or self.fb_model_var.get().strip() or "citl-demo-bot"
        base = (self.m_from.get().strip() if hasattr(self, "m_from") else "") or "olmo2:13b"
        safe_model = re.sub(r"[^a-zA-Z0-9_.:-]+", "-", model).strip("-") or "citl-demo-bot"
        outdir = REPO_ROOT / "data" / "sandbox_bots" / safe_model.replace(":", "-")

        cmd = [
            sys.executable,
            str(script),
            "--model-name",
            safe_model,
            "--base-model",
            base,
            "--outdir",
            str(outdir),
            "--write-modelfile",
        ]
        _run_threaded(self, f"Export Sandbox Bundle ({safe_model})", cmd, REPO_ROOT, self.idx_log)

    def on_browse_modelfile(self) -> None:
        modelfiles_dir = self._modelfiles_dir()
        path = filedialog.askopenfilename(
            initialdir=str(modelfiles_dir if modelfiles_dir.exists() else Path.home()),

            title="Select Modelfile",
            filetypes=[("Modelfile", "Modelfile*"), ("All files", "*.*")]
        )
        if path:
            self.m_path.set(path)

    def on_open_modelfiles_dir(self) -> None:
        modelfiles_dir = self._modelfiles_dir()
        # Linux
        try:
            subprocess.Popen(["xdg-open", str(modelfiles_dir)])
        except Exception:
            pass

    def _parse_ollama_list_names(self, text: str) -> List[str]:
        names: List[str] = []
        for line in (text or "").splitlines():
            ln = line.strip()
            if not ln:
                continue
            if ln.lower().startswith("name "):
                continue
            parts = ln.split()
            if parts:
                names.append(parts[0].strip())
        return names

    def _verify_graft_async(self, model_name: str) -> None:
        exe = _which_ollama()
        if not exe or not model_name:
            return

        def _worker():
            time.sleep(2.0)
            try:
                p = subprocess.run(
                    [exe, "list"],
                    cwd=str(REPO_ROOT),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    errors="replace",
                    check=False,
                )
                txt = _clean_cli_text((p.stdout or ""))
                names = self._parse_ollama_list_names(txt)
                want = {model_name, f"{model_name}:latest"}
                hit = next((n for n in names if n in want), None)
                if hit:
                    self.after(0, lambda: _append(self.mdl_log, f"[VERIFY] Graft saved and available: {hit}\n"))
                else:
                    self.after(
                        0,
                        lambda: _append(
                            self.mdl_log,
                            f"[VERIFY] WARNING: {model_name} not found in `ollama list` yet. "
                            "Run `Ollama: List` to recheck.\n",
                        ),
                    )
            except Exception as e:
                self.after(0, lambda: _append(self.mdl_log, f"[VERIFY] ERROR: could not verify grafted model ({e})\n"))

        threading.Thread(target=_worker, daemon=True).start()

    def _ensure_modelfile_for_create(self) -> Optional[str]:
        mf = self.m_path.get().strip()
        if mf and Path(mf).exists():
            return mf

        name = self.m_name.get().strip() or "citl-custom"
        modelfiles_dir = self._modelfiles_dir()
        auto_path = modelfiles_dir / f"Modelfile.{name}"
        self.m_path.set(str(auto_path))
        _append(self.mdl_log, f"[AUTO] Modelfile missing; writing new Modelfile at {auto_path}\n")
        try:
            self.on_write_modelfile()
        except Exception as e:
            _append(self.mdl_log, f"[AUTO] ERROR writing Modelfile: {e}\n")
            return None

        mf2 = self.m_path.get().strip()
        if mf2 and Path(mf2).exists():
            size = Path(mf2).stat().st_size
            _append(self.mdl_log, f"[AUTO] Modelfile ready: {mf2} ({size} bytes)\n")
            return mf2
        _append(self.mdl_log, "[AUTO] ERROR: Modelfile still missing after write.\n")
        return None

    def on_write_modelfile(self) -> None:
        modelfiles_dir = self._modelfiles_dir()
        try:
            modelfiles_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            _append(self.mdl_log, f"\nERROR: Could not create Modelfiles directory '{modelfiles_dir}': {e}\n")
            return
        bot = self.m_bot.get().strip() or "CITL Bot"
        color = (self.m_color.get().strip() or "ops").lower()
        lang = (self.m_lang.get().strip() or "en").lower()
        base = self.m_from.get().strip() or "mistral:7b-instruct"
        system = self.m_system.get("1.0","end").strip() or DEFAULT_MODEFILE_SYSTEM_PROMPT.strip()

        # file name derived from model name
        name = self.m_name.get().strip() or "citl-custom"
        out = modelfiles_dir / f"Modelfile.{name}"
        self.m_path.set(str(out))

        content = (
            f"# CITL-BOTNAME: {bot}\n"
            f"# CITL-COLOR: {color}\n"
            f"# CITL-LANG: {lang}\n"
            f"# CITL-DESC: generated by CITL GUI\n"
            f"FROM {base}\n"
            f"SYSTEM \"\"\"\n{system}\n\"\"\"\n"
        )
        out.write_text(content, encoding="utf-8")

        self.cfg["botname"] = bot
        self.cfg["theme"] = color
        self.cfg["last_base_model"] = base
        self.cfg["last_custom_model"] = name
        self.cfg["last_modelfile_path"] = str(out)
        self.cfg["last_system_prompt"] = system
        self._remember_grafted_model(name)
        _save_cfg(self.cfg)

        self.fb_model_var.set(name)
        self.cfg["ollama_model"] = name
        _save_cfg(self.cfg)
        self.on_refresh_models()
        _append(self.mdl_log, f"\nWrote Modelfile: {out}\n")
        _append(self.mdl_log, f"[SAVE] FROM={base}  MODEL={name}\n")

    def on_ollama_list(self) -> None:
        exe = _which_ollama()
        if not exe:
            _append(self.mdl_log, "\nERROR: ollama not found in PATH.\n")
            return
        _run_threaded(self, "ollama list", [exe, "list"], REPO_ROOT, self.mdl_log)

    def on_ollama_pull_from(self) -> None:
        exe = _which_ollama()
        if not exe:
            _append(self.mdl_log, "\nERROR: ollama not found in PATH.\n")
            return
        base = self.m_from.get().strip()
        if not base:
            _append(self.mdl_log, "\nERROR: Base model is empty.\n")
            return
        _run_threaded(self, f"ollama pull {base}", [exe, "pull", base], REPO_ROOT, self.mdl_log)

    def on_ollama_create(self) -> None:
        exe = _which_ollama()
        if not exe:
            _append(self.mdl_log, "\nERROR: ollama not found in PATH.\n")
            return
        name = self.m_name.get().strip()
        if not name:
            _append(self.mdl_log, "\nERROR: New model name is empty.\n")
            return
        mf = self._ensure_modelfile_for_create()
        if not mf:
            _append(
                self.mdl_log,
                "\nERROR: Modelfile path missing or not found, and auto-write did not succeed.\n",
            )
            return
        _append(self.mdl_log, f"[CREATE] model={name}  modelfile={mf}\n")
        self.fb_model_var.set(name)
        self.cfg["ollama_model"] = name
        self.cfg["last_custom_model"] = name
        self.cfg["last_modelfile_path"] = mf
        self._remember_grafted_model(name)
        _save_cfg(self.cfg)
        self.on_refresh_models()
        _run_threaded(self, f"ollama create {name}", [exe, "create", name, "-f", mf], REPO_ROOT, self.mdl_log)
        self._verify_graft_async(name)
        self.after(4000, self.on_refresh_models)

    # ── Theme / Modelfile load (existing) ──────────────────────────────────
    def _apply_saved_theme(self) -> None:
        if not _HAS_THEME:
            return
        key = self.cfg.get("theme", "ops")
        _theme.apply_theme(self, key)

    def on_theme_changed(self, _evt=None) -> None:
        if not _HAS_THEME:
            return
        display = self.theme_display_var.get()
        key = next((k for k, v in _theme.PALETTE_DISPLAY.items() if v == display), "ops")
        _theme.apply_theme(self, key)
        self.cfg["theme"] = key
        _save_cfg(self.cfg)

    def on_load_modelfile(self) -> None:
        if not _HAS_MODELFILE:
            messagebox.showinfo("Unavailable", "citl_modelfile module not found.")
            return
        modelfiles_dir = self._modelfiles_dir()
        path = filedialog.askopenfilename(
            initialdir=str(modelfiles_dir if modelfiles_dir.exists() else Path.home()),

            title="Select Modelfile",
            filetypes=[("Modelfile", "Modelfile*"), ("All files", "*.*")]
        )
        if not path:
            return
        try:
            content, meta = _mf.load_modelfile(path)
        except Exception as e:
            messagebox.showerror("Load failed", str(e))
            return
        self._apply_modelfile_profile(path, content, meta)
        self.on_refresh_models()
        self._auto_graft_last_model_if_needed(self.fb_model_var.get().strip(), path)
        _save_cfg(self.cfg)
        messagebox.showinfo("Modelfile loaded", f"Bot: {meta.get('botname')}\nColor: {meta.get('color')}\nLang: {meta.get('lang')}")

    # ── Tab 5: Corpus Health ───────────────────────────────────────────────

    def _build_corpus_health_tab(self) -> None:
        tab = ttk.Frame(self.notebook, padding=8)
        self.notebook.add(tab, text=" Corpus Health ")

        # Control row
        ctrl = ttk.Frame(tab)
        ctrl.pack(fill="x")
        self.ch_scan_btn = ttk.Button(ctrl, text="Run Health Scan",
                                      command=self.on_run_corpus_health)
        self.ch_scan_btn.pack(side="left")
        self.ch_status_var = tk.StringVar(value="Not yet scanned.")
        ttk.Label(ctrl, textvariable=self.ch_status_var).pack(side="left", padx=(12, 0))

        # Legend
        legend = ttk.Frame(tab)
        legend.pack(fill="x", pady=(4, 0))
        for color, label in (("green", "OK"), ("orange", "WARNING"), ("red", "ERROR")):
            f = tk.Frame(legend, bg=color, width=12, height=12)
            f.pack(side="left", padx=(0, 2))
            ttk.Label(legend, text=label).pack(side="left", padx=(0, 10))
        ttk.Label(legend, text="(results update the badge on the Factbook tab)",
                  foreground="gray").pack(side="left")

        # Summary panel
        summary_frame = ttk.LabelFrame(tab, text="Health Summary", padding=6)
        summary_frame.pack(fill="x", pady=(8, 0))
        self.ch_summary = scrolledtext.ScrolledText(
            summary_frame, height=7, wrap="word", state="disabled")
        self.ch_summary.pack(fill="both", expand=False)

        # Detail panel
        detail_frame = ttk.LabelFrame(tab, text="Detail", padding=6)
        detail_frame.pack(fill="both", expand=True, pady=(6, 0))
        self.ch_detail = scrolledtext.ScrolledText(
            detail_frame, height=18, wrap="word", state="disabled")
        self.ch_detail.pack(fill="both", expand=True)

    def on_run_corpus_health(self) -> None:
        if not _HAS_CORPUS_HEALTH:
            _append(self.ch_detail,
                    "[ERROR] citl_corpus_health module not available.\n")
            return

        from factbook_db import DEFAULT_DB_PATH
        source_path = HERE / "factbook.txt"
        db_path = DEFAULT_DB_PATH

        self.ch_status_var.set("Scanning …")
        self.ch_scan_btn.configure(state="disabled")
        _append(self.ch_detail, "\n== Corpus Health Scan ==\n")

        def _worker():
            try:
                report = _ch.scan_corpus_health(source_path, db_path)
            except Exception as e:
                self.after(0, lambda: self._on_health_scan_error(str(e)))
                return
            self.after(0, lambda r=report: self._on_health_scan_done(r))

        threading.Thread(target=_worker, daemon=True).start()

    def _on_health_scan_done(self, report) -> None:
        self._corpus_health_report = report
        self.ch_scan_btn.configure(state="normal")
        self.ch_status_var.set(
            f"Last scan: {report.timestamp}  |  Status: {report.overall_status}")

        # ── Summary widget ────────────────────────────────────────────────
        self.ch_summary.configure(state="normal")
        self.ch_summary.delete("1.0", "end")
        self.ch_summary.insert("end",
            f"Overall status : {report.overall_status}\n"
            f"Scan time      : {report.timestamp}\n\n")
        for note in report.notes:
            self.ch_summary.insert("end", f"  • {note}\n")
        self.ch_summary.configure(state="disabled")

        # ── Detail widget ─────────────────────────────────────────────────
        lines: List[str] = []

        # Field coverage — the primary quality metric
        if report.field_coverage:
            db = report.db
            lines.append(
                f"\n── Field Coverage  ({db.country_count} countries in DB) ───────────────")
            w = max(len(r.field) for r in report.field_coverage)
            for r in report.field_coverage:
                bar_filled = int(r.pct / 5)       # 20 chars = 100 %
                bar = "█" * bar_filled + "░" * (20 - bar_filled)
                flag = "OK  " if r.pct >= 60 else ("WARN" if r.pct >= 30 else "ERR ")
                gaps = (f"  missing e.g.: {', '.join(r.sample_gaps[:3])}"
                        if r.sample_gaps else "")
                lines.append(
                    f"  [{flag}]  {r.field:<{w}}  {bar}  {r.pct:5.1f}%"
                    f"  ({r.count}/{r.total}){gaps}")

        # Embedding shapes
        if report.embeddings:
            lines.append("\n── Embedding Files ──────────────────────────────")
            for e in report.embeddings:
                if not e.exists:
                    lines.append(f"  [MISS ]  {e.name}")
                elif e.error:
                    lines.append(f"  [WARN ]  {e.name}  {e.error}")
                else:
                    lines.append(f"  [OK   ]  {e.name}"
                                 f"  {e.vec_count:,} × {e.vec_dim}d"
                                 f"  ({e.size_bytes/1_048_576:.1f} MB)")

        # Corpus source files
        lines.append("\n── Corpus Source Files ──────────────────────────")
        for cf in report.corpus_files:
            flag = "OK   " if cf.exists else "MISS "
            lines.append(
                f"  [{flag}]  {cf.name}"
                f"  profile={cf.detected_profile}"
                f"  {cf.size_bytes:,} B  ~{cf.word_count_approx:,} words"
                + (f"\n           {cf.error}" if cf.error else ""))

        # Index files
        lines.append("\n── JSONL Index Files ────────────────────────────")
        for idx in report.indexes:
            flag = "OK   " if idx.exists else "MISS "
            schema_ok = f"  ({idx.valid_records}/{idx.record_count} valid records)" if idx.exists else ""
            lines.append(
                f"  [{flag}]  {idx.name}{schema_ok}"
                + (f"\n           {idx.error}" if idx.error else ""))

        # Smoke tests
        lines.append("\n── Smoke Tests (full pipeline) ──────────────────")
        for st in report.smoke_tests:
            flag = "PASS" if st.answered else "FAIL"
            lines.append(
                f"  [{flag}]  {st.question}  ({st.elapsed_sec:.2f}s)\n"
                f"           {st.snippet}")

        _append(self.ch_detail, "\n".join(lines) + "\n")
        self._update_health_badge(report)

    def _on_health_scan_error(self, msg: str) -> None:
        self.ch_scan_btn.configure(state="normal")
        self.ch_status_var.set("Scan failed.")
        _append(self.ch_detail, f"[ERROR] Health scan failed: {msg}\n")

    def _update_health_badge(self, report) -> None:
        smoke_pass  = sum(1 for s in report.smoke_tests if s.answered)
        smoke_total = len(report.smoke_tests)
        db = report.db
        text = (
            f"Corpus: {report.overall_status}"
            f"  |  {db.country_count:,} countries / {db.section_count:,} sections"
            f"  |  {len(report.indexes)} index file(s)"
            + (f"  |  smoke {smoke_pass}/{smoke_total}" if smoke_total else "")
            + (f"  ← last scan {report.timestamp}" )
        )
        self.fb_health_var.set(text)
        color_map = {"OK": "#2e7d32", "WARNING": "#e65100", "ERROR": "#c62828"}
        self.fb_health_label.configure(foreground=color_map.get(report.overall_status, "gray"))

    # ── Startup auto-index ────────────────────────────────────────────────

    def _auto_index_on_startup(self) -> None:
        """On launch, silently rebuild any stale JSONL indexes in library_raw/."""
        def _worker():
            try:
                from citl_auto_index import auto_index_library, LIB_RAW, IDX_DIR
                results = auto_index_library(lib_dir=LIB_RAW, idx_dir=IDX_DIR)
                if results:
                    summary = ", ".join(f"{n}: {c} chunks" for n, c in results.items())
                    self.after(0, lambda s=summary:
                        _append(self.idx_log, f"\n[Auto-index] Rebuilt: {s}\n"))
            except Exception as e:
                self.after(0, lambda: _append(self.idx_log,
                                              f"\n[Auto-index] {e}\n"))
        threading.Thread(target=_worker, daemon=True).start()

    # ── Tick ───────────────────────────────────────────────────────────────
    def _tick(self) -> None:
        self.after(1000, self._tick)

def main() -> None:
    App().mainloop()

# === CITL_PATCH_MODEL_DROPDOWN_V1 ============================================
# This block is injected automatically by CITL_FIX_BOTBUILDER_AND_MODEL_DROPDOWN.sh
# Purpose:
#  - Replace free-text Ollama model Entry with a dropdown of local models (/api/tags)
#  - Optionally upgrade "Base model (FROM)" to dropdown too
#  - Support "--tab models" etc. so a Bot Builder launcher can open the right tab
# ============================================================================
import sys as _citl_sys
import json as _citl_json
import threading as _citl_threading

def _citl__http_get_json(url: str, timeout: float = 2.5):
    try:
        from urllib.request import urlopen, Request
        req = Request(url, headers={"Accept": "application/json"})
        with urlopen(req, timeout=timeout) as r:
            return _citl_json.loads(r.read().decode("utf-8"))
    except Exception:
        return None

def _citl__normalize_host(host: str) -> str:
    host = (host or "").strip()
    if not host:
        # env default
        host = os.environ.get("OLLAMA_HOST", "").strip()
    if not host:
        host = "http://127.0.0.1:11434"
    if "://" not in host:
        host = "http://" + host
    return host.rstrip("/")

def _citl__ollama_models(host: str):
    host = _citl__normalize_host(host)
    data = _citl__http_get_json(f"{host}/api/tags")
    models = []
    if isinstance(data, dict):
        for m in data.get("models", []) or []:
            name = (m or {}).get("name")
            if name:
                models.append(name)
    # stable, de-dup
    seen = set()
    out = []
    for m in sorted(models, key=lambda s: s.lower()):
        if m not in seen:
            seen.add(m); out.append(m)
    return out

def _citl__walk_widgets(root):
    # DFS walk Tk widget tree
    stack = [root]
    out = []
    while stack:
        w = stack.pop()
        out.append(w)
        try:
            stack.extend(list(w.winfo_children()))
        except Exception:
            pass
    return out

def _citl__widget_text(w):
    # label/button text across tk/ttk
    try:
        return (w.cget("text") or "").strip()
    except Exception:
        return ""

def _citl__grid_find_sibling(parent, row, col):
    for ch in parent.winfo_children():
        try:
            gi = ch.grid_info()
        except Exception:
            continue
        if not gi:
            continue
        try:
            r = int(gi.get("row", -999))
            c = int(gi.get("column", -999))
        except Exception:
            continue
        if r == row and c == col:
            return ch
    return None

def _citl__try_replace_entry_with_combo(app, label_regex, host_regex, prefer_same_row=True):
    """
    Find a label matching label_regex (e.g. 'Ollama model'),
    then find the Entry next to it, replace with readonly Combobox.
    Also tries to add a Refresh button at col+2 if empty.
    """
    try:
        import tkinter as tk
        from tkinter import ttk
    except Exception:
        return False

    # root guess
    root = getattr(app, "root", None) or getattr(app, "master", None) or tk._default_root
    if root is None:
        return False

    widgets = _citl__walk_widgets(root)

    # Find host entry by label text (Host:)
    host_entry = None
    for w in widgets:
        t = _citl__widget_text(w)
        if t and re.search(host_regex, t, re.IGNORECASE):
            try:
                gi = w.grid_info()
                parent = w.master
                row = int(gi.get("row", -1))
                col = int(gi.get("column", -1))
                cand = _citl__grid_find_sibling(parent, row, col+1)
                if cand is not None:
                    host_entry = cand
                    break
            except Exception:
                continue

    # Find target label + entry
    for w in widgets:
        t = _citl__widget_text(w)
        if not t:
            continue
        if not re.search(label_regex, t, re.IGNORECASE):
            continue

        try:
            gi = w.grid_info()
            parent = w.master
            row = int(gi.get("row", -1))
            col = int(gi.get("column", -1))
        except Exception:
            continue

        entry = _citl__grid_find_sibling(parent, row, col+1)
        if entry is None and prefer_same_row:
            # fallback: nearest widget on same row with higher column
            best = None
            best_col = 10**9
            for ch in parent.winfo_children():
                try:
                    cgi = ch.grid_info()
                    r = int(cgi.get("row", -999))
                    c = int(cgi.get("column", -999))
                except Exception:
                    continue
                if r == row and c > col and c < best_col:
                    best = ch; best_col = c
            entry = best

        if entry is None:
            continue

        # Only replace if it looks like an Entry/Combobox-like input (has get())
        if not hasattr(entry, "get"):
            continue

        # Capture geometry + padding
        try:
            egi = entry.grid_info()
            sticky = egi.get("sticky", "ew")
            padx = egi.get("padx", 0)
            pady = egi.get("pady", 0)
        except Exception:
            sticky, padx, pady = "ew", 0, 0

        # Get existing value
        try:
            cur_val = entry.get().strip()
        except Exception:
            cur_val = ""

        # If entry is already a Combobox, just refresh values
        # (we still want readonly + values)
        if entry.winfo_class().lower().endswith("combobox"):
            combo = entry
        else:
            # Preserve textvariable if any
            tv = ""
            try:
                tv = entry.cget("textvariable") or ""
            except Exception:
                tv = ""

            # Create combo in same grid cell
            combo = ttk.Combobox(parent, state="readonly")
            if tv:
                try:
                    combo.configure(textvariable=tv)
                except Exception:
                    pass

            combo.grid(row=row, column=col+1, sticky=sticky, padx=padx, pady=pady)

            # Hide old entry
            try:
                entry.grid_remove()
            except Exception:
                try:
                    entry.grid_forget()
                except Exception:
                    pass

            # If app stored the entry as an attribute, swap it to combo for compatibility
            try:
                for k, v in list(vars(app).items()):
                    if v is entry:
                        setattr(app, k, combo)
            except Exception:
                pass

        # Helper: read host string safely
        def read_host():
            # Prefer Host entry if found
            if host_entry is not None and hasattr(host_entry, "get"):
                try:
                    h = host_entry.get().strip()
                    if h:
                        return h
                except Exception:
                    pass
            # Next, try app.host_var if exists
            hv = getattr(app, "host_var", None)
            try:
                if hv is not None:
                    h = hv.get().strip()
                    if h:
                        return h
            except Exception:
                pass
            # fallback env/default
            return ""

        # Populate models asynchronously
        def do_refresh():
            host = read_host()
            models = _citl__ollama_models(host)
            def apply():
                try:
                    combo["values"] = models
                except Exception:
                    return
                # keep current if valid else set first
                try:
                    now = combo.get().strip()
                except Exception:
                    now = ""
                if models:
                    if now not in models:
                        # If we preserved textvariable, combo.get may already be value; set anyway
                        try:
                            combo.set(models[0])
                        except Exception:
                            pass
                else:
                    # keep current text if any
                    if cur_val:
                        try:
                            combo.set(cur_val)
                        except Exception:
                            pass
            try:
                root.after(0, apply)
            except Exception:
                apply()

        _citl_threading.Thread(target=do_refresh, daemon=True).start()

        # Set initial value if present
        if cur_val:
            try:
                combo.set(cur_val)
            except Exception:
                pass

        # Add Refresh button if the grid slot is free (col+2)
        try:
            existing = _citl__grid_find_sibling(parent, row, col+2)
            if existing is None:
                btn = ttk.Button(parent, text="Refresh", command=lambda: _citl_threading.Thread(target=do_refresh, daemon=True).start())
                btn.grid(row=row, column=col+2, sticky="w")
        except Exception:
            pass

        # Bind host entry events to refresh
        try:
            if host_entry is not None:
                host_entry.bind("<Return>", lambda e: _citl_threading.Thread(target=do_refresh, daemon=True).start())
                host_entry.bind("<FocusOut>", lambda e: _citl_threading.Thread(target=do_refresh, daemon=True).start())
        except Exception:
            pass

        return True

    return False

def _citl__select_tab_by_arg(app):
    # Parse argv without argparse (no dependency on existing parser)
    argv = list(_citl_sys.argv)
    if "--tab" not in argv:
        return
    try:
        i = argv.index("--tab")
        val = (argv[i+1] if i+1 < len(argv) else "").strip().lower()
    except Exception:
        return
    if not val:
        return

    # Map to substrings to match tab text
    want = {
        "factbook": ["factbook"],
        "audio": ["audio", "transcribe"],
        "translate": ["translate"],
        "models": ["library", "models", "modelfile"],
        "builder": ["library", "models", "modelfile"],
    }.get(val, [val])

    try:
        import tkinter as tk
        from tkinter import ttk
    except Exception:
        return

    root = getattr(app, "root", None) or getattr(app, "master", None) or tk._default_root
    if root is None:
        return

    # Find any Notebook and select tab whose text contains any 'want' substring
    for w in _citl__walk_widgets(root):
        try:
            cls = w.winfo_class()
        except Exception:
            continue
        if "Notebook" not in cls:
            continue
        try:
            tabs = w.tabs()
        except Exception:
            continue
        for tab_id in tabs:
            try:
                text = (w.tab(tab_id, "text") or "").strip().lower()
            except Exception:
                text = ""
            if not text:
                continue
            if any(s in text for s in want):
                try:
                    w.select(tab_id)
                except Exception:
                    pass
                return

def _citl__enhance_ui(app):
    # Native dropdown support now exists in the main UI code.
    if hasattr(app, "fb_model_combo") and hasattr(app, "on_refresh_models"):
        try:
            app.on_refresh_models()
        except Exception:
            pass
        _citl__select_tab_by_arg(app)
        return True

    # 1) Upgrade Ollama model field to dropdown
    ok1 = _citl__try_replace_entry_with_combo(
        app,
        label_regex=r"ollama\s*model",
        host_regex=r"host\s*:",
        prefer_same_row=True,
    )

    # 2) Upgrade Base model (FROM) field to dropdown (if present)
    ok2 = _citl__try_replace_entry_with_combo(
        app,
        label_regex=r"base\s*model.*from",
        host_regex=r"host\s*:",
        prefer_same_row=True,
    )

    # 3) Support --tab models (for Bot Builder launcher)
    _citl__select_tab_by_arg(app)
    return ok1 or ok2

def _citl__wrap_app_init():
    # Wrap App.__init__ so enhancements apply without touching original layout code
    g = globals()
    App = g.get("App")
    if App is None:
        return
    if getattr(App, "_citl_wrapped_init", False):
        return

    orig_init = App.__init__
    def wrapped_init(self, *a, **kw):
        orig_init(self, *a, **kw)
        try:
            _citl__enhance_ui(self)
        except Exception as e:
            try:
                print(f"[CITL_PATCH] enhance_ui failed: {e}")
            except Exception:
                pass

    App.__init__ = wrapped_init
    App._citl_wrapped_init = True

try:
    import os as _citl_os  # ensure os available for normalize_host default
    _citl__wrap_app_init()
except Exception:
    pass
# === END CITL_PATCH_MODEL_DROPDOWN_V1 ========================================

# === CITL_PATCH_TEMPLATES_ONLINE_V1 ==========================================
# Adds:
#  - CITL menu: Apply Template..., Collect Public Posts...
# Notes:
#  - Collector uses Playwright and DOES NOT bypass login/CAPTCHA/anti-bot.
# ============================================================================
import json as _citl_json2
import glob as _citl_glob2
import subprocess as _citl_subprocess2
import threading as _citl_threading2

def _citl2__walk(root):
    st=[root]; out=[]
    while st:
        w=st.pop()
        out.append(w)
        try: st.extend(list(w.winfo_children()))
        except Exception: pass
    return out

def _citl2__wtext(w):
    try: return (w.cget("text") or "").strip()
    except Exception: return ""

def _citl2__grid_sib(parent, row, col):
    for ch in parent.winfo_children():
        try: gi=ch.grid_info()
        except Exception: continue
        if not gi: continue
        try:
            r=int(gi.get("row",-999)); c=int(gi.get("column",-999))
        except Exception:
            continue
        if r==row and c==col:
            return ch
    return None

def _citl2__find_input_by_label(app, label_regex):
    import tkinter as tk
    root = getattr(app, "root", None) or getattr(app, "master", None) or tk._default_root
    if root is None: return None
    for w in _citl2__walk(root):
        t=_citl2__wtext(w)
        if not t: continue
        if not re.search(label_regex, t, re.IGNORECASE): continue
        try:
            gi=w.grid_info(); parent=w.master
            row=int(gi.get("row",-1)); col=int(gi.get("column",-1))
        except Exception:
            continue
        # prefer immediate right sibling
        inp=_citl2__grid_sib(parent, row, col+1)
        if inp is not None and hasattr(inp, "get"):
            return inp
    return None

def _citl2__find_text_widget_near_label(app, label_regex):
    import tkinter as tk
    root = getattr(app, "root", None) or getattr(app, "master", None) or tk._default_root
    if root is None: return None
    for w in _citl2__walk(root):
        t=_citl2__wtext(w)
        if not t: continue
        if not re.search(label_regex, t, re.IGNORECASE): continue
        parent = w.master
        # find a tk.Text under same parent
        for ch in parent.winfo_children():
            try:
                if ch.winfo_class() == "Text":
                    return ch
            except Exception:
                pass
        # fallback: any Text in descendants
        for ch in _citl2__walk(parent):
            try:
                if ch.winfo_class() == "Text":
                    return ch
            except Exception:
                pass
    # last resort: first Text in whole UI
    for w in _citl2__walk(root):
        try:
            if w.winfo_class() == "Text":
                return w
        except Exception:
            pass
    return None

def _citl2__templates_dir():
    return os.path.expanduser("~/.local/share/citl/templates")

def _citl2__list_templates():
    d=_citl2__templates_dir()
    files=sorted(_citl_glob2.glob(os.path.join(d,"*.json")))
    out=[]
    for fp in files:
        try:
            obj=_citl_json2.loads(Path(fp).read_text(encoding="utf-8"))
            name=obj.get("name") or os.path.basename(fp)
            out.append((name, fp))
        except Exception:
            continue
    return out

def _citl2__apply_template(app, template_path):
    import tkinter as tk
    from pathlib import Path
    obj=_citl_json2.loads(Path(template_path).read_text(encoding="utf-8"))
    base=obj.get("base_model","").strip()
    sys_prompt=obj.get("system_prompt","")

    # Locate widgets
    base_inp=_citl2__find_input_by_label(app, r"base\s*model.*from")
    sys_text=_citl2__find_text_widget_near_label(app, r"system\s*prompt")

    # Apply base model
    if base and base_inp is not None:
        try:
            # Combobox supports set()
            if hasattr(base_inp, "set"):
                base_inp.set(base)
            else:
                base_inp.delete(0, "end")
                base_inp.insert(0, base)
        except Exception:
            pass

    # Apply system prompt (Text widget)
    if sys_text is not None and sys_prompt:
        try:
            sys_text.delete("1.0", "end")
            sys_text.insert("1.0", sys_prompt)
        except Exception:
            pass

    # Optional: CITL color/lang
    col=obj.get("citl_color","").strip()
    lang=obj.get("citl_lang","").strip()
    if col:
        w=_citl2__find_input_by_label(app, r"citl-color")
        if w is not None:
            try:
                if hasattr(w,"set"): w.set(col)
                else:
                    w.delete(0,"end"); w.insert(0,col)
            except Exception: pass
    if lang:
        w=_citl2__find_input_by_label(app, r"citl-lang")
        if w is not None:
            try:
                w.delete(0,"end"); w.insert(0,lang)
            except Exception: pass

def _citl2__popup_apply_template(app):
    import tkinter as tk
    from tkinter import ttk, messagebox

    root = getattr(app, "root", None) or getattr(app, "master", None) or tk._default_root
    if root is None: return

    tpl=_citl2__list_templates()
    if not tpl:
        messagebox.showerror("CITL", "No templates found in ~/.local/share/citl/templates")
        return

    win=tk.Toplevel(root)
    win.title("Apply Bot Builder Template")
    win.geometry("520x160")

    ttk.Label(win, text="Template:").pack(anchor="w", padx=12, pady=(12,4))

    names=[n for n,_ in tpl]
    var=tk.StringVar(value=names[0])
    cb=ttk.Combobox(win, state="readonly", values=names, textvariable=var)
    cb.pack(fill="x", padx=12)

    def do_apply():
        name=var.get()
        fp=dict(tpl).get(name)
        try:
            _citl2__apply_template(app, fp)
            messagebox.showinfo("CITL", f"Applied: {name}")
            win.destroy()
        except Exception as e:
            messagebox.showerror("CITL", f"Failed: {e}")

    ttk.Button(win, text="Apply", command=do_apply).pack(pady=14)
    ttk.Label(win, text="Tip: templates set Base model + System prompt.").pack(pady=(0,10))

def _citl2__popup_collect_public_posts(app):
    import tkinter as tk
    from tkinter import ttk, messagebox

    root = getattr(app, "root", None) or getattr(app, "master", None) or tk._default_root
    if root is None: return

    win=tk.Toplevel(root)
    win.title("Collect Public Posts (X Search, No API)")
    win.geometry("560x240")

    frm=ttk.Frame(win); frm.pack(fill="both", expand=True, padx=12, pady=12)

    ttk.Label(frm, text="Keyword / phrase:").grid(row=0, column=0, sticky="w")
    kw=tk.StringVar(value="")
    ttk.Entry(frm, textvariable=kw).grid(row=1, column=0, sticky="ew", pady=(0,10))

    ttk.Label(frm, text="Limit (best effort):").grid(row=2, column=0, sticky="w")
    lim=tk.StringVar(value="50")
    ttk.Entry(frm, textvariable=lim, width=10).grid(row=3, column=0, sticky="w", pady=(0,10))

    headful=tk.BooleanVar(value=False)
    ttk.Checkbutton(frm, text="Headful (show browser window)", variable=headful).grid(row=4, column=0, sticky="w", pady=(0,10))

    status=tk.StringVar(value="Ready.")
    ttk.Label(frm, textvariable=status).grid(row=6, column=0, sticky="w")

    frm.columnconfigure(0, weight=1)

    def worker():
        k=kw.get().strip()
        if not k:
            root.after(0, lambda: messagebox.showerror("CITL","Keyword required"))
            return
        try:
            n=int(lim.get().strip() or "50")
        except Exception:
            n=50
        status.set("Collecting (public pages only; no bypass)...")

        # Call local collector script
        collector=os.path.expanduser("~/.local/bin/citl_collect_public_x.py")
        if not os.path.exists(collector):
            root.after(0, lambda: messagebox.showerror("CITL","Collector script missing: ~/.local/bin/citl_collect_public_x.py"))
            return

        cmd=[sys.executable, collector, "--keyword", k, "--limit", str(n)]
        if headful.get():
            cmd.append("--headful")

        try:
            out=_citl_subprocess2.check_output(cmd, stderr=_citl_subprocess2.STDOUT, text=True)
        except _citl_subprocess2.CalledProcessError as e:
            root.after(0, lambda: messagebox.showerror("CITL", f"Collect failed:\n{e.output}"))
            status.set("Failed.")
            return

        # Optionally reindex if build script exists next to GUI
        try:
            appdir=os.path.dirname(__file__)
            build=os.path.join(appdir, "build_corpus_index.py")
            if os.path.exists(build):
                status.set("Collected. Rebuilding corpus index...")
                _citl_subprocess2.check_call([sys.executable, build], cwd=appdir)
                status.set("Done: collected + reindexed.")
            else:
                status.set("Done: collected (no reindex script found).")
        except Exception as e:
            status.set("Collected, but reindex failed.")
            root.after(0, lambda: messagebox.showwarning("CITL", f"Collected but reindex failed:\n{e}"))

        root.after(0, lambda: messagebox.showinfo("CITL", f"Collect finished.\n\n{out.strip()}"))

    def start():
        _citl_threading2.Thread(target=worker, daemon=True).start()

    ttk.Button(frm, text="Run Collection", command=start).grid(row=5, column=0, sticky="w")

def _citl2__install_menu(app):
    import tkinter as tk
    root = getattr(app, "root", None) or getattr(app, "master", None) or tk._default_root
    if root is None: return
    try:
        import tkinter.ttk as ttk  # noqa
    except Exception:
        pass

    # Create or extend menu bar
    menubar = root["menu"] if "menu" in root.keys() and root["menu"] else None
    if not menubar:
        menubar = tk.Menu(root)
        root.config(menu=menubar)

    # Avoid duplicate menu
    try:
        for i in range(menubar.index("end") + 1):
            if menubar.type(i) == "cascade" and menubar.entrycget(i, "label") == "CITL":
                return
    except Exception:
        pass

    m = tk.Menu(menubar, tearoff=0)
    m.add_command(label="Apply Template...", command=lambda: _citl2__popup_apply_template(app))
    m.add_command(label="Collect Public Posts...", command=lambda: _citl2__popup_collect_public_posts(app))
    menubar.add_cascade(label="CITL", menu=m)

def _citl2__wrap_app_init():
    g=globals()
    App=g.get("App")
    if App is None: return
    if getattr(App, "_citl2_wrapped_init", False): return
    orig=App.__init__
    def wrap(self, *a, **kw):
        orig(self, *a, **kw)
        try:
            _citl2__install_menu(self)
        except Exception as e:
            try: print(f"[CITL_PATCH] menu install failed: {e}")
            except Exception: pass
    App.__init__=wrap
    App._citl2_wrapped_init=True

try:
    _citl2__wrap_app_init()
except Exception:
    pass
# === END CITL_PATCH_TEMPLATES_ONLINE_V1 ======================================

# === CITL_PATCH_STARTTAB_WMCLASS_V1 ==========================================
# Purpose:
#  - Allow a dedicated Bot Builder launcher to:
#     (a) open directly to the Library/Models tab, and
#     (b) appear as a DISTINCT dock icon (different WM_CLASS)
#
# Inputs:
#  - CLI:  --tab factbook|audio|translate|models
#  - CLI:  --wmclass <string>
#  - ENV:  CITL_START_TAB, CITL_WMCLASS
#
# Design:
#  - runs AFTER UI is constructed using root.after(...)
# ============================================================================
import os as _citl_os3
import sys as _citl_sys3

def _citl3__argval(flag: str, default: str = "") -> str:
    try:
        argv = list(_citl_sys3.argv)
        if flag in argv:
            i = argv.index(flag)
            return (argv[i+1] if i+1 < len(argv) else default) or default
    except Exception:
        pass
    return default

def _citl3__desired_tab() -> str:
    return (_citl3__argval("--tab","") or _citl_os3.environ.get("CITL_START_TAB","")).strip().lower()

def _citl3__desired_wmclass() -> str:
    return (_citl3__argval("--wmclass","") or _citl_os3.environ.get("CITL_WMCLASS","")).strip()

def _citl3__walk(w):
    out=[w]
    try:
        for ch in w.winfo_children():
            out.extend(_citl3__walk(ch))
    except Exception:
        pass
    return out

def _citl3__select_tab_and_class(app):
    try:
        import tkinter as tk
    except Exception:
        return

    root = getattr(app, "root", None) or getattr(app, "master", None) or tk._default_root
    if root is None:
        return

    tab = _citl3__desired_tab()
    wm  = _citl3__desired_wmclass()

    # Map "models" to common labels in your UI
    tab_map = {
        "factbook": ["factbook"],
        "audio": ["audio", "transcribe"],
        "translate": ["translate"],
        "models": ["library", "models", "modelfile"],
        "builder": ["library", "models", "modelfile"],
        "health": ["corpus health", "health"],
    }
    want = tab_map.get(tab, [tab] if tab else [])

    def apply():
        # Set distinct WM_CLASS for GNOME dock grouping
        if wm:
            try:
                root.wm_class(wm, wm)
            except Exception:
                pass

        if not want:
            return

        for w in _citl3__walk(root):
            try:
                if "Notebook" not in (w.winfo_class() or ""):
                    continue
                tabs = w.tabs()
            except Exception:
                continue

            for tid in tabs:
                try:
                    txt = (w.tab(tid, "text") or "").strip().lower()
                except Exception:
                    txt = ""
                if not txt:
                    continue
                if any(s in txt for s in want):
                    try:
                        w.select(tid)
                    except Exception:
                        pass
                    return

    # Delay ensures the notebook is actually created before we try to select it
    try:
        root.after(350, apply)
    except Exception:
        apply()

def _citl3__wrap_app_init():
    App = globals().get("App")
    if App is None:
        return
    if getattr(App, "_citl3_wrapped_init", False):
        return
    orig = App.__init__
    def wrap(self, *a, **kw):
        orig(self, *a, **kw)
        try:
            _citl3__select_tab_and_class(self)
        except Exception:
            pass
    App.__init__ = wrap
    App._citl3_wrapped_init = True

try:
    _citl3__wrap_app_init()
except Exception:
    pass
# === END CITL_PATCH_STARTTAB_WMCLASS_V1 ======================================




if __name__ == "__main__":
    main()
