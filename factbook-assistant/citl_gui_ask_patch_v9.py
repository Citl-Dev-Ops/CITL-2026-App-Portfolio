from __future__ import annotations
import os, sys, threading, subprocess, json
from urllib.request import Request, urlopen
import tkinter as tk
from tkinter import simpledialog

def _get_models(host: str) -> set[str]:
    try:
        req = Request(host.rstrip("/") + "/api/tags")
        with urlopen(req, timeout=3) as r:
            data = json.loads(r.read().decode("utf-8","ignore"))
        return set(m.get("name","") for m in data.get("models",[]) if m.get("name"))
    except Exception:
        return set()

def apply(App):
    host = os.environ.get("CITL_OLLAMA_HOST") or os.environ.get("OLLAMA_HOST") or "http://127.0.0.1:11434"
    models = _get_models(host)

    def _bad(s: str) -> bool:
        s = (s or "").strip()
        if not s: return True
        if s.isdigit() and len(s) >= 3: return True        # 4096 etc
        low = s.lower()
        if low.endswith(".txt"): return True
        if "factbook.txt" in low: return True
        if s in models: return True                         # model tag selected instead of question
        if low.startswith("factbook (") and "factbook.txt" in low: return True
        return False

    def _walk(w):
        for ch in w.winfo_children():
            yield ch
            yield from _walk(ch)

    def _pick_from_widgets(app) -> str:
        # Prefer focused widget
        try:
            w = app.focus_get()
            if w is not None:
                cls = w.winfo_class()
                if cls in ("Entry","TEntry","TCombobox"):
                    v = (w.get() or "").strip()
                    if not _bad(v): return v
                if cls == "Text":
                    v = (w.get("1.0","end") or "").strip()
                    v = v.splitlines()[0].strip() if v else ""
                    if not _bad(v): return v
        except Exception:
            pass

        # Try common vars
        for name in ("query_var","prompt_var","question_var","q_var","input_var","user_var"):
            v = getattr(app, name, None)
            try:
                s = (v.get() or "").strip()
            except Exception:
                s = ""
            if not _bad(s): return s

        # Scan entries/texts, pick non-bad
        cands = []
        for w in _walk(app):
            try: cls = w.winfo_class()
            except Exception: continue
            if cls in ("Entry","TEntry","TCombobox"):
                try:
                    s = (w.get() or "").strip()
                    if not _bad(s): cands.append(s)
                except Exception:
                    pass
            if cls == "Text":
                try:
                    state = str(w.cget("state")).lower()
                except Exception:
                    state = "normal"
                if state == "disabled": continue
                try:
                    s = (w.get("1.0","end") or "").strip()
                    s = s.splitlines()[0].strip() if s else ""
                    if not _bad(s): cands.append(s)
                except Exception:
                    pass
        # Prefer question-ish text
        for s in cands:
            if "?" in s or " " in s or ":" in s:
                return s
        return cands[0] if cands else ""

    def _output_widget(app):
        texts = []
        for w in _walk(app):
            try:
                if w.winfo_class() == "Text":
                    texts.append(w)
            except Exception:
                pass
        if not texts: return None
        return max(texts, key=lambda x: x.winfo_height())

    def _write_output(app, text: str):
        w = _output_widget(app)
        if w is None:
            print("[CITL][ASK] no Text widget for output")
            return
        try: w.configure(state="normal")
        except Exception: pass
        try:
            w.delete("1.0","end")
            w.insert("end", text)
        finally:
            try: w.configure(state="disabled")
            except Exception: pass

    def _set_status(app, s: str):
        try: app.status_var.set(s)
        except Exception: pass

    def ask_sync(self):
        q = _pick_from_widgets(self)
        if _bad(q):
            # popup fallback prevents students getting stuck
            default = getattr(self, "_citl_last_question", "capital:laos")
            q2 = simpledialog.askstring("CITL Factbook", "Enter your question:", initialvalue=default, parent=self)
            q = (q2 or "").strip()

        print("[CITL][ASK] selected_query:", repr(q))
        if _bad(q):
            _set_status(self, "Type a question (e.g. capital:laos) then Ask")
            return

        self._citl_last_question = q
        _set_status(self, "Working…")

        root = os.path.dirname(__file__)
        script = os.path.join(root, "citl_query_factbook_only.py")

        env = dict(os.environ)
        env.setdefault("NO_PROXY","127.0.0.1,localhost")
        env.setdefault("no_proxy","127.0.0.1,localhost")

        # Hard lock to env model (avoid random GUI selections)
        env["OLLAMA_HOST"] = env.get("CITL_OLLAMA_HOST") or env.get("OLLAMA_HOST") or "http://127.0.0.1:11434"
        env["CITL_OLLAMA_HOST"] = env["OLLAMA_HOST"]
        env["FACTBOOK_MODEL"] = env.get("FACTBOOK_MODEL") or "mistral:7b-instruct"
        env["FACTBOOK_EMBED"] = env.get("FACTBOOK_EMBED") or "nomic-embed-text:latest"

        cmd = [sys.executable, script, q, "-k", "8", "--maxctx", "2400"]
        print("[CITL][ASK] cmd:", " ".join(cmd))

        p = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=900)
        out = (p.stdout or "").strip()
        err = (p.stderr or "").strip()
        combined = (out + ("\n\n" + err if err else "")).strip() or "(no output)"

        print("[CITL][ASK] rc=", p.returncode)
        print("[CITL][ASK] out(head):", combined[:600].replace("\n","\\n"))

        _write_output(self, combined)
        _set_status(self, "Done" if p.returncode == 0 else "Query error (see output)")

    def ask_async(self):
        threading.Thread(target=ask_sync, args=(self,), daemon=True).start()

    App.ask_sync = ask_sync
    App.ask_async = ask_async
    print("[CITL][ASK] v9 patch applied (popup fallback enabled)")
