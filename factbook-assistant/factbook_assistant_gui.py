import os
import sys
import json
import re
import threading
import shutil
from pathlib import Path

import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, filedialog

import requests

# -------------------------
# Optional classroom capture (button appears if module is present)
# -------------------------
try:
    from citl_class_capture import open_class_capture
except Exception:
    open_class_capture = None

# -------------------------
# App paths (works from ANY directory)
# -------------------------
IS_FROZEN = getattr(sys, "frozen", False)
APP_DIR = Path(sys.executable).resolve().parent if IS_FROZEN else Path(__file__).resolve().parent

def get_data_root() -> Path:
    """
    Default: per-user LOCALAPPDATA (works from any folder, no admin).
    Optional portable mode: set CITL_PORTABLE=1 to store data next to EXE/script.
    """
    portable = os.environ.get("CITL_PORTABLE", "").strip().lower() in ("1", "true", "yes")
    if portable:
        return APP_DIR / "data"

    base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
    if not base:
        return APP_DIR / "data"
    return Path(base) / "CITL_Library_Assistant"

DATA_ROOT  = get_data_root()
LIB_RAW    = DATA_ROOT / "library_raw"
INDEX_DIR  = DATA_ROOT / "indexes"
CONFIG_DIR = DATA_ROOT / "config"
RECS_DIR   = DATA_ROOT / "recordings"
CONFIG_FILE = CONFIG_DIR / "settings.json"

for d in (LIB_RAW, INDEX_DIR, CONFIG_DIR, RECS_DIR):
    d.mkdir(parents=True, exist_ok=True)

# -------------------------
# Factbook is just another book now (stored in library_raw)
# -------------------------
FACTBOOK_FILE = LIB_RAW / "factbook.txt"
FACTBOOK_LABEL = "Factbook (factbook.txt)"

# -------------------------
# Ollama
# -------------------------
OLLAMA_HOST   = os.environ.get("CITL_OLLAMA_HOST", "http://localhost:11434").rstrip("/")
DEFAULT_MODEL = os.environ.get("CITL_LLM_MODEL", "llama3.1:8b")

# -------------------------
# Retrieval rules
# -------------------------
WORD_RE = re.compile(r"[A-Za-z]{2,}")

SYSTEM_RULES = """You are CITL Offline Library Assistant.
Rules:
- Answer ONLY using the EXCERPTS provided.
- If the answer is not present in the excerpts, output exactly: NOT FOUND IN SELECTED CORPUS.
- Every bullet/claim MUST end with a citation like [doc_id]. If you can't cite it, do not include it.
- Do NOT use outside knowledge.
"""

def tokenize(s: str) -> set:
    return set(WORD_RE.findall((s or "").lower()))

def ollama_list_models():
    r = requests.get(f"{OLLAMA_HOST}/api/tags", timeout=5)
    r.raise_for_status()
    models = r.json().get("models", [])
    return sorted([m.get("name") for m in models if m.get("name")])

def ollama_generate(model: str, prompt: str, num_ctx: int = 4096, temperature: float = 0.2) -> str:
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "num_ctx": int(num_ctx),
            "temperature": float(temperature),
        },
    }
    r = requests.post(f"{OLLAMA_HOST}/api/generate", json=payload, timeout=600)
    r.raise_for_status()
    return (r.json().get("response") or "").strip()

def chunk_text(text: str, max_chars: int = 2400):
    text = (text or "").replace("\r\n", "\n")
    parts = [p.strip() for p in text.split("\n\n") if p.strip()]
    buf, n = [], 0
    for p in parts:
        if n + len(p) > max_chars and buf:
            yield "\n\n".join(buf)
            buf, n = [], 0
        buf.append(p)
        n += len(p)
    if buf:
        yield "\n\n".join(buf)

def safe_stem(p: Path) -> str:
    return re.sub(r"[^A-Za-z0-9_\-\.]+", "_", p.stem).strip("_")[:80] or "book"

def index_for_txt(txt_path: Path) -> Path:
    return INDEX_DIR / f"{safe_stem(txt_path)}_index.jsonl"

def build_index_from_txt(txt_path: Path, log=None) -> Path:
    if not txt_path.exists():
        raise FileNotFoundError(f"Missing TXT file: {txt_path}")
    out_path = index_for_txt(txt_path)
    title = txt_path.stem
    if log: log(f"Indexing: {txt_path.name} -> {out_path.name}")

    text = txt_path.read_text(encoding="utf-8", errors="ignore")
    with out_path.open("w", encoding="utf-8") as w:
        for i, ch in enumerate(chunk_text(text), 1):
            rec = {"id": f"{title}:{i}", "title": title, "text": ch}
            w.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return out_path

def index_needed(txt_path: Path) -> bool:
    idx = index_for_txt(txt_path)
    if not idx.exists():
        return True
    try:
        return idx.stat().st_mtime < txt_path.stat().st_mtime
    except Exception:
        return True

def ensure_index(txt_path: Path, log=None) -> Path:
    idx = index_for_txt(txt_path)
    if index_needed(txt_path):
        idx = build_index_from_txt(txt_path, log=log)
    return idx

def load_index(index_path: Path):
    if not index_path.exists():
        return []
    docs = []
    with index_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                docs.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return docs

def retrieve(query: str, index_path: Path, k: int = 6):
    docs = load_index(index_path)
    if not docs:
        return []
    q = tokenize(query)
    scored = []
    for d in docs:
        text = (d.get("title", "") + "\n" + d.get("text", ""))
        t = tokenize(text)
        score = len(q.intersection(t))
        if score:
            scored.append((score, d))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [d for _, d in scored[:k]]

def build_prompt(question: str, excerpts):
    blocks = []
    for d in excerpts:
        blocks.append(f"[{d.get('id','?')}] {d.get('title','')}\n{d.get('text','')}")
    context = "\n\n".join(blocks) if blocks else "(no excerpts found)"
    return f"""{SYSTEM_RULES}

EXCERPTS:
{context}

QUESTION:
{question}

ANSWER (with citations):
"""

def load_settings() -> dict:
    if not CONFIG_FILE.exists():
        return {}
    try:
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}

def save_settings(d: dict):
    try:
        CONFIG_FILE.write_text(json.dumps(d, indent=2), encoding="utf-8")
    except Exception:
        pass

def available_corpora():
    corpora = []
    # Always show Factbook choice (even if not imported yet)
    corpora.append(FACTBOOK_LABEL)
    # Other books
    for fp in sorted(LIB_RAW.glob("*.txt")):
        if fp.name.lower() == "factbook.txt":
            continue
        corpora.append(fp.name)
    return corpora

def corpus_to_txtpath(corpus_name: str) -> Path:
    if corpus_name.startswith("Factbook"):
        return FACTBOOK_FILE
    return LIB_RAW / corpus_name

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("CITL Library Assistant (Offline - Ollama)")
        self.geometry("1100x760")

        self.settings = load_settings()

        self.status = tk.StringVar(value="Status: starting…")
        self.model_var = tk.StringVar(value=self.settings.get("model", DEFAULT_MODEL))
        self.ctx_var = tk.StringVar(value=str(self.settings.get("ctx", os.environ.get("CITL_NUM_CTX", "4096"))))
        self.topk_var = tk.StringVar(value=str(self.settings.get("topk", os.environ.get("CITL_TOPK", "8"))))
        self.temp_var = tk.StringVar(value=str(self.settings.get("temp", os.environ.get("CITL_TEMP", "0.2"))))
        self.corpus_var = tk.StringVar(value=self.settings.get("corpus", FACTBOOK_LABEL))
        self.auto_index_var = tk.BooleanVar(value=bool(self.settings.get("auto_index", True)))

        self._build_ui()
        self.refresh_corpora()
        self.after(200, self.refresh_models_async)

        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _on_close(self):
        self.settings["model"] = self.model_var.get()
        self.settings["ctx"] = int(self.ctx_var.get() or "4096")
        self.settings["topk"] = int(self.topk_var.get() or "8")
        self.settings["temp"] = float(self.temp_var.get() or "0.2")
        self.settings["corpus"] = self.corpus_var.get()
        self.settings["auto_index"] = bool(self.auto_index_var.get())
        save_settings(self.settings)
        self.destroy()

    def _build_ui(self):
        top = ttk.Frame(self, padding=10)
        top.pack(fill="x")

        ttk.Label(top, text="Corpus:").pack(side="left")
        self.corpus_combo = ttk.Combobox(top, textvariable=self.corpus_var, width=40, state="readonly")
        self.corpus_combo.pack(side="left", padx=6)

        ttk.Button(top, text="Add Book (.txt)", command=self.add_book).pack(side="left", padx=6)
        ttk.Button(top, text="Import Factbook", command=self.import_factbook).pack(side="left", padx=6)
        ttk.Button(top, text="Refresh Corpora", command=self.refresh_corpora).pack(side="left", padx=6)

        ttk.Checkbutton(top, text="Auto-index", variable=self.auto_index_var).pack(side="left", padx=10)
        ttk.Button(top, text="Index Selected", command=self.index_selected_async).pack(side="left", padx=6)
        ttk.Button(top, text="Index All", command=self.index_all_async).pack(side="left", padx=6)

        ttk.Label(top, text="Model:").pack(side="left", padx=(18, 0))
        self.model_combo = ttk.Combobox(top, textvariable=self.model_var, width=22, state="readonly")
        self.model_combo.pack(side="left", padx=6)

        ttk.Label(top, text="Ctx:").pack(side="left")
        ttk.Entry(top, textvariable=self.ctx_var, width=6).pack(side="left", padx=6)

        ttk.Label(top, text="TopK:").pack(side="left")
        ttk.Entry(top, textvariable=self.topk_var, width=4).pack(side="left", padx=6)

        ttk.Label(top, text="Temp:").pack(side="left")
        ttk.Entry(top, textvariable=self.temp_var, width=4).pack(side="left", padx=6)

        ttk.Button(top, text="Refresh Models", command=self.refresh_models_async).pack(side="left", padx=6)

        if open_class_capture is not None:
            ttk.Button(top, text="Class Capture", command=self.open_capture).pack(side="left", padx=6)

        qf = ttk.Frame(self, padding=10)
        qf.pack(fill="x")
        ttk.Label(qf, text="Question:").pack(anchor="w")
        self.q_entry = ttk.Entry(qf)
        self.q_entry.pack(fill="x")
        self.q_entry.focus_set()

        btns = ttk.Frame(self, padding=10)
        btns.pack(fill="x")
        ttk.Button(btns, text="Ask", command=self.ask_async).pack(side="left")
        ttk.Button(btns, text="Clear", command=self.clear).pack(side="left", padx=8)
        ttk.Button(btns, text="Open Data Folder", command=self.open_data_folder).pack(side="left", padx=8)

        self.out = scrolledtext.ScrolledText(self, wrap="word", font=("Consolas", 11))
        self.out.pack(fill="both", expand=True, padx=10, pady=10)

        ttk.Label(self, textvariable=self.status).pack(anchor="w", padx=10, pady=(0, 10))

    def set_status(self, msg):
        self.status.set(f"Status: {msg}")

    def clear(self):
        self.out.delete("1.0", "end")

    def append(self, text):
        self.out.insert("end", text + "\n")
        self.out.see("end")

    def open_data_folder(self):
        try:
            os.startfile(str(DATA_ROOT))
        except Exception as e:
            messagebox.showerror("Open folder failed", str(e))

    def refresh_corpora(self):
        items = available_corpora()
        self.corpus_combo["values"] = items
        if self.corpus_var.get() not in items:
            self.corpus_var.set(items[0])
        self.set_status("corpora refreshed")

    def add_book(self):
        fp = filedialog.askopenfilename(
            title="Select a .txt book file",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")]
        )
        if not fp:
            return

        src = Path(fp)
        dst = LIB_RAW / src.name
        try:
            shutil.copyfile(str(src), str(dst))
            self.append(f"Added: {dst}")
            self.refresh_corpora()
            self.corpus_var.set(dst.name)

            if self.auto_index_var.get():
                self._index_one_async(dst)

        except Exception as e:
            messagebox.showerror("Add book failed", str(e))

    def import_factbook(self):
        fp = filedialog.askopenfilename(
            title="Select your Factbook .txt file",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")]
        )
        if not fp:
            return
        src = Path(fp)
        try:
            shutil.copyfile(str(src), str(FACTBOOK_FILE))
            self.append(f"Factbook imported to: {FACTBOOK_FILE}")
            self.refresh_corpora()
            self.corpus_var.set(FACTBOOK_LABEL)

            if self.auto_index_var.get():
                self._index_one_async(FACTBOOK_FILE)

        except Exception as e:
            messagebox.showerror("Import Factbook failed", str(e))

    def ensure_factbook_present_or_prompt(self) -> bool:
        if FACTBOOK_FILE.exists():
            return True
        self.append("ERROR: Factbook not imported yet.")
        if messagebox.askyesno("Factbook missing", "Factbook is not imported. Import it now?"):
            self.import_factbook()
            return FACTBOOK_FILE.exists()
        return False

    def refresh_models_async(self):
        def run():
            try:
                self.set_status("checking Ollama…")
                names = ollama_list_models()
                if not names:
                    self.set_status("Ollama OK, but no models found.")
                    return
                self.model_combo["values"] = names
                if self.model_var.get() not in names:
                    self.model_var.set(names[0])
                self.set_status("ready")
            except Exception as e:
                self.set_status("Ollama not reachable (start Ollama)")
                self.append(f"ERROR: Ollama not reachable: {e}")

        threading.Thread(target=run, daemon=True).start()

    def _index_one_async(self, txt_path: Path):
        def run():
            try:
                self.set_status(f"indexing {txt_path.name}…")
                idx = ensure_index(txt_path, log=self.append)
                self.append(f"Index ready: {idx}")
                self.set_status("index built OK")
            except Exception as e:
                self.append(f"INDEX FAILED: {e}")
                self.set_status("index failed")

        threading.Thread(target=run, daemon=True).start()

    def index_selected_async(self):
        corpus = self.corpus_var.get()
        txt_path = corpus_to_txtpath(corpus)

        if corpus.startswith("Factbook"):
            if not self.ensure_factbook_present_or_prompt():
                self.set_status("index failed")
                return

        self._index_one_async(txt_path)

    def index_all_async(self):
        def run():
            try:
                self.set_status("indexing ALL corpora…")
                items = available_corpora()
                for corpus in items:
                    txt_path = corpus_to_txtpath(corpus)

                    if corpus.startswith("Factbook") and not FACTBOOK_FILE.exists():
                        self.append("SKIP: Factbook not imported.")
                        continue

                    try:
                        idx = ensure_index(txt_path, log=self.append)
                        self.append(f"Index ready: {idx}")
                    except Exception as e:
                        self.append(f"INDEX FAILED for {txt_path.name}: {e}")

                self.set_status("all indexing complete")
            except Exception as e:
                self.append(f"INDEX ALL FAILED: {e}")
                self.set_status("index all failed")

        threading.Thread(target=run, daemon=True).start()

    def open_capture(self):
        if open_class_capture is None:
            messagebox.showerror("Class Capture unavailable", "citl_class_capture.py not found or dependencies missing.")
            return
        try:
            open_class_capture(self, RECS_DIR)
        except Exception as e:
            messagebox.showerror("Class Capture failed", str(e))

    def ask_async(self):
        q = self.q_entry.get().strip()
        if not q:
            return

        def run():
            try:
                corpus = self.corpus_var.get()
                txt_path = corpus_to_txtpath(corpus)

                # Factbook missing? Prompt to import instead of erroring.
                if corpus.startswith("Factbook"):
                    if not self.ensure_factbook_present_or_prompt():
                        self.set_status("error")
                        return

                # Ensure index automatically when Auto-index is ON
                if self.auto_index_var.get():
                    self.set_status("ensuring index…")
                    idx_path = ensure_index(txt_path, log=self.append)
                else:
                    idx_path = index_for_txt(txt_path)
                    if not idx_path.exists():
                        self.append("Index missing and Auto-index is OFF. Turn Auto-index ON or click Index Selected.")
                        self.set_status("missing index")
                        return

                self.set_status("retrieving excerpts…")
                topk = int(self.topk_var.get() or "8")
                excerpts = retrieve(q, idx_path, k=topk)

                if not excerpts:
                    self.append("NOT FOUND IN SELECTED CORPUS.")
                    self.set_status("ready (no excerpts found)")
                    return

                self.set_status("calling Ollama…")
                prompt = build_prompt(q, excerpts)
                model = self.model_var.get().strip()
                ctx = int(self.ctx_var.get() or "4096")
                temp = float(self.temp_var.get() or "0.2")

                answer = ollama_generate(model=model, prompt=prompt, num_ctx=ctx, temperature=temp)

                self.append(f"[Corpus: {corpus}]")
                self.append(f"Q: {q}\n{answer}\n---\n")
                self.set_status("ready")

            except Exception as e:
                self.append(f"ERROR: {e}")
                self.set_status("error")

        threading.Thread(target=run, daemon=True).start()

if __name__ == "__main__":
    App().mainloop()
