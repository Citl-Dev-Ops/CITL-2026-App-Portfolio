"""
CITL FLEX Troubleshooter v1.0
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Standalone IT troubleshooting app built on the CITL Factbook RAG engine.
Indexed from the FLEX Team OneNote PDF corpus.

Tabs:
  1) Ask / Query       — RAG search against the FLEX corpus
  2) IT Diagnostics    — ping, services, ports, disk, network
  3) Ticket Writer     — AI-generated structured IT support tickets
  4) Index Builder     — rebuild/update the FLEX corpus embedding
  5) Models            — Ollama model list, pull, delete, Modelfile editor
  6) Settings          — theme, host, model defaults

Portable: runs from USB. All outputs written to data/ sibling dir.
Modular: each tab has a standalone entry point for separate EXE builds.

Authors:
  Abdo Mohammed        Lead Developer — Factbook AI Engine & RAG Systems
  Wahaj Al Obid        Lead Developer — Academic Advisor v2.0
  Doc McDowell         Project Lead, CITL AI and Systems Architect
  Jerome Anti Porta    Developer — UI/UX, App Integration
  Jonathan Reed        Developer — LLMOps & Model Management
  Peter Anderson       Developer — AV/IT Operations & Network Tools
  Will Cram            Developer — E-Learning Administrator and Software Architect
  William Grainger     Developer — Technical Writing & Documentation Tools
  Mason Jones          Developer — Staff Toolkit & Field Apps

Renton Technical College — CITL
"""
from __future__ import annotations

import json
import math
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import List, Optional
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk
from urllib.request import Request, urlopen

# ── Paths ───────────────────────────────────────────────────────────────────
HERE       = Path(__file__).resolve().parent
REPO_ROOT  = HERE.parent
FA_DIR     = REPO_ROOT / "factbook-assistant"
DATA_DIR   = HERE / "data"
CORPUS     = HERE / "flex_embeddings.json"
MODFILE    = HERE / "Modelfile"
DATA_DIR.mkdir(exist_ok=True)

# ── Optional CITL module imports ─────────────────────────────────────────────
for _p in (str(FA_DIR),):
    if _p not in sys.path:
        sys.path.insert(0, _p)

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
    from citl_corpus_health import scan_corpus_health as _scan_corpus_health
    _HAS_HEALTH = True
except Exception:
    _HAS_HEALTH = False

# ── query_flex backend ───────────────────────────────────────────────────────
try:
    from query_flex import (
        load_corpus, embed_query, top_k as _top_k, gen_with_context,
        OLLAMA_HOST as _DEFAULT_HOST, LLM_MODEL as _DEFAULT_MODEL,
        EMB_MODEL as _DEFAULT_EMB,
    )
    _HAS_QUERY = True
except Exception as _qe:
    _HAS_QUERY = False
    _DEFAULT_HOST  = "http://127.0.0.1:11434"
    _DEFAULT_MODEL = "mistral:7b-instruct"
    _DEFAULT_EMB   = "nomic-embed-text"

# ── Config ───────────────────────────────────────────────────────────────────
_CFG_PATH = HERE / "flex_config.json"

def _load_cfg() -> dict:
    try:
        return json.loads(_CFG_PATH.read_text(encoding="utf-8")) if _CFG_PATH.exists() else {}
    except Exception:
        return {}

def _save_cfg(cfg: dict) -> None:
    try:
        _CFG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    except Exception:
        pass

# ── Ollama helpers ────────────────────────────────────────────────────────────
def _ollama(path: str, payload: dict, host: str, stream: bool = False, timeout: int = 600):
    import urllib.request, urllib.error
    url  = host.rstrip("/") + path
    data = json.dumps(payload).encode()
    req  = Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.URLError as e:
        raise ConnectionError(f"Ollama unreachable at {host}: {e}")
    if stream:
        return resp
    return json.loads(resp.read().decode())

def _list_models(host: str) -> List[str]:
    try:
        j = _ollama("/api/tags", {}, host, timeout=5)
        return [m["name"] for m in j.get("models", [])]
    except Exception:
        return []

def _stream_generate(host: str, model: str, system: str, prompt: str,
                     token_cb, done_cb, err_cb):
    def _run():
        try:
            resp = _ollama("/api/generate",
                           {"model": model, "system": system, "prompt": prompt,
                            "stream": True, "options": {"temperature": 0.15}},
                           host, stream=True)
            for raw_line in resp:
                line = raw_line.decode("utf-8").strip()
                if not line:
                    continue
                try:
                    j = json.loads(line)
                except Exception:
                    continue
                tok = j.get("response", "")
                if tok:
                    token_cb(tok)
                if j.get("done"):
                    break
            done_cb()
        except Exception as e:
            err_cb(str(e))
    threading.Thread(target=_run, daemon=True).start()

# ── Palette (teal_ops default) ────────────────────────────────────────────────
_TEAL_OPS = {
    "bg":         "#071A1E",
    "fg":         "#C8E8EC",
    "accent":     "#00C8A8",
    "highlight":  "#0A3040",
    "button_bg":  "#0D2838",
    "button_fg":  "#B8E8E4",
    "entry_bg":   "#041214",
    "entry_fg":   "#C0E4E8",
    "text_bg":    "#041214",
    "text_fg":    "#B4DCE0",
    "select_bg":  "#005A4A",
    "select_fg":  "#FFFFFF",
    "tab_bg":     "#0A2030",
    "tab_fg":     "#80BCBF",
    "status_fg":  "#00E5C8",
    "cursor":     "#00E5C8",
}

APP_NAME    = "CITL FLEX Troubleshooter"
APP_VERSION = "v1.0"

# ─────────────────────────────────────────────────────────────────────────────
# Main Application
# ─────────────────────────────────────────────────────────────────────────────

class FlexTroubleshooterApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self._cfg = _load_cfg()
        self._palette_name = self._cfg.get("theme", "teal_ops")
        self._host  = self._cfg.get("host",  _DEFAULT_HOST)
        self._model = self._cfg.get("model", _DEFAULT_MODEL)
        self._emb   = self._cfg.get("emb_model", _DEFAULT_EMB)
        self._topk  = int(self._cfg.get("topk", 6))

        self.title(f"{APP_NAME} {APP_VERSION}")
        self.geometry("1100x760")
        self.minsize(820, 580)

        self._apply_theme(self._palette_name)
        self._build_health_bar()

        nb = ttk.Notebook(self)
        nb.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        self._nb = nb

        self._build_query_tab(nb)
        self._build_diagnostics_tab(nb)
        self._build_ticket_tab(nb)
        self._build_index_tab(nb)
        self._build_models_tab(nb)
        self._build_settings_tab(nb)
        self._build_heal_tab(nb)
        self._build_usb_deploy_tab(nb)

        self._statusbar = tk.Label(self, text="Ready — FLEX corpus loaded.",
                                   anchor=tk.W, padx=6, pady=2,
                                   font=("Consolas", 8))
        self._statusbar.pack(fill=tk.X, side=tk.BOTTOM)
        self._theme_status()

    # ── Theme helpers ────────────────────────────────────────────────────────
    def _apply_theme(self, name: str):
        if _HAS_THEME:
            _theme.apply_theme(self, name)
        else:
            p = _TEAL_OPS
            self.configure(bg=p["bg"])
        p = _TEAL_OPS if name == "teal_ops" else _TEAL_OPS
        if _HAS_THEME and hasattr(_theme, "_PALETTES"):
            p = _theme._PALETTES.get(name, _TEAL_OPS)
        self._p = p
        try:
            self._statusbar.configure(
                bg=p.get("tab_bg", "#0A2030"),
                fg=p.get("status_fg", "#00E5C8"))
        except Exception:
            pass

    def _theme_status(self):
        try:
            self._statusbar.configure(
                bg=self._p.get("tab_bg", "#0A2030"),
                fg=self._p.get("status_fg", "#00E5C8"))
        except Exception:
            pass

    def _status(self, msg: str):
        try:
            self._statusbar.configure(text=msg)
        except Exception:
            pass

    # ── Health bar ───────────────────────────────────────────────────────────
    def _build_health_bar(self) -> None:
        BG = "#091820"; DIM = "#4a7a8a"; MID = "#80bcbf"; SEP = "#15303a"
        bar = tk.Frame(self, bg=BG, height=36)
        bar.pack(fill="x", padx=0, pady=0)
        bar.pack_propagate(False)

        tk.Label(bar, text="  SYSTEM STATUS", fg="#00C8A8", bg=BG,
                 font=("Segoe UI", 8, "bold")).pack(side="left", padx=(8, 4))

        def _sep():
            tk.Frame(bar, bg=SEP, width=1, height=22).pack(side="left", padx=6)

        def _indicator(label: str):
            dot = tk.Label(bar, text="●", fg=DIM, bg=BG, font=("Segoe UI", 10))
            dot.pack(side="left", padx=(0, 2))
            tk.Label(bar, text=label, fg=MID, bg=BG,
                     font=("Segoe UI", 8)).pack(side="left", padx=(0, 4))
            return dot

        self._hb_dot_ollama = _indicator("Ollama")
        _sep()
        self._hb_dot_model  = _indicator("LLM")
        _sep()
        self._hb_dot_index  = _indicator("Index")
        _sep()
        self._hb_dot_net    = _indicator("Network")

        self._hb_ts = tk.Label(bar, text="", fg=DIM, bg=BG, font=("Consolas", 7))
        self._hb_ts.pack(side="right", padx=(0, 8))

        tk.Button(
            bar, text="↻", fg="#00C8A8", bg=BG, relief="flat",
            activebackground="#0A2030", activeforeground="#00E5C8",
            font=("Segoe UI", 10), cursor="hand2",
            command=lambda: threading.Thread(
                target=lambda: self._health_bar_poll(force=True),
                daemon=True).start(),
        ).pack(side="right", padx=4)

        self.after(1500, self._health_bar_poll)

    def _health_bar_poll(self, force: bool = False) -> None:
        def _check():
            GREEN = "#00e676"; AMBER = "#ffb300"; RED = "#ff5252"
            state: dict = {}

            # Ollama
            try:
                s = socket.create_connection(("127.0.0.1", 11434), timeout=2)
                s.close()
                state["ollama"] = GREEN
                ollama_ok = True
            except OSError:
                state["ollama"] = RED
                ollama_ok = False

            # LLM model
            if ollama_ok:
                try:
                    models = _list_models(self._host)
                    state["model"] = GREEN if models else AMBER
                except Exception:
                    state["model"] = AMBER
            else:
                state["model"] = RED

            # FLEX Index
            state["index"] = (
                GREEN if CORPUS.exists() and CORPUS.stat().st_size > 1024 else AMBER
            )

            # Network
            try:
                socket.create_connection(("8.8.8.8", 53), timeout=2).close()
                state["net"] = GREEN
            except OSError:
                state["net"] = AMBER

            state["ts"] = datetime.now().strftime("%H:%M:%S")
            self.after(0, lambda s=state: self._health_bar_apply(s))
            if not force:
                self.after(12_000, self._health_bar_poll)

        threading.Thread(target=_check, daemon=True).start()

    def _health_bar_apply(self, state: dict) -> None:
        for key, attr in (
            ("ollama", "_hb_dot_ollama"),
            ("model",  "_hb_dot_model"),
            ("index",  "_hb_dot_index"),
            ("net",    "_hb_dot_net"),
        ):
            try:
                getattr(self, attr).configure(fg=state.get(key, "#888"))
            except Exception:
                pass
        try:
            self._hb_ts.configure(text=f"updated {state.get('ts', '')}")
        except Exception:
            pass

    # ── Widget factory ───────────────────────────────────────────────────────
    def _lf(self, parent, text, expand=False):
        p = self._p
        lf = ttk.LabelFrame(parent, text=text, padding=6)
        lf.pack(fill=tk.BOTH if expand else tk.X, expand=expand, padx=4, pady=3)
        return lf

    def _btn(self, parent, text, cmd, width=None, state="normal"):
        kw = {"command": cmd, "state": state}
        if width:
            kw["width"] = width
        return ttk.Button(parent, text=text, **kw)

    def _log(self, widget: tk.Text, msg: str, tag: str = ""):
        widget.configure(state="normal")
        widget.insert(tk.END, msg, tag)
        widget.see(tk.END)
        widget.configure(state="disabled")

    def _log_clear(self, widget: tk.Text):
        widget.configure(state="normal")
        widget.delete("1.0", tk.END)
        widget.configure(state="disabled")

    def _scrolled_text(self, parent, height=10, state="disabled"):
        p = self._p
        st = scrolledtext.ScrolledText(
            parent, height=height, wrap=tk.WORD, state=state,
            font=("Consolas", 9),
            bg=p.get("text_bg", "#041214"),
            fg=p.get("text_fg", "#B4DCE0"),
            insertbackground=p.get("cursor", "#00E5C8"),
            selectbackground=p.get("select_bg", "#005A4A"),
        )
        # Text tags for coloured output
        st.tag_configure("ok",    foreground="#00E5A0")
        st.tag_configure("warn",  foreground="#F4A261")
        st.tag_configure("err",   foreground="#E63946")
        st.tag_configure("head",  foreground="#00C8A8", font=("Consolas", 9, "bold"))
        st.tag_configure("dim",   foreground="#5A8C8F")
        return st

    # ─────────────────────────────────────────────────────────────────────────
    # TAB 1 — Ask / Query
    # ─────────────────────────────────────────────────────────────────────────
    def _build_query_tab(self, nb):
        f = ttk.Frame(nb, padding=4)
        nb.add(f, text=" Ask FLEX ")

        # Question row
        qf = self._lf(f, "Question")
        self._q_entry = tk.Text(qf, height=3, wrap=tk.WORD,
                                font=("Segoe UI", 10),
                                bg=self._p["entry_bg"], fg=self._p["entry_fg"],
                                insertbackground=self._p["cursor"])
        self._q_entry.pack(fill=tk.X, padx=2, pady=2)
        self._q_entry.bind("<Control-Return>", lambda e: self._do_query())

        # Controls row
        ctrl = ttk.Frame(f)
        ctrl.pack(fill=tk.X, padx=4, pady=2)

        ttk.Label(ctrl, text="Model:").pack(side=tk.LEFT, padx=(0, 4))
        self._q_model_var = tk.StringVar(value=self._model)
        self._q_model_cb = ttk.Combobox(ctrl, textvariable=self._q_model_var,
                                         width=28, state="readonly")
        self._q_model_cb.pack(side=tk.LEFT, padx=4)

        ttk.Label(ctrl, text="Top-K:").pack(side=tk.LEFT, padx=(8, 2))
        self._topk_var = tk.IntVar(value=self._topk)
        ttk.Spinbox(ctrl, from_=1, to=20, textvariable=self._topk_var,
                    width=4).pack(side=tk.LEFT)

        self._ask_btn = self._btn(ctrl, "Ask  [Ctrl+Enter]", self._do_query)
        self._ask_btn.pack(side=tk.LEFT, padx=12)
        self._btn(ctrl, "Clear", lambda: (
            self._q_entry.delete("1.0", tk.END),
            self._log_clear(self._q_out)
        )).pack(side=tk.LEFT)
        self._btn(ctrl, "Refresh Models", self._refresh_models_q).pack(side=tk.RIGHT)

        # Response
        rf = self._lf(f, "Response", expand=True)
        self._q_out = self._scrolled_text(rf, height=20)
        self._q_out.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)

        # source info footer
        sf = ttk.Frame(f)
        sf.pack(fill=tk.X, padx=4, pady=1)
        self._corpus_lbl = ttk.Label(sf, text=self._corpus_status(),
                                      font=("Consolas", 8))
        self._corpus_lbl.pack(side=tk.LEFT)
        self._btn(sf, "Rebuild Index", lambda: self._nb.select(3)).pack(side=tk.RIGHT)

        self._refresh_models_q()

    def _corpus_status(self) -> str:
        if CORPUS.exists():
            sz = CORPUS.stat().st_size
            return f"Corpus: {CORPUS.name}  ({sz//1024:,} KB)"
        return "Corpus: NOT BUILT — go to Index Builder tab"

    def _refresh_models_q(self):
        models = _list_models(self._host)
        if models:
            self._q_model_cb["values"] = models
            if self._q_model_var.get() not in models:
                self._q_model_var.set(models[0])
        self._status(f"Models refreshed — {len(models)} found")

    def _do_query(self):
        q = self._q_entry.get("1.0", tk.END).strip()
        if not q:
            return
        if not CORPUS.exists():
            messagebox.showerror("No Corpus",
                "Corpus not built yet.\nGo to the Index Builder tab first.")
            return
        model = self._q_model_var.get() or self._model
        topk  = self._topk_var.get()

        self._log_clear(self._q_out)
        self._log(self._q_out, f"Question: {q}\n", "head")
        self._log(self._q_out, "─" * 60 + "\n", "dim")
        self._ask_btn.configure(state="disabled")
        self._status("Querying FLEX corpus…")

        def _run():
            try:
                emb, chunks = load_corpus(CORPUS)
                qvec = embed_query(q)
                ctx_chunks = _top_k(emb, chunks, qvec, topk)
                ctx = "\n---\n".join(ctx_chunks)[:3000]
                system = (
                    "You are the CITL FLEX Troubleshooter, an expert IT support assistant. "
                    "Answer ONLY using facts found in the provided context from the FLEX Team knowledge base. "
                    "If the answer is not in the context, say so clearly. "
                    "Be concise, structured, and actionable. Use bullet points for steps."
                )
                _stream_generate(
                    self._host, model, system,
                    f"Context:\n{ctx}\n\nQuestion: {q}\nAnswer:",
                    token_cb=lambda t: self.after(0, lambda t=t: self._log(self._q_out, t)),
                    done_cb=lambda: self.after(0, self._query_done),
                    err_cb=lambda e: self.after(0, lambda e=e: self._query_err(e)),
                )
            except Exception as e:
                self.after(0, lambda e=e: self._query_err(str(e)))

        threading.Thread(target=_run, daemon=True).start()

    def _query_done(self):
        self._log(self._q_out, "\n\n" + "─" * 60 + "\n", "dim")
        self._ask_btn.configure(state="normal")
        self._status("Done.")

    def _query_err(self, msg: str):
        self._log(self._q_out, f"\n[ERROR] {msg}\n", "err")
        self._ask_btn.configure(state="normal")
        self._status(f"Error: {msg[:80]}")

    # ─────────────────────────────────────────────────────────────────────────
    # TAB 2 — IT Diagnostics
    # ─────────────────────────────────────────────────────────────────────────
    def _build_diagnostics_tab(self, nb):
        f = ttk.Frame(nb, padding=4)
        nb.add(f, text=" IT Diagnostics ")

        top = ttk.Frame(f)
        top.pack(fill=tk.X)

        # Left: controls
        left = ttk.Frame(top)
        left.pack(side=tk.LEFT, fill=tk.Y, padx=4)

        # Ping
        plf = self._lf(left, "Ping / Connectivity")
        ttk.Label(plf, text="Host / IP:").pack(anchor=tk.W)
        self._ping_host = ttk.Entry(plf, width=28)
        self._ping_host.insert(0, "8.8.8.8")
        self._ping_host.pack(fill=tk.X, pady=2)
        self._btn(plf, "Ping", self._do_ping).pack(fill=tk.X, pady=1)
        self._btn(plf, "Tracert", self._do_tracert).pack(fill=tk.X, pady=1)
        self._btn(plf, "DNS Lookup", self._do_dns).pack(fill=tk.X, pady=1)

        # Port check
        portlf = self._lf(left, "Port Check")
        ttk.Label(portlf, text="Host:").pack(anchor=tk.W)
        self._port_host = ttk.Entry(portlf, width=28)
        self._port_host.insert(0, "localhost")
        self._port_host.pack(fill=tk.X, pady=1)
        ttk.Label(portlf, text="Port:").pack(anchor=tk.W)
        self._port_num = ttk.Entry(portlf, width=10)
        self._port_num.insert(0, "11434")
        self._port_num.pack(fill=tk.X, pady=1)
        self._btn(portlf, "Check Port", self._do_port_check).pack(fill=tk.X, pady=1)
        self._btn(portlf, "Scan Common Ports", self._do_port_scan).pack(fill=tk.X, pady=1)

        # Disk / System
        syslf = self._lf(left, "System")
        self._btn(syslf, "Disk Usage", self._do_disk).pack(fill=tk.X, pady=1)
        self._btn(syslf, "Network Interfaces", self._do_netinfo).pack(fill=tk.X, pady=1)
        self._btn(syslf, "Running Services", self._do_services).pack(fill=tk.X, pady=1)
        self._btn(syslf, "Ollama Status", self._do_ollama_status).pack(fill=tk.X, pady=1)
        self._btn(syslf, "Full System Snapshot", self._do_full_snapshot).pack(fill=tk.X, pady=2)

        # Right: output
        right = ttk.Frame(top)
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=4)

        hdr = ttk.Frame(right)
        hdr.pack(fill=tk.X)
        ttk.Label(hdr, text="Diagnostics Output", font=("Segoe UI", 9, "bold")).pack(side=tk.LEFT)
        self._btn(hdr, "Clear", lambda: self._log_clear(self._diag_out)).pack(side=tk.RIGHT)
        self._btn(hdr, "Save Report", self._save_diag_report).pack(side=tk.RIGHT, padx=4)

        self._diag_out = self._scrolled_text(right, height=30)
        self._diag_out.pack(fill=tk.BOTH, expand=True, pady=2)

    def _diag(self, msg: str, tag: str = ""):
        self._log(self._diag_out, msg, tag)

    def _do_ping(self):
        host = self._ping_host.get().strip()
        self._diag(f"\n[PING] {host}\n", "head")
        def _run():
            try:
                flag = "-n" if sys.platform == "win32" else "-c"
                r = subprocess.run(
                    ["ping", flag, "4", host],
                    capture_output=True, text=True, timeout=15)
                out = r.stdout or r.stderr
                tag = "ok" if r.returncode == 0 else "err"
                self.after(0, lambda: self._diag(out + "\n", tag))
            except Exception as e:
                self.after(0, lambda e=e: self._diag(f"ERROR: {e}\n", "err"))
        threading.Thread(target=_run, daemon=True).start()

    def _do_tracert(self):
        host = self._ping_host.get().strip()
        self._diag(f"\n[TRACERT] {host}\n", "head")
        def _run():
            cmd = ["tracert", "-d", "-h", "15", host] if sys.platform == "win32" \
                  else ["traceroute", "-m", "15", host]
            try:
                r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
                self.after(0, lambda: self._diag((r.stdout or r.stderr) + "\n"))
            except Exception as e:
                self.after(0, lambda e=e: self._diag(f"ERROR: {e}\n", "err"))
        threading.Thread(target=_run, daemon=True).start()

    def _do_dns(self):
        host = self._ping_host.get().strip()
        self._diag(f"\n[DNS] {host}\n", "head")
        def _run():
            try:
                result = socket.getaddrinfo(host, None)
                lines = "\n".join(f"  {r[4][0]}" for r in result[:6])
                self.after(0, lambda: self._diag(f"Resolved:\n{lines}\n", "ok"))
            except Exception as e:
                self.after(0, lambda e=e: self._diag(f"DNS failed: {e}\n", "err"))
        threading.Thread(target=_run, daemon=True).start()

    def _do_port_check(self):
        host = self._port_host.get().strip()
        try:
            port = int(self._port_num.get().strip())
        except ValueError:
            self._diag("Invalid port number.\n", "err")
            return
        self._diag(f"\n[PORT CHECK] {host}:{port}\n", "head")
        def _run():
            try:
                s = socket.create_connection((host, port), timeout=4)
                s.close()
                self.after(0, lambda: self._diag(f"  OPEN — {host}:{port} is reachable.\n", "ok"))
            except Exception as e:
                self.after(0, lambda e=e: self._diag(f"  CLOSED/BLOCKED — {e}\n", "err"))
        threading.Thread(target=_run, daemon=True).start()

    def _do_port_scan(self):
        host = self._port_host.get().strip()
        COMMON = [21,22,23,25,53,80,110,135,139,143,443,445,3389,5900,8080,8443,11434]
        self._diag(f"\n[PORT SCAN] {host} — checking {len(COMMON)} common ports\n", "head")
        def _run():
            results = []
            for p in COMMON:
                try:
                    s = socket.create_connection((host, p), timeout=0.8)
                    s.close()
                    results.append((p, "OPEN"))
                except Exception:
                    results.append((p, "closed"))
            lines = "\n".join(
                f"  {p:5d}  {'OPEN ' if s=='OPEN' else '     '} {_PORT_NAMES.get(p,'')}"
                for p, s in results if s == "OPEN"
            )
            closed = sum(1 for _, s in results if s == "closed")
            self.after(0, lambda: self._diag(
                (lines or "  No open ports found.") + f"\n  ({closed} closed)\n", "ok" if lines else "warn"
            ))
        threading.Thread(target=_run, daemon=True).start()

    def _do_disk(self):
        self._diag("\n[DISK USAGE]\n", "head")
        def _run():
            lines = []
            if sys.platform == "win32":
                try:
                    r = subprocess.run(
                        ["powershell", "-NoProfile", "-Command",
                         "Get-PSDrive -PSProvider FileSystem | Select-Object Name,Used,Free,Root | Format-Table -AutoSize"],
                        capture_output=True, text=True, timeout=10)
                    lines.append(r.stdout)
                except Exception as e:
                    lines.append(f"ERROR: {e}")
            else:
                try:
                    r = subprocess.run(["df", "-h"], capture_output=True, text=True)
                    lines.append(r.stdout)
                except Exception as e:
                    lines.append(f"ERROR: {e}")
            self.after(0, lambda: self._diag("\n".join(lines) + "\n"))
        threading.Thread(target=_run, daemon=True).start()

    def _do_netinfo(self):
        self._diag("\n[NETWORK INTERFACES]\n", "head")
        def _run():
            try:
                if sys.platform == "win32":
                    r = subprocess.run(["ipconfig", "/all"], capture_output=True, text=True, timeout=10)
                else:
                    r = subprocess.run(["ip", "addr"], capture_output=True, text=True, timeout=10)
                self.after(0, lambda: self._diag(r.stdout + "\n"))
            except Exception as e:
                self.after(0, lambda e=e: self._diag(f"ERROR: {e}\n", "err"))
        threading.Thread(target=_run, daemon=True).start()

    def _do_services(self):
        self._diag("\n[RUNNING SERVICES (top 30 by CPU)]\n", "head")
        def _run():
            try:
                if sys.platform == "win32":
                    r = subprocess.run(
                        ["powershell", "-NoProfile", "-Command",
                         "Get-Process | Sort-Object CPU -Descending | Select-Object -First 30 Name,CPU,WorkingSet,Id | Format-Table -AutoSize"],
                        capture_output=True, text=True, timeout=15)
                    self.after(0, lambda: self._diag(r.stdout + "\n"))
                else:
                    r = subprocess.run(["ps", "aux", "--sort=-%cpu"],
                                       capture_output=True, text=True)
                    lines = r.stdout.splitlines()[:32]
                    self.after(0, lambda: self._diag("\n".join(lines) + "\n"))
            except Exception as e:
                self.after(0, lambda e=e: self._diag(f"ERROR: {e}\n", "err"))
        threading.Thread(target=_run, daemon=True).start()

    def _do_ollama_status(self):
        host = self._host
        self._diag(f"\n[OLLAMA STATUS] {host}\n", "head")
        def _run():
            try:
                models = _list_models(host)
                lines = [f"  Ollama reachable at {host}", f"  Models ({len(models)}):"]
                lines += [f"    • {m}" for m in models]
                self.after(0, lambda: self._diag("\n".join(lines) + "\n", "ok"))
            except Exception as e:
                self.after(0, lambda e=e: self._diag(f"  UNREACHABLE: {e}\n", "err"))
        threading.Thread(target=_run, daemon=True).start()

    def _do_full_snapshot(self):
        self._log_clear(self._diag_out)
        self._diag(f"CITL FLEX — Full System Snapshot\n{datetime.now():%Y-%m-%d %H:%M:%S}\n", "head")
        self._diag("=" * 60 + "\n", "dim")
        self._do_disk()
        self.after(500,  self._do_netinfo)
        self.after(2000, self._do_ollama_status)
        self.after(3000, self._do_services)

    def _save_diag_report(self):
        ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = filedialog.asksaveasfilename(
            defaultextension=".txt",
            initialfile=f"FLEX_Diag_{ts}.txt",
            filetypes=[("Text", "*.txt"), ("All", "*.*")])
        if not path:
            return
        try:
            content = self._diag_out.get("1.0", tk.END)
            Path(path).write_text(content, encoding="utf-8")
            self._status(f"Report saved: {path}")
        except Exception as e:
            messagebox.showerror("Save Error", str(e))

    # ─────────────────────────────────────────────────────────────────────────
    # TAB 3 — Ticket Writer
    # ─────────────────────────────────────────────────────────────────────────
    def _build_ticket_tab(self, nb):
        f = ttk.Frame(nb, padding=4)
        nb.add(f, text=" Ticket Writer ")

        left = ttk.Frame(f)
        left.pack(side=tk.LEFT, fill=tk.Y, padx=4, pady=2)

        # Category / priority
        meta = self._lf(left, "Ticket Metadata")
        ttk.Label(meta, text="Category:").pack(anchor=tk.W)
        self._tkt_cat = ttk.Combobox(meta, width=22, state="readonly",
                                      values=["AV / Projector", "Network / Wi-Fi",
                                              "Hardware", "Software / OS", "Account / Access",
                                              "Classroom Tech", "Printer", "Other"])
        self._tkt_cat.set("AV / Projector")
        self._tkt_cat.pack(fill=tk.X, pady=2)

        ttk.Label(meta, text="Priority:").pack(anchor=tk.W)
        self._tkt_pri = ttk.Combobox(meta, width=22, state="readonly",
                                      values=["Low", "Medium", "High", "Critical"])
        self._tkt_pri.set("Medium")
        self._tkt_pri.pack(fill=tk.X, pady=2)

        ttk.Label(meta, text="Location / Room:").pack(anchor=tk.W)
        self._tkt_loc = ttk.Entry(meta, width=24)
        self._tkt_loc.insert(0, "")
        self._tkt_loc.pack(fill=tk.X, pady=2)

        ttk.Label(meta, text="Reported by:").pack(anchor=tk.W)
        self._tkt_rep = ttk.Entry(meta, width=24)
        self._tkt_rep.pack(fill=tk.X, pady=2)

        # Description
        desc_lf = self._lf(left, "Issue Description")
        self._tkt_desc = tk.Text(desc_lf, height=8, wrap=tk.WORD,
                                  font=("Segoe UI", 9),
                                  bg=self._p["entry_bg"], fg=self._p["entry_fg"],
                                  insertbackground=self._p["cursor"])
        self._tkt_desc.pack(fill=tk.BOTH, expand=True, pady=2)

        btn_row = ttk.Frame(left)
        btn_row.pack(fill=tk.X, pady=4)
        self._ticket_btn = self._btn(btn_row, "Generate Ticket", self._do_generate_ticket)
        self._ticket_btn.pack(fill=tk.X)
        self._btn(btn_row, "Clear", self._clear_ticket).pack(fill=tk.X, pady=2)
        self._btn(btn_row, "Copy Ticket", self._copy_ticket).pack(fill=tk.X)
        self._btn(btn_row, "Save Ticket", self._save_ticket).pack(fill=tk.X, pady=2)

        # Right: output
        right = ttk.Frame(f)
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=4)
        ttk.Label(right, text="Generated Ticket", font=("Segoe UI", 9, "bold")).pack(anchor=tk.W)
        self._tkt_out = self._scrolled_text(right, height=30)
        self._tkt_out.pack(fill=tk.BOTH, expand=True)

    def _do_generate_ticket(self):
        desc   = self._tkt_desc.get("1.0", tk.END).strip()
        cat    = self._tkt_cat.get()
        pri    = self._tkt_pri.get()
        loc    = self._tkt_loc.get().strip()
        rep    = self._tkt_rep.get().strip()
        ts     = datetime.now().strftime("%Y-%m-%d %H:%M")

        if not desc:
            messagebox.showwarning("Empty", "Enter an issue description first.")
            return

        self._log_clear(self._tkt_out)
        self._log(self._tkt_out,
            f"CITL FLEX IT Support Ticket\n"
            f"Generated: {ts}\n"
            f"Category:  {cat}\n"
            f"Priority:  {pri}\n"
            f"Location:  {loc or '(not specified)'}\n"
            f"Reporter:  {rep or '(not specified)'}\n"
            f"{'─'*50}\n\n", "head")

        model = self._q_model_var.get() if hasattr(self, "_q_model_var") else self._model
        system = (
            "You are an expert IT support ticket writer for Renton Technical College CITL. "
            "Write a professional, structured IT support ticket. Include:\n"
            "1. SUMMARY (one sentence)\n"
            "2. SYMPTOMS (bullet list of what the user described)\n"
            "3. AFFECTED SYSTEMS (hardware/software/services impacted)\n"
            "4. INITIAL TRIAGE STEPS (3-5 ordered steps an IT tech should try first)\n"
            "5. ESCALATION CRITERIA (when to escalate to higher tier)\n"
            "6. NOTES (any relevant knowledge base references or common causes)\n\n"
            "Be concise, specific, and actionable. Use plain text only."
        )
        prompt = (
            f"Category: {cat}\nPriority: {pri}\nLocation: {loc}\n"
            f"Issue Description:\n{desc}\n\nWrite the IT support ticket:"
        )

        self._ticket_btn.configure(state="disabled")
        self._status("Generating ticket…")
        _stream_generate(
            self._host, model, system, prompt,
            token_cb=lambda t: self.after(0, lambda t=t: self._log(self._tkt_out, t)),
            done_cb=lambda: self.after(0, self._ticket_done),
            err_cb=lambda e: self.after(0, lambda e=e: (
                self._log(self._tkt_out, f"\n[ERROR] {e}\n", "err"),
                self._ticket_btn.configure(state="normal"),
            )),
        )

    def _ticket_done(self):
        self._log(self._tkt_out, "\n\n" + "─" * 50 + "\n", "dim")
        self._ticket_btn.configure(state="normal")
        self._status("Ticket generated.")

    def _clear_ticket(self):
        self._tkt_desc.delete("1.0", tk.END)
        self._log_clear(self._tkt_out)

    def _copy_ticket(self):
        content = self._tkt_out.get("1.0", tk.END)
        self.clipboard_clear()
        self.clipboard_append(content)
        self._status("Ticket copied to clipboard.")

    def _save_ticket(self):
        ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = filedialog.asksaveasfilename(
            defaultextension=".txt",
            initialfile=f"FLEX_Ticket_{ts}.txt",
            filetypes=[("Text", "*.txt"), ("All", "*.*")])
        if not path:
            return
        try:
            Path(path).write_text(self._tkt_out.get("1.0", tk.END), encoding="utf-8")
            self._status(f"Ticket saved: {path}")
        except Exception as e:
            messagebox.showerror("Save Error", str(e))

    # ─────────────────────────────────────────────────────────────────────────
    # TAB 4 — Index Builder
    # ─────────────────────────────────────────────────────────────────────────
    def _build_index_tab(self, nb):
        f = ttk.Frame(nb, padding=4)
        nb.add(f, text=" Index Builder ")

        src_lf = self._lf(f, "Source Document(s)")
        src_row = ttk.Frame(src_lf)
        src_row.pack(fill=tk.X)
        self._idx_src = ttk.Entry(src_row)
        default_pdf = DATA_DIR / "MAIN - The FLEX Team One Note - FULL.pdf"
        self._idx_src.insert(0, str(default_pdf))
        self._idx_src.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 4))
        self._btn(src_row, "Browse…", self._browse_idx_src).pack(side=tk.LEFT)

        out_lf = self._lf(f, "Output Corpus")
        out_row = ttk.Frame(out_lf)
        out_row.pack(fill=tk.X)
        self._idx_out = ttk.Entry(out_row)
        self._idx_out.insert(0, str(CORPUS))
        self._idx_out.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 4))
        self._btn(out_row, "Browse…", self._browse_idx_out).pack(side=tk.LEFT)

        opts_lf = self._lf(f, "Options")
        opt_row = ttk.Frame(opts_lf)
        opt_row.pack(fill=tk.X)
        ttk.Label(opt_row, text="Chunk size:").pack(side=tk.LEFT)
        self._chunk_sz = ttk.Entry(opt_row, width=6)
        self._chunk_sz.insert(0, "512")
        self._chunk_sz.pack(side=tk.LEFT, padx=6)
        ttk.Label(opt_row, text="Overlap:").pack(side=tk.LEFT)
        self._chunk_ov = ttk.Entry(opt_row, width=6)
        self._chunk_ov.insert(0, "64")
        self._chunk_ov.pack(side=tk.LEFT, padx=6)
        ttk.Label(opt_row, text="Embed model:").pack(side=tk.LEFT, padx=(12, 4))
        self._idx_emb = ttk.Entry(opt_row, width=22)
        self._idx_emb.insert(0, self._emb)
        self._idx_emb.pack(side=tk.LEFT)

        btn_row = ttk.Frame(f)
        btn_row.pack(fill=tk.X, pady=6, padx=4)
        self._idx_btn = self._btn(btn_row, "Build / Rebuild Index", self._do_build_index)
        self._idx_btn.pack(side=tk.LEFT, padx=4)
        self._btn(btn_row, "Corpus Health Check", self._do_corpus_health).pack(side=tk.LEFT, padx=4)
        self._btn(btn_row, "Clear Log", lambda: self._log_clear(self._idx_log)).pack(side=tk.RIGHT)

        self._idx_progress = ttk.Progressbar(f, mode="indeterminate")
        self._idx_progress.pack(fill=tk.X, padx=4, pady=2)

        log_lf = self._lf(f, "Index Builder Log", expand=True)
        self._idx_log = self._scrolled_text(log_lf, height=14)
        self._idx_log.pack(fill=tk.BOTH, expand=True)

        # Show existing corpus info
        self._show_corpus_info()

    def _show_corpus_info(self):
        if CORPUS.exists():
            try:
                d = json.loads(CORPUS.read_text(encoding="utf-8"))
                n_chunks = len(d.get("chunks", []))
                sz = CORPUS.stat().st_size // 1024
                self._log(self._idx_log,
                    f"Existing corpus: {CORPUS.name}\n"
                    f"  Chunks: {n_chunks:,}   Size: {sz:,} KB\n", "ok")
            except Exception as e:
                self._log(self._idx_log, f"Corpus parse error: {e}\n", "warn")
        else:
            self._log(self._idx_log, "No corpus found — use Build to create one.\n", "warn")

    def _browse_idx_src(self):
        p = filedialog.askopenfilename(
            filetypes=[("PDF/Text", "*.pdf *.txt *.docx *.md"), ("All", "*.*")])
        if p:
            self._idx_src.delete(0, tk.END)
            self._idx_src.insert(0, p)

    def _browse_idx_out(self):
        p = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON", "*.json"), ("All", "*.*")])
        if p:
            self._idx_out.delete(0, tk.END)
            self._idx_out.insert(0, p)

    def _do_build_index(self):
        src = Path(self._idx_src.get().strip())
        out = Path(self._idx_out.get().strip())
        if not src.exists():
            messagebox.showerror("Not Found", f"Source not found:\n{src}")
            return

        self._idx_progress.start(12)
        self._idx_btn.configure(state="disabled")
        self._log(self._idx_log, f"\n[BUILD] {src.name} → {out.name}\n", "head")
        self._status("Building FLEX corpus index…")

        build_script = FA_DIR / "build_corpus_index.py"
        emb_model    = self._idx_emb.get().strip()
        chunk_sz     = self._chunk_sz.get().strip()
        chunk_ov     = self._chunk_ov.get().strip()

        def _run():
            try:
                if build_script.exists():
                    cmd = [sys.executable, str(build_script),
                           "--src", str(src), "--out", str(out),
                           "--embed-model", emb_model,
                           "--chunk", chunk_sz]
                    proc = subprocess.Popen(
                        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                        text=True, bufsize=1)
                    for line in proc.stdout:
                        self.after(0, lambda l=line: self._log(self._idx_log, l))
                    proc.wait()
                    ok = proc.returncode == 0
                else:
                    # Fallback: use flex_builder
                    from flex_builder import build_index
                    build_index(src=src, out=out)
                    ok = True
                self.after(0, lambda: self._index_done(ok))
            except Exception as e:
                self.after(0, lambda e=e: self._index_err(str(e)))

        threading.Thread(target=_run, daemon=True).start()

    def _index_done(self, ok: bool):
        self._idx_progress.stop()
        self._idx_btn.configure(state="normal")
        tag = "ok" if ok else "err"
        self._log(self._idx_log, f"\nIndex build {'complete' if ok else 'FAILED'}.\n", tag)
        self._show_corpus_info()
        self._corpus_lbl.configure(text=self._corpus_status())
        self._status("Index built." if ok else "Index build failed.")

    def _index_err(self, msg: str):
        self._idx_progress.stop()
        self._idx_btn.configure(state="normal")
        self._log(self._idx_log, f"ERROR: {msg}\n", "err")
        self._status(f"Build error: {msg[:80]}")

    def _do_corpus_health(self):
        if not _HAS_HEALTH:
            self._log(self._idx_log,
                "citl_corpus_health module not available — check PYTHONPATH.\n", "warn")
            return
        self._log(self._idx_log, "\n[CORPUS HEALTH CHECK]\n", "head")
        def _run():
            try:
                rpt = _scan_corpus_health(source_path=CORPUS)
                lines = [f"Status: {rpt.overall_status}  [{rpt.timestamp}]"]
                for e in rpt.embeddings:
                    lines.append(f"  Embedding {e.name}: {e.status}  "
                                 f"({e.vector_count} vectors, dim={e.dim})")
                for ix in rpt.indexes:
                    lines.append(f"  Index {ix.name}: {ix.chunk_count} chunks")
                for n in rpt.notes:
                    lines.append(f"  NOTE: {n}")
                self.after(0, lambda: self._log(self._idx_log,
                    "\n".join(lines) + "\n", "ok"))
            except Exception as e:
                self.after(0, lambda e=e: self._log(self._idx_log, f"Error: {e}\n", "err"))
        threading.Thread(target=_run, daemon=True).start()

    # ─────────────────────────────────────────────────────────────────────────
    # TAB 5 — Models
    # ─────────────────────────────────────────────────────────────────────────
    def _build_models_tab(self, nb):
        f = ttk.Frame(nb, padding=4)
        nb.add(f, text=" Models ")

        left = ttk.Frame(f)
        left.pack(side=tk.LEFT, fill=tk.Y, padx=4)

        list_lf = self._lf(left, "Installed Models")
        self._mdl_listbox = tk.Listbox(list_lf, width=30, height=16,
                                        bg=self._p["entry_bg"],
                                        fg=self._p["entry_fg"],
                                        selectbackground=self._p["select_bg"],
                                        font=("Consolas", 9))
        self._mdl_listbox.pack(fill=tk.BOTH, expand=True, pady=2)
        self._btn(list_lf, "Refresh", self._refresh_models_tab).pack(fill=tk.X, pady=1)

        pull_lf = self._lf(left, "Pull Model")
        ttk.Label(pull_lf, text="Model name:").pack(anchor=tk.W)
        self._pull_name = ttk.Entry(pull_lf, width=28)
        self._pull_name.insert(0, "mistral:7b-instruct")
        self._pull_name.pack(fill=tk.X, pady=2)
        self._btn(pull_lf, "Pull", self._do_pull_model).pack(fill=tk.X)

        del_lf = self._lf(left, "Delete Selected")
        self._btn(del_lf, "Delete Model", self._do_delete_model).pack(fill=tk.X)

        allen_lf = self._lf(left, "AllenAI Quick Install")
        self._btn(allen_lf, "OLMo2 7B  (LLM)",
                  lambda: self._pull_allenai("olmo2:7b")).pack(fill=tk.X, pady=1)
        self._btn(allen_lf, "OLMo2 1B  (Fast LLM)",
                  lambda: self._pull_allenai("olmo2:1b")).pack(fill=tk.X, pady=1)
        self._btn(allen_lf, "Molmo 7B-D  (Vision)",
                  lambda: self._pull_allenai("molmo7b-d-0924")).pack(fill=tk.X, pady=1)
        self._btn(allen_lf, "Molmo 7B-O  (Vision)",
                  lambda: self._pull_allenai("molmo7b-o-0924")).pack(fill=tk.X, pady=1)

        # Right: Modelfile editor
        right = ttk.Frame(f)
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=4)

        mf_hdr = ttk.Frame(right)
        mf_hdr.pack(fill=tk.X)
        ttk.Label(mf_hdr, text="FLEX Modelfile",
                  font=("Segoe UI", 9, "bold")).pack(side=tk.LEFT)
        self._btn(mf_hdr, "Load", self._load_modelfile).pack(side=tk.RIGHT, padx=2)
        self._btn(mf_hdr, "Save", self._save_modelfile).pack(side=tk.RIGHT, padx=2)
        self._btn(mf_hdr, "Apply (ollama create)", self._apply_modelfile).pack(side=tk.RIGHT, padx=2)

        self._mf_editor = tk.Text(right, wrap=tk.NONE,
                                   font=("Consolas", 9),
                                   bg=self._p["entry_bg"], fg=self._p["entry_fg"],
                                   insertbackground=self._p["cursor"])
        sb = ttk.Scrollbar(right, command=self._mf_editor.yview)
        self._mf_editor.configure(yscrollcommand=sb.set)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self._mf_editor.pack(fill=tk.BOTH, expand=True)

        self._mdl_log = self._scrolled_text(right, height=5)
        self._mdl_log.pack(fill=tk.X, pady=2)

        self._load_modelfile_content()
        self._refresh_models_tab()

    def _refresh_models_tab(self):
        models = _list_models(self._host)
        self._mdl_listbox.delete(0, tk.END)
        for m in models:
            self._mdl_listbox.insert(tk.END, m)
        self._log(self._mdl_log, f"[{datetime.now():%H:%M:%S}] {len(models)} models\n", "ok")

    def _do_pull_model(self):
        name = self._pull_name.get().strip()
        if not name:
            return
        self._log(self._mdl_log, f"Pulling {name}…\n", "head")
        def _run():
            try:
                r = subprocess.run(
                    ["ollama", "pull", name],
                    capture_output=True, text=True, timeout=3600)
                out = r.stdout or r.stderr
                tag = "ok" if r.returncode == 0 else "err"
                self.after(0, lambda: (
                    self._log(self._mdl_log, out[:500] + "\n", tag),
                    self._refresh_models_tab()
                ))
            except Exception as e:
                self.after(0, lambda e=e: self._log(self._mdl_log, f"ERROR: {e}\n", "err"))
        threading.Thread(target=_run, daemon=True).start()

    def _do_delete_model(self):
        sel = self._mdl_listbox.curselection()
        if not sel:
            messagebox.showwarning("Select", "Select a model first.")
            return
        name = self._mdl_listbox.get(sel[0])
        if not messagebox.askyesno("Delete", f"Delete model '{name}'?"):
            return
        def _run():
            try:
                r = subprocess.run(["ollama", "rm", name], capture_output=True, text=True)
                self.after(0, lambda: (
                    self._log(self._mdl_log, f"Deleted {name}\n", "ok"),
                    self._refresh_models_tab()
                ))
            except Exception as e:
                self.after(0, lambda e=e: self._log(self._mdl_log, f"ERROR: {e}\n", "err"))
        threading.Thread(target=_run, daemon=True).start()

    def _pull_allenai(self, model_tag: str) -> None:
        self._log(self._mdl_log, f"Pulling AllenAI {model_tag} — this may take 10-30 min…\n", "head")
        def _run():
            try:
                r = subprocess.run(
                    ["ollama", "pull", model_tag],
                    capture_output=True, text=True, timeout=7200)
                out = (r.stdout or r.stderr or "")[:800]
                tag = "ok" if r.returncode == 0 else "err"
                self.after(0, lambda: (
                    self._log(self._mdl_log, out + "\n", tag),
                    self._refresh_models_tab(),
                    self._health_bar_poll(force=True),
                ))
            except Exception as e:
                self.after(0, lambda e=e: self._log(self._mdl_log, f"ERROR: {e}\n", "err"))
        threading.Thread(target=_run, daemon=True).start()

    def _load_modelfile_content(self):
        if MODFILE.exists():
            self._mf_editor.delete("1.0", tk.END)
            self._mf_editor.insert("1.0", MODFILE.read_text(encoding="utf-8"))

    def _load_modelfile(self):
        p = filedialog.askopenfilename(
            filetypes=[("Modelfile", "Modelfile*"), ("All", "*.*")])
        if p:
            self._mf_editor.delete("1.0", tk.END)
            self._mf_editor.insert("1.0", Path(p).read_text(encoding="utf-8"))

    def _save_modelfile(self):
        content = self._mf_editor.get("1.0", tk.END)
        MODFILE.write_text(content, encoding="utf-8")
        self._log(self._mdl_log, f"Saved: {MODFILE}\n", "ok")

    def _apply_modelfile(self):
        self._save_modelfile()
        name = "flex-troubleshooter"
        self._log(self._mdl_log, f"Creating model '{name}' from Modelfile…\n", "head")
        def _run():
            try:
                r = subprocess.run(
                    ["ollama", "create", name, "-f", str(MODFILE)],
                    capture_output=True, text=True, timeout=300)
                tag = "ok" if r.returncode == 0 else "err"
                self.after(0, lambda: (
                    self._log(self._mdl_log, (r.stdout or r.stderr)[:400] + "\n", tag),
                    self._refresh_models_tab()
                ))
            except Exception as e:
                self.after(0, lambda e=e: self._log(self._mdl_log, f"ERROR: {e}\n", "err"))
        threading.Thread(target=_run, daemon=True).start()

    # ─────────────────────────────────────────────────────────────────────────
    # TAB 6 — Settings
    # ─────────────────────────────────────────────────────────────────────────
    def _build_settings_tab(self, nb):
        f = ttk.Frame(nb, padding=8)
        nb.add(f, text=" Settings ")

        conn_lf = self._lf(f, "Ollama Connection")
        ttk.Label(conn_lf, text="Host URL:").pack(anchor=tk.W)
        self._set_host = ttk.Entry(conn_lf, width=40)
        self._set_host.insert(0, self._host)
        self._set_host.pack(fill=tk.X, pady=2)
        self._btn(conn_lf, "Test Connection", self._test_connection).pack(anchor=tk.W, pady=2)

        model_lf = self._lf(f, "Default Models")
        ttk.Label(model_lf, text="Generation model:").pack(anchor=tk.W)
        self._set_model = ttk.Entry(model_lf, width=36)
        self._set_model.insert(0, self._model)
        self._set_model.pack(fill=tk.X, pady=2)

        ttk.Label(model_lf, text="Embedding model:").pack(anchor=tk.W, pady=(6, 0))
        self._set_emb = ttk.Entry(model_lf, width=36)
        self._set_emb.insert(0, self._emb)
        self._set_emb.pack(fill=tk.X, pady=2)

        ttk.Label(model_lf, text="Default top-K chunks:").pack(anchor=tk.W, pady=(6, 0))
        self._set_topk = ttk.Spinbox(model_lf, from_=1, to=20, width=6)
        self._set_topk.set(str(self._topk))
        self._set_topk.pack(anchor=tk.W, pady=2)

        theme_lf = self._lf(f, "Theme")
        ttk.Label(theme_lf, text="Color scheme:").pack(anchor=tk.W)
        palette_names = list(_theme.PALETTE_DISPLAY.keys()) if _HAS_THEME else ["teal_ops", "ops", "graphite"]
        self._set_theme = ttk.Combobox(theme_lf, values=palette_names,
                                        width=32, state="readonly")
        self._set_theme.set(self._palette_name)
        self._set_theme.pack(fill=tk.X, pady=2)
        self._btn(theme_lf, "Preview Theme", self._preview_theme).pack(anchor=tk.W, pady=2)

        self._btn(f, "Save Settings", self._save_settings).pack(anchor=tk.W, pady=12)

        self._set_log = self._scrolled_text(f, height=5)
        self._set_log.pack(fill=tk.X)

    def _test_connection(self):
        host = self._set_host.get().strip()
        models = _list_models(host)
        if models:
            self._log(self._set_log, f"Connected to {host} — {len(models)} models.\n", "ok")
        else:
            self._log(self._set_log, f"No models found at {host} (may be offline or no models pulled).\n", "warn")

    def _preview_theme(self):
        name = self._set_theme.get()
        self._apply_theme(name)
        self._theme_status()

    def _save_settings(self):
        self._host  = self._set_host.get().strip()
        self._model = self._set_model.get().strip()
        self._emb   = self._set_emb.get().strip()
        try:
            self._topk = int(self._set_topk.get())
        except ValueError:
            pass
        self._palette_name = self._set_theme.get()
        cfg = {
            "host":      self._host,
            "model":     self._model,
            "emb_model": self._emb,
            "topk":      self._topk,
            "theme":     self._palette_name,
        }
        _save_cfg(cfg)
        self._apply_theme(self._palette_name)
        self._theme_status()
        self._log(self._set_log, "Settings saved.\n", "ok")
        self._status("Settings saved.")

    # ─────────────────────────────────────────────────────────────────────────
    # TAB 7 — System Diagnostics & Self-Heal
    # ─────────────────────────────────────────────────────────────────────────
    def _build_heal_tab(self, nb):
        f = ttk.Frame(nb, padding=4)
        nb.add(f, text=" System Heal ")

        sub_nb = ttk.Notebook(f)
        sub_nb.pack(fill=tk.BOTH, expand=True)

        # ── Sub-tab 1: Pipeline Diagnostic ────────────────────────────────
        diag_f = ttk.Frame(sub_nb, padding=4)
        sub_nb.add(diag_f, text=" Pipeline Diagnostic ")

        try:
            from citl_factbook_diagnostic import run_diagnostic, StepResult as SR
            _HAS_DIAG = True
        except ImportError:
            _HAS_DIAG = False

        if not _HAS_DIAG:
            ttk.Label(diag_f,
                      text="citl_factbook_diagnostic.py not found in factbook-assistant/",
                      wraplength=500).pack(padx=20, pady=20)
        else:
            diag_sv = tk.StringVar(value="Click 'Run' to test the full pipeline.")
            tk.Label(diag_f, textvariable=diag_sv,
                     font=("Consolas", 9), anchor="w").pack(fill=tk.X)

            canv = tk.Canvas(diag_f, highlightthickness=0)
            vsb = ttk.Scrollbar(diag_f, orient="vertical", command=canv.yview)
            sf = tk.Frame(canv)
            sf.bind("<Configure>",
                    lambda e: canv.configure(scrollregion=canv.bbox("all")))
            canv.create_window((0, 0), window=sf, anchor="nw")
            canv.configure(yscrollcommand=vsb.set)
            vsb.pack(side=tk.RIGHT, fill=tk.Y)
            canv.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

            dlog = scrolledtext.ScrolledText(diag_f, height=4, state="disabled",
                                             font=("Consolas", 8))
            dlog.pack(fill=tk.X)

            def _dlog(line: str):
                def _d():
                    dlog.configure(state="normal")
                    dlog.insert("end", line + "\n")
                    dlog.configure(state="disabled")
                    dlog.see("end")
                self.after(0, _d)

            _DOTC = {"pass": "green", "fail": "red", "warn": "orange", "skip": "gray"}
            _store = []
            _cnts = {"pass": 0, "fail": 0, "warn": 0, "skip": 0}

            def _add(r: SR):
                def _ui():
                    c = _DOTC.get(r.status, "gray")
                    row = tk.Frame(sf)
                    row.pack(fill=tk.X, pady=1)
                    tk.Label(row, text="●", fg=c,
                             font=("Consolas", 11)).pack(side=tk.LEFT, padx=(4, 4))
                    inf = tk.Frame(row)
                    inf.pack(side=tk.LEFT, fill=tk.X, expand=True)
                    tk.Label(inf,
                             text=f"[{r.status.upper():4s}] S{r.stage:02d}: {r.name}",
                             font=("Consolas", 8, "bold"), fg=c, anchor="w").pack(anchor="w")
                    fl = r.detail.split("\n")[0][:90]
                    tk.Label(inf, text=fl, font=("Consolas", 8), anchor="w",
                             wraplength=350, justify="left").pack(anchor="w")
                    bfr = tk.Frame(row)
                    bfr.pack(side=tk.RIGHT, padx=2)
                    _ex = [False]; _df2 = [None]
                    def _tog(rr=r, ex=_ex, df=_df2, p=inf):
                        if ex[0]:
                            if df[0]: df[0].destroy(); df[0] = None; ex[0] = False
                        else:
                            df[0] = tk.Frame(p, bg="#111")
                            df[0].pack(fill=tk.X)
                            tk.Label(df[0], text=rr.detail, font=("Consolas", 7),
                                     wraplength=460, justify="left",
                                     bg="#111", fg="#ccc").pack(anchor="w")
                            ex[0] = True
                    tk.Button(bfr, text="Detail", relief="flat", padx=3,
                               font=("Consolas", 7), command=_tog).pack(side=tk.LEFT)
                    if r.fix_fn and not r.passed:
                        def _fix(rr=r):
                            def _bg():
                                try:
                                    ok = rr.fix_fn(rr, _dlog)
                                    self.after(0, lambda o=ok, n=rr.name: diag_sv.set(
                                        f"Fix {'OK' if o else 'incomplete'}: {n}"))
                                except Exception as ex2:
                                    self.after(0, lambda e=ex2: _dlog(f"ERROR: {e}"))
                            threading.Thread(target=_bg, daemon=True).start()
                        tk.Button(bfr, text="Fix", relief="flat", padx=4,
                                   bg="green", fg="black",
                                   font=("Consolas", 7, "bold"),
                                   command=_fix).pack(side=tk.LEFT, padx=2)
                    tk.Frame(sf, height=1).pack(fill=tk.X)
                self.after(0, _ui)

            def _run_d():
                for w in sf.winfo_children():
                    w.destroy()
                _store.clear()
                _cnts.update({"pass": 0, "fail": 0, "warn": 0, "skip": 0})
                diag_sv.set("Running...")

                def _bg():
                    def _on(r: SR):
                        _store.append(r)
                        _cnts[r.status] = _cnts.get(r.status, 0) + 1
                        _add(r)
                        self.after(0, lambda: diag_sv.set(
                            f"S{r.stage}/18: {r.name} [{r.status.upper()}] | "
                            f"{_cnts['pass']}P {_cnts['fail']}F {_cnts['warn']}W"))
                    run_diagnostic(on_result=_on)
                    failed = [r for r in _store if r.failed]
                    self.after(0, lambda: diag_sv.set(
                        f"DONE: {_cnts['pass']} pass, {_cnts['fail']} fail, "
                        f"{_cnts['warn']} warn"
                        + (" -- FIX RED STAGES" if failed else " -- PIPELINE OK")))
                threading.Thread(target=_bg, daemon=True).start()

            btn_r = ttk.Frame(diag_f)
            btn_r.pack(fill=tk.X)
            self._btn(btn_r, "Run Pipeline Diagnostic", _run_d).pack(
                side=tk.LEFT, padx=4, pady=4)
            self._btn(btn_r, "Open Full Diagnostic Window",
                      lambda: threading.Thread(
                          target=lambda: __import__("citl_factbook_diagnostic",
                                                    fromlist=["run_gui"]).run_gui(),
                          daemon=True).start()).pack(side=tk.LEFT, padx=2)

        # ── Sub-tab 2: System Heal ─────────────────────────────────────────
        heal_f = ttk.Frame(sub_nb, padding=2)
        sub_nb.add(heal_f, text=" System Heal ")
        try:
            from citl_heal_panel import HealPanel
            pal = {}
            if _HAS_THEME:
                try:
                    pal = _theme.PALETTES.get(self._palette_name, {})
                except Exception:
                    pass
            panel = HealPanel(heal_f, theme=pal or None, quick=False)
            panel.pack(fill=tk.BOTH, expand=True)
        except Exception as e:
            ttk.Label(heal_f,
                      text=f"Heal panel unavailable: {e}",
                      wraplength=500, justify="left").pack(padx=20, pady=20)


    # ─────────────────────────────────────────────────────────────────────────
    # TAB 8 — USB Reimager Deploy
    # ─────────────────────────────────────────────────────────────────────────
    def _build_usb_deploy_tab(self, nb):
        f = ttk.Frame(nb, padding=4)
        nb.add(f, text=" USB Reimager ")

        top = self._lf(f, "CITL Reimager USB Deploy")
        ttk.Label(top,
                  text="Detect connected ExFAT drives and push the CITL Reimager toolkit to them.",
                  wraplength=700, justify="left").pack(anchor=tk.W, pady=(0, 4))

        btn_row = ttk.Frame(top)
        btn_row.pack(fill=tk.X, pady=2)
        self._btn(btn_row, "Scan for ExFAT Drives",
                  self._usb_scan_drives).pack(side=tk.LEFT, padx=(0, 4))
        self._btn(btn_row, "Deploy to Selected Drive",
                  self._usb_deploy_selected).pack(side=tk.LEFT, padx=4)
        self._btn(btn_row, "Fix USB GRUB Config",
                  self._usb_fix_grub).pack(side=tk.LEFT, padx=4)
        self._btn(btn_row, "Open Reimager Scripts",
                  self._usb_open_scripts).pack(side=tk.RIGHT)

        # Drive list
        drives_lf = self._lf(f, "Detected ExFAT Drives")
        col_frame = ttk.Frame(drives_lf)
        col_frame.pack(fill=tk.BOTH, expand=True)
        self._usb_listbox = tk.Listbox(col_frame, height=6,
                                        bg=self._p["entry_bg"],
                                        fg=self._p["entry_fg"],
                                        selectbackground=self._p["select_bg"],
                                        font=("Consolas", 9))
        sb_usb = ttk.Scrollbar(col_frame, command=self._usb_listbox.yview)
        self._usb_listbox.configure(yscrollcommand=sb_usb.set)
        sb_usb.pack(side=tk.RIGHT, fill=tk.Y)
        self._usb_listbox.pack(fill=tk.BOTH, expand=True)

        # Profile selector
        prof_lf = self._lf(f, "Reimager Profile (written to USB)")
        self._usb_profile = tk.StringVar(value="standard")
        for val, lbl in (("lean",     "Lean — Ubuntu minimal + phi3:mini  (16 GB+)"),
                          ("standard", "Standard — Ubuntu + mistral:7b + Factbook  (64 GB+)"),
                          ("full",     "Full — Standard + OLMo2 + Molmo vision  (128 GB+)")):
            ttk.Radiobutton(prof_lf, text=lbl,
                             variable=self._usb_profile, value=val).pack(anchor=tk.W)

        # GRUB fix section
        grub_lf = self._lf(f, "GRUB Repair  (fix 'grub>' shell on boot)")
        ttk.Label(grub_lf,
                  text="If your CITL USB boots to a GRUB shell instead of the menu,\n"
                       "select the USB device below and click 'Fix USB GRUB Config'.",
                  font=("Consolas", 8), justify="left").pack(anchor=tk.W)
        grub_row = ttk.Frame(grub_lf)
        grub_row.pack(fill=tk.X, pady=4)
        ttk.Label(grub_row, text="USB device:").pack(side=tk.LEFT, padx=(0, 4))
        self._grub_dev = ttk.Entry(grub_row, width=16)
        self._grub_dev.insert(0, "/dev/sdb")
        self._grub_dev.pack(side=tk.LEFT, padx=4)
        ttk.Label(grub_row,
                  text="(run as root — requires grub-install on host)",
                  font=("Consolas", 7)).pack(side=tk.LEFT, padx=8)

        # Log output
        log_lf = self._lf(f, "Output", expand=True)
        self._usb_log = self._scrolled_text(log_lf, height=6)
        self._usb_log.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)

        # ── Fleet Sync ───────────────────────────────────────────────────────
        fleet_lf = self._lf(f, "Fleet Update  —  Push to All Connected USB Drives")
        ttk.Label(fleet_lf,
                  text="Select source (the USB with updated CITL Reimager), "
                       "scan targets, then sync all at once.",
                  wraplength=700, justify="left").pack(anchor=tk.W, pady=(0, 4))

        src_row = ttk.Frame(fleet_lf)
        src_row.pack(fill=tk.X, pady=2)
        ttk.Label(src_row, text="Source USB device:").pack(side=tk.LEFT, padx=(0, 4))
        self._fleet_src = ttk.Entry(src_row, width=14)
        self._fleet_src.insert(0, "/dev/sdb")
        self._fleet_src.pack(side=tk.LEFT, padx=4)
        ttk.Label(src_row,
                  text="(leave blank to auto-detect)", font=("Consolas", 7)
                  ).pack(side=tk.LEFT, padx=4)

        fleet_btn_row = ttk.Frame(fleet_lf)
        fleet_btn_row.pack(fill=tk.X, pady=2)
        self._btn(fleet_btn_row, "Scan Fleet Drives",
                  self._fleet_scan).pack(side=tk.LEFT, padx=(0, 4))
        self._btn(fleet_btn_row, "Sync All Fleet Drives",
                  self._fleet_sync_all).pack(side=tk.LEFT, padx=4)
        self._btn(fleet_btn_row, "Dry Run (preview only)",
                  lambda: self._fleet_sync_all(dry_run=True)).pack(side=tk.LEFT, padx=4)

        fleet_drives_lf = self._lf(fleet_lf, "Detected Target Drives")
        self._fleet_listbox = tk.Listbox(fleet_drives_lf, height=5, selectmode=tk.MULTIPLE,
                                          bg=self._p["entry_bg"], fg=self._p["entry_fg"],
                                          selectbackground=self._p["select_bg"],
                                          font=("Consolas", 9))
        fleet_sb = ttk.Scrollbar(fleet_drives_lf, command=self._fleet_listbox.yview)
        self._fleet_listbox.configure(yscrollcommand=fleet_sb.set)
        fleet_sb.pack(side=tk.RIGHT, fill=tk.Y)
        self._fleet_listbox.pack(fill=tk.BOTH, expand=True)

        self._usb_scan_drives()

    def _usb_script_path(self) -> str:
        here = Path(__file__).resolve().parent
        for candidate in (
            here.parent / "CITL-Cannakit" / "reimager",
            here / "reimager",
            Path("CITL-Cannakit") / "reimager",
        ):
            if candidate.exists():
                return str(candidate)
        return str(here.parent / "CITL-Cannakit" / "reimager")

    def _usb_scan_drives(self):
        self._usb_listbox.delete(0, tk.END)
        self._log(self._usb_log, "Scanning for ExFAT drives…\n", "head")

        def _run():
            drives = []
            if platform.system() == "Windows":
                try:
                    out = subprocess.check_output(
                        ["powershell", "-NoProfile", "-Command",
                         "Get-Volume | Where-Object {$_.FileSystemType -eq 'ExFAT'} | "
                         "Select-Object DriveLetter,Size,FileSystemLabel | "
                         "ConvertTo-Csv -NoTypeInformation"],
                        text=True, timeout=15)
                    for line in out.strip().splitlines()[1:]:
                        parts = [p.strip('"') for p in line.split(",")]
                        if parts and parts[0]:
                            letter, size_b, label = parts[0], parts[1], parts[2]
                            size_gb = int(size_b) // (1024 ** 3) if size_b.isdigit() else "?"
                            drives.append(f"{letter}:\\  [{label or 'unlabelled'}  {size_gb} GB]")
                except Exception as e:
                    drives.append(f"ERROR: {e}")
            else:
                deploy_sh = Path(self._usb_script_path()) / "deploy_reimager_to_usb.sh"
                if deploy_sh.exists():
                    try:
                        out = subprocess.check_output(
                            ["bash", str(deploy_sh), "--list-only"],
                            text=True, timeout=10)
                        for line in out.strip().splitlines():
                            if line.startswith("DRIVE:"):
                                drives.append(line[6:].replace("|", "  "))
                            elif line == "NO_EXFAT_DRIVES":
                                drives.append("No ExFAT drives detected")
                    except Exception as e:
                        drives.append(f"ERROR: {e}")
                else:
                    try:
                        out = subprocess.check_output(
                            ["lsblk", "-rno", "PATH,FSTYPE,LABEL,SIZE"],
                            text=True, timeout=5)
                        for line in out.splitlines():
                            cols = line.split()
                            if len(cols) >= 2 and cols[1] == "exfat":
                                label = cols[2] if len(cols) > 2 else "unlabelled"
                                size  = cols[3] if len(cols) > 3 else "?"
                                drives.append(f"{cols[0]}  [{label}  {size}]")
                    except Exception as e:
                        drives.append(f"ERROR: {e}")

            def _update():
                self._usb_listbox.delete(0, tk.END)
                if not drives:
                    self._log(self._usb_log, "No ExFAT drives found.\n", "warn")
                    self._usb_listbox.insert(tk.END, "  No ExFAT drives detected")
                else:
                    for d in drives:
                        self._usb_listbox.insert(tk.END, f"  {d}")
                    self._log(self._usb_log,
                              f"Found {len(drives)} ExFAT drive(s).\n", "ok")
            self.after(0, _update)

        threading.Thread(target=_run, daemon=True).start()

    def _usb_deploy_selected(self):
        sel = self._usb_listbox.curselection()
        if not sel:
            messagebox.showwarning("Select Drive", "Select an ExFAT drive from the list first.")
            return
        entry = self._usb_listbox.get(sel[0]).strip()
        profile = self._usb_profile.get()

        # Extract device/path from the listbox entry
        dev_or_path = entry.split()[0] if entry else ""
        if not dev_or_path or "No ExFAT" in entry:
            messagebox.showwarning("No Drive", "No valid drive selected.")
            return

        if not messagebox.askyesno(
                "Confirm Deploy",
                f"Deploy CITL Reimager ({profile}) to:\n  {dev_or_path}\n\nThis will write files to that drive."):
            return

        self._log(self._usb_log,
                  f"Deploying CITL Reimager ({profile}) → {dev_or_path}…\n", "head")

        def _run():
            script_dir = self._usb_script_path()
            deploy_sh = str(Path(script_dir) / "deploy_reimager_to_usb.sh")

            try:
                if platform.system() == "Windows":
                    # Windows: use robocopy to copy script dir to ExFAT drive
                    dest = f"{dev_or_path}citl_reimager"
                    cmd = ["robocopy", script_dir, dest,
                           "/E", "/R:2", "/W:1", "/NFL", "/NDL", "/NJH"]
                    r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
                    # robocopy exits 1 on success (files copied)
                    ok = r.returncode in (0, 1, 2, 3)
                    out = r.stdout[:800] if ok else (r.stderr or r.stdout)[:800]
                    tag = "ok" if ok else "err"
                    result = f"DEPLOYED:{dest}" if ok else f"FAILED:{r.returncode}"
                else:
                    # Linux: use deploy script with sudo
                    if dev_or_path.startswith("/dev/"):
                        args = ["sudo", "bash", deploy_sh,
                                "--target-dev", dev_or_path, "--quiet"]
                    else:
                        args = ["sudo", "bash", deploy_sh,
                                "--target-mount", dev_or_path, "--quiet"]
                    r = subprocess.run(args, capture_output=True, text=True, timeout=300)
                    out = (r.stdout + r.stderr)[:800]
                    tag = "ok" if r.returncode == 0 else "err"
                    result = out.strip()

                def _update(o=out, t=tag, res=result):
                    self._log(self._usb_log, o + "\n", t)
                    if "DEPLOYED:" in res:
                        messagebox.showinfo("Deploy Complete",
                                            f"CITL Reimager deployed successfully!\n\n{res}")
                    elif "FAILED:" in res:
                        messagebox.showerror("Deploy Failed", res)
                self.after(0, _update)

            except Exception as e:
                self.after(0, lambda e=e: (
                    self._log(self._usb_log, f"ERROR: {e}\n", "err"),
                ))

        threading.Thread(target=_run, daemon=True).start()

    def _usb_fix_grub(self):
        dev = self._grub_dev.get().strip()
        if not dev:
            messagebox.showwarning("No Device", "Enter the USB device (e.g. /dev/sdb).")
            return
        if platform.system() == "Windows":
            messagebox.showinfo("Windows", "GRUB repair must run on the Ubuntu mainframe.\n"
                                           "Run: sudo bash fix_usb_grub.sh /dev/sdb")
            return

        script_dir = self._usb_script_path()
        fix_sh = str(Path(script_dir) / "fix_usb_grub.sh")
        if not Path(fix_sh).exists():
            messagebox.showerror("Script Missing",
                                  f"fix_usb_grub.sh not found in {script_dir}")
            return

        self._log(self._usb_log, f"Running GRUB repair on {dev}…\n", "head")

        def _run():
            r = subprocess.run(
                ["sudo", "bash", fix_sh, dev],
                capture_output=True, text=True, timeout=120)
            out = (r.stdout + r.stderr)[:1200]
            tag = "ok" if r.returncode == 0 else "err"
            self.after(0, lambda: self._log(self._usb_log, out + "\n", tag))

        threading.Thread(target=_run, daemon=True).start()

    def _usb_open_scripts(self):
        script_dir = self._usb_script_path()
        opened = False
        try:
            if platform.system() == "Windows":
                subprocess.Popen(["explorer", script_dir])
                opened = True
            else:
                for opener in ("xdg-open", "nautilus", "thunar", "dolphin", "pcmanfm"):
                    if shutil.which(opener):
                        subprocess.Popen([opener, script_dir])
                        opened = True
                        break
        except Exception as e:
            self._log(self._usb_log, f"Cannot open folder: {e}\n", "warn")
        if not opened:
            self._log(self._usb_log, f"Scripts at: {script_dir}\n", "dim")

    # ── Fleet scan ────────────────────────────────────────────────────────────
    def _fleet_scan(self):
        self._fleet_listbox.delete(0, tk.END)
        self._log(self._usb_log, "Scanning for fleet target drives…\n", "head")
        src_dev = self._fleet_src.get().strip()

        def _run():
            drives = []
            script_dir = self._usb_script_path()
            fleet_sh = str(Path(script_dir) / "fleet_sync_usb.sh")

            if platform.system() != "Windows" and Path(fleet_sh).exists():
                try:
                    out = subprocess.check_output(
                        ["bash", fleet_sh, "--list"],
                        text=True, timeout=15)
                    for line in out.strip().splitlines():
                        if line.startswith("DRIVE:"):
                            # DRIVE:path|label|size|mnt|fstype|tran
                            parts = line[6:].split("|")
                            dev_path = parts[0] if len(parts) > 0 else "?"
                            label    = parts[1] if len(parts) > 1 else ""
                            size     = parts[2] if len(parts) > 2 else ""
                            mnt      = parts[3] if len(parts) > 3 else "unmounted"
                            # Skip source device
                            if src_dev and dev_path.startswith(src_dev):
                                continue
                            drives.append(
                                f"{dev_path}  [{label or 'unlabelled'}  {size}  {mnt}]"
                            )
                        elif line == "NO_DRIVES":
                            drives.append("No ExFAT drives detected")
                except Exception as e:
                    drives.append(f"ERROR: {e}")
            elif platform.system() == "Windows":
                try:
                    out = subprocess.check_output(
                        ["powershell", "-NoProfile", "-Command",
                         "Get-Volume | Where-Object {$_.FileSystemType -eq 'ExFAT'} | "
                         "Select-Object DriveLetter,Size,FileSystemLabel | "
                         "ConvertTo-Csv -NoTypeInformation"],
                        text=True, timeout=15)
                    for line in out.strip().splitlines()[1:]:
                        cols = [c.strip('"') for c in line.split(",")]
                        if cols and cols[0]:
                            letter = cols[0] + ":\\"
                            size_gb = (int(cols[1]) // (1024**3)
                                       if cols[1].isdigit() else "?")
                            label = cols[2] if len(cols) > 2 else ""
                            drives.append(f"{letter}  [{label}  {size_gb} GB]")
                except Exception as e:
                    drives.append(f"ERROR: {e}")
            else:
                drives.append("fleet_sync_usb.sh not found — scan unavailable")

            def _update():
                self._fleet_listbox.delete(0, tk.END)
                if not drives:
                    self._fleet_listbox.insert(tk.END, "  No target ExFAT drives found")
                    self._log(self._usb_log, "No target fleet drives found.\n", "warn")
                else:
                    for d in drives:
                        self._fleet_listbox.insert(tk.END, f"  {d}")
                    self._log(self._usb_log,
                              f"Fleet scan: {len(drives)} potential target(s).\n", "ok")
            self.after(0, _update)

        threading.Thread(target=_run, daemon=True).start()

    # ── Fleet sync ────────────────────────────────────────────────────────────
    def _fleet_sync_all(self, dry_run: bool = False):
        src_dev = self._fleet_src.get().strip()
        selected = self._fleet_listbox.curselection()

        # Build target list from selection or all items
        items = (
            [self._fleet_listbox.get(i) for i in selected]
            if selected else
            [self._fleet_listbox.get(i) for i in range(self._fleet_listbox.size())]
        )
        targets = [
            line.strip().split()[0]
            for line in items
            if line.strip() and not line.strip().startswith("No ")
        ]

        if not targets:
            messagebox.showwarning("No Targets",
                                   "No fleet drives found.\nRun 'Scan Fleet Drives' first.")
            return

        mode_txt = "DRY RUN — " if dry_run else ""
        if not messagebox.askyesno(
                "Confirm Fleet Sync",
                f"{mode_txt}Sync CITL Reimager to {len(targets)} drive(s)?\n\n"
                + "\n".join(f"  • {t}" for t in targets[:8])
                + (f"\n  ...and {len(targets)-8} more" if len(targets) > 8 else "")):
            return

        self._log(self._usb_log,
                  f"{mode_txt}Starting fleet sync → {len(targets)} drive(s)…\n", "head")

        def _run():
            script_dir = self._usb_script_path()
            fleet_sh = str(Path(script_dir) / "fleet_sync_usb.sh")

            if platform.system() == "Windows":
                # Windows fleet sync: robocopy to each drive letter
                ok = 0; fail = 0
                for tgt in targets:
                    drive_letter = tgt.rstrip("\\").rstrip("/")
                    dest = os.path.join(drive_letter, "citl_reimager")
                    self.after(0, lambda t=tgt: self._log(
                        self._usb_log, f"  → {t}…\n", "dim"))
                    if dry_run:
                        self.after(0, lambda t=tgt: self._log(
                            self._usb_log, f"    DRY RUN: would copy {script_dir} → {dest}\n", "ok"))
                        ok += 1
                        continue
                    try:
                        r = subprocess.run(
                            ["robocopy", script_dir, dest,
                             "/E", "/R:1", "/W:1", "/NFL", "/NDL", "/NJH", "/NJS"],
                            capture_output=True, text=True, timeout=300)
                        if r.returncode in (0, 1, 2, 3):
                            ok += 1
                            self.after(0, lambda t=tgt: self._log(
                                self._usb_log, f"    DONE: {t}\n", "ok"))
                        else:
                            fail += 1
                            self.after(0, lambda t=tgt, rc=r.returncode: self._log(
                                self._usb_log, f"    FAILED: {t}  (rc={rc})\n", "err"))
                    except Exception as e:
                        fail += 1
                        self.after(0, lambda t=tgt, e=e: self._log(
                            self._usb_log, f"    ERROR {t}: {e}\n", "err"))
                self.after(0, lambda: self._log(
                    self._usb_log,
                    f"\nFleet sync complete: {ok} OK, {fail} failed.\n",
                    "ok" if fail == 0 else "err"))
                return

            # Linux: stream fleet_sync_usb.sh output line by line for live progress
            if not Path(fleet_sh).exists():
                self.after(0, lambda: self._log(
                    self._usb_log, "fleet_sync_usb.sh not found.\n", "err"))
                return

            args = ["sudo", "bash", fleet_sh, "--all"]
            if src_dev:
                args += ["--source", src_dev]
            if dry_run:
                args += ["--dry-run"]
            for tgt in targets:
                args += ["--target", tgt]

            try:
                proc = subprocess.Popen(
                    args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, bufsize=1)

                for line in iter(proc.stdout.readline, ""):
                    line = line.rstrip()
                    if not line:
                        continue
                    tag = "dim"
                    if line.startswith("DONE:"):
                        tag = "ok"
                    elif line.startswith("FAILED:"):
                        tag = "err"
                    elif line.startswith("PROGRESS:"):
                        tag = "dim"
                    elif line.startswith("FLEET_DONE:"):
                        tag = "ok"
                    self.after(0, lambda l=line, t=tag: self._log(
                        self._usb_log, l + "\n", t))

                proc.wait(timeout=600)
                rc = proc.returncode
                self.after(0, lambda: self._log(
                    self._usb_log,
                    f"\nFleet sync finished (exit {rc}).\n",
                    "ok" if rc == 0 else "err"))

            except Exception as e:
                self.after(0, lambda e=e: self._log(
                    self._usb_log, f"Fleet sync error: {e}\n", "err"))

        threading.Thread(target=_run, daemon=True).start()

# ── Common port names ─────────────────────────────────────────────────────────
_PORT_NAMES = {
    21: "FTP", 22: "SSH", 23: "Telnet", 25: "SMTP", 53: "DNS",
    80: "HTTP", 110: "POP3", 135: "RPC", 139: "NetBIOS", 143: "IMAP",
    443: "HTTPS", 445: "SMB", 3389: "RDP", 5900: "VNC",
    8080: "HTTP-Alt", 8443: "HTTPS-Alt", 11434: "Ollama",
}


# ─────────────────────────────────────────────────────────────────────────────
# Standalone entry points (for separate EXE builds)
# ─────────────────────────────────────────────────────────────────────────────

def run_query_only():
    """Entry point: Query-only mini-app."""
    app = FlexTroubleshooterApp()
    app.title("FLEX Ask — RAG Query")
    app._nb.select(0)
    for i in range(1, app._nb.index("end")):
        app._nb.tab(i, state="hidden")
    app.geometry("820x580")
    app.mainloop()

def run_diagnostics_only():
    """Entry point: Diagnostics-only mini-app."""
    app = FlexTroubleshooterApp()
    app.title("FLEX IT Diagnostics")
    app._nb.select(1)
    for i in [0, 2, 3, 4, 5]:
        app._nb.tab(i, state="hidden")
    app.geometry("900x660")
    app.mainloop()

def run_ticket_only():
    """Entry point: Ticket Writer mini-app."""
    app = FlexTroubleshooterApp()
    app.title("FLEX Ticket Writer")
    app._nb.select(2)
    for i in [0, 1, 3, 4, 5]:
        app._nb.tab(i, state="hidden")
    app.geometry("900x620")
    app.mainloop()

def run_index_builder_only():
    """Entry point: Index Builder mini-app."""
    app = FlexTroubleshooterApp()
    app.title("FLEX Index Builder")
    app._nb.select(3)
    for i in [0, 1, 2, 4, 5]:
        app._nb.tab(i, state="hidden")
    app.geometry("820x560")
    app.mainloop()

def main():
    """Full CITL FLEX Troubleshooter."""
    app = FlexTroubleshooterApp()
    app.mainloop()


if __name__ == "__main__":
    main()
