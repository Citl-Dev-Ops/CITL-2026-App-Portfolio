"""
citl_rag_patch.py  —  CITL Factbook & FLEX Resilience Patch
═════════════════════════════════════════════════════════════
Drop-in patch that makes the RAG pipeline fault-tolerant.

Failure modes handled:
  • Ollama not running              → fallback to keyword search, show fix message
  • Embed model not pulled          → skip embedding, use keyword search
  • numpy missing                   → keyword search only
  • factbook_embeddings.json absent  → auto-trigger rebuild, answer from keywords
  • Index JSONL absent / < 5 chunks → auto-trigger rebuild, continue with what exists
  • Index files unreadable (USB RO) → write to APPDATA fallback dir
  • All RAG paths fail              → return best keyword hits, formatted by LLM if available
  • LLM generation timeout          → return formatted context chunks directly

Usage in factbook_assistant_gui.py — replace the two lines in _query_factbook:

    from citl_rag_patch import resilient_answer
    return resilient_answer(question, model=model, host=host)

And in __init__, after self._build_ui():

    from citl_rag_patch import attach_startup_check
    attach_startup_check(self)
"""
from __future__ import annotations

import json
import os
import re
import sys
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# ── Paths ─────────────────────────────────────────────────────────────────────
HERE = Path(__file__).resolve().parent

# Writable fallback dir when USB is read-only
def _writable_dir() -> Path:
    """Return a writable data dir — prefers local, falls back to APPDATA/CITL."""
    candidates = [
        HERE / "data" / "indexes",
        Path(os.environ.get("APPDATA", Path.home())) / "CITL" / "indexes",
        Path.home() / ".citl" / "indexes",
    ]
    for p in candidates:
        try:
            p.mkdir(parents=True, exist_ok=True)
            # Quick write test
            test = p / ".write_test"
            test.write_text("ok")
            test.unlink()
            return p
        except Exception:
            continue
    return HERE / "data" / "indexes"


# ── Ollama helpers ────────────────────────────────────────────────────────────

def _check_ollama(host: str, timeout: float = 3.0) -> Tuple[bool, List[str]]:
    """Returns (is_running, model_names_list)."""
    import urllib.request, urllib.error
    url = host.rstrip("/") + "/api/tags"
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode())
        models = [m["name"] for m in data.get("models", []) if isinstance(m, dict)]
        return True, models
    except Exception:
        return False, []


def _embed(text: str, host: str, emb_model: str, timeout: float = 30.0) -> Optional[List[float]]:
    import urllib.request
    for url, payload in [
        (host.rstrip("/") + "/api/embed",       {"model": emb_model, "input": text}),
        (host.rstrip("/") + "/api/embeddings",   {"model": emb_model, "prompt": text}),
    ]:
        try:
            data_bytes = json.dumps(payload).encode()
            req = urllib.request.Request(url, data=data_bytes,
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                j = json.loads(r.read().decode())
            # Multiple Ollama response shapes
            if "embeddings" in j and j["embeddings"]:
                vec = j["embeddings"][0]
                if isinstance(vec, list) and vec:
                    return vec
            if "embedding" in j and j["embedding"]:
                return j["embedding"]
        except Exception:
            continue
    return None


def _generate(prompt: str, system: str, model: str, host: str,
              timeout: float = 90.0) -> Optional[str]:
    import urllib.request
    payload = {
        "model": model,
        "system": system,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.1},
    }
    try:
        data_bytes = json.dumps(payload).encode()
        req = urllib.request.Request(
            host.rstrip("/") + "/api/generate",
            data=data_bytes,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as r:
            j = json.loads(r.read().decode())
        return j.get("response", "").strip() or None
    except Exception:
        return None


# ── Index health ──────────────────────────────────────────────────────────────

def _idx_dir() -> Path:
    cands = [HERE / "data" / "indexes", HERE / "index"]
    for p in cands:
        if p.is_dir():
            return p
    return HERE / "data" / "indexes"


def _count_all_chunks() -> int:
    """Count total chunks across all JSONL index files."""
    total = 0
    d = _idx_dir()
    if not d.is_dir():
        return 0
    for f in d.glob("*.jsonl"):
        if f.name.startswith("_"):
            continue
        try:
            total += sum(1 for line in f.open(encoding="utf-8", errors="ignore")
                         if line.strip() and not line.strip().startswith("//"))
        except Exception:
            pass
    return total


def _check_index_health() -> Dict:
    """Return dict with health info about the current index state."""
    d = _idx_dir()
    jsonl_files = list(d.glob("*.jsonl")) if d.is_dir() else []
    data_files = list(jsonl_files)  # non-underscore
    data_files = [f for f in jsonl_files if not f.name.startswith("_")]

    lib_raw = HERE / "data" / "library_raw"
    source_docs = list(lib_raw.glob("*.pdf")) + list(lib_raw.glob("*.txt")) + \
                  list(lib_raw.glob("*.docx")) + list(lib_raw.glob("*.md")) \
                  if lib_raw.is_dir() else []

    total_chunks = _count_all_chunks()

    # Check embedding JSON
    emb_json = HERE / "factbook_embeddings.json"
    emb_chunks = 0
    if emb_json.exists():
        try:
            d2 = json.loads(emb_json.read_text(encoding="utf-8"))
            emb_chunks = len(d2.get("chunks", d2.get("embeddings", [])))
        except Exception:
            emb_chunks = -1  # corrupt

    return {
        "jsonl_files":   len(data_files),
        "total_chunks":  total_chunks,
        "source_docs":   len(source_docs),
        "emb_chunks":    emb_chunks,
        "index_dir":     str(_idx_dir()),
        "healthy":       total_chunks >= 10,
        "emb_healthy":   emb_chunks > 0,
    }


def _trigger_reindex(force: bool = False, progress_cb=None):
    """Trigger auto-index rebuild (non-blocking, background thread)."""
    def _run():
        try:
            from citl_auto_index import auto_index_library, LIB_RAW, IDX_DIR
            idx_dir = _writable_dir()
            results = auto_index_library(lib_dir=LIB_RAW, idx_dir=idx_dir,
                                         force=force, progress_cb=progress_cb)
            if progress_cb:
                progress_cb("__done__", sum(results.values()))
        except Exception as e:
            if progress_cb:
                progress_cb("__error__", str(e))
    threading.Thread(target=_run, daemon=True).start()


# ── Keyword fallback ──────────────────────────────────────────────────────────

def _keyword_hits(question: str, top_k: int = 8) -> List[Dict]:
    """Keyword search — works with no Ollama."""
    try:
        from citl_auto_index import keyword_search
        idx_dir = _idx_dir()
        return keyword_search(question, idx_dir=idx_dir, top_k=top_k) or []
    except Exception:
        return []


def _format_hits_as_answer(question: str, hits: List[Dict]) -> str:
    """Format keyword hits into a readable answer without LLM."""
    if not hits:
        return ""
    lines = [f"Search results for: {question}", "─" * 50]
    for i, h in enumerate(hits[:6], 1):
        src   = h.get("source", "")
        title = h.get("title", "")
        text  = (h.get("text") or h.get("content") or "").strip()[:400]
        lines.append(f"\n[{i}] {title}  ({src})")
        lines.append(text)
    return "\n".join(lines)


def _synthesize_with_llm(question: str, context_chunks: List[Dict],
                          model: str, host: str) -> Optional[str]:
    """Ask LLM to synthesize answer from keyword-hit context chunks."""
    if not context_chunks:
        return None
    ctx = "\n\n---\n\n".join(
        f"[Source: {h.get('source','')} | {h.get('title','')}]\n"
        + (h.get("text") or h.get("content") or "")[:600]
        for h in context_chunks[:5]
    )
    system = (
        "You are CITL Assistant. Answer ONLY using the provided context passages. "
        "If the answer is not clearly in the context, say so. "
        "Be concise, accurate, and cite the source where possible."
    )
    prompt = f"Context passages:\n{ctx}\n\nQuestion: {question}\n\nAnswer:"
    return _generate(prompt, system, model, host, timeout=60.0)


# ── Main resilient answer function ───────────────────────────────────────────

_SYSTEM = (
    "You are CITL Assistant, a professional academic support assistant. "
    "Answer ONLY using verified facts from the provided context. "
    "If the context is missing or insufficient, say so clearly. "
    "Be concise, structured, and cite sources when available."
)

# Student-friendly messages for each failure mode
_MSG_OLLAMA_DOWN = (
    "⚠  Ollama is not running.\n\n"
    "Start it in a terminal with:\n"
    "    ollama serve\n\n"
    "Then click Ask again. While Ollama starts, here are the best keyword matches:\n\n"
)
_MSG_NO_MODEL = (
    "⚠  No suitable LLM found in Ollama.\n\n"
    "Pull a model first:\n"
    "    ollama pull mistral:7b-instruct\n\n"
    "Keyword search results:\n\n"
)
_MSG_NO_INDEX = (
    "⚠  The search index is empty or missing.\n\n"
    "Go to the Library / Models tab and click 'Rebuild Index'.\n"
    "Or wait — rebuilding now in the background.\n\n"
    "Keyword results (index rebuilding…):\n\n"
)
_MSG_NUMPY_MISSING = (
    "⚠  numpy is not installed — vector search unavailable.\n"
    "Keyword search is being used instead.\n\n"
)


def resilient_answer(question: str, model: str, host: str,
                     emb_model: str = "nomic-embed-text") -> str:
    """
    4-tier resilient answer pipeline:
      Tier 1 — Embedding RAG (full Ollama + numpy)
      Tier 2 — Keyword search + LLM synthesis (Ollama running, no embed model)
      Tier 3 — Keyword search, raw formatted output (no Ollama)
      Tier 4 — Guided failure message with actionable instructions
    """
    q = (question or "").strip()
    if not q:
        return ""

    host = (host or "http://127.0.0.1:11434").rstrip("/")

    # ── Pre-flight: check Ollama ───────────────────────────────────────────
    ollama_up, installed_models = _check_ollama(host)

    # ── Pre-flight: check index health ────────────────────────────────────
    health = _check_index_health()
    if not health["healthy"] and health["source_docs"] > 0:
        # Index empty but source docs exist — trigger rebuild silently
        _trigger_reindex(force=False)

    # ── TIER 1: Embedding RAG ─────────────────────────────────────────────
    if ollama_up:
        try:
            from citl_factbook_query import answer_question as _aq
            result = _aq(question, model=model, ollama_host=host)
            if result and not result.startswith("["):
                return result
        except Exception:
            pass  # fall through to tier 2

    # ── TIER 2: Keyword search + LLM synthesis ────────────────────────────
    hits = _keyword_hits(q)

    if ollama_up and installed_models:
        # Pick best available model (prefer requested, fallback to any)
        use_model = model if model in installed_models else installed_models[0]
        synth = _synthesize_with_llm(q, hits, use_model, host)
        if synth:
            preamble = ""
            if not health["healthy"]:
                preamble = _MSG_NO_INDEX
            return preamble + synth

    # ── TIER 3: Raw keyword hits, no LLM ─────────────────────────────────
    if hits:
        prefix = ""
        if not ollama_up:
            prefix = _MSG_OLLAMA_DOWN
        elif not installed_models:
            prefix = _MSG_NO_MODEL
        elif not health["healthy"]:
            prefix = _MSG_NO_INDEX
        return prefix + _format_hits_as_answer(q, hits)

    # ── TIER 4: Guided failure ────────────────────────────────────────────
    lines = ["Unable to find an answer. Here's a diagnostic summary:\n"]

    if not ollama_up:
        lines.append("• Ollama is NOT running. Start it: ollama serve")
    else:
        lines.append(f"• Ollama is running at {host}")
        if installed_models:
            lines.append(f"• Models available: {', '.join(installed_models[:4])}")
        else:
            lines.append("• No models installed. Run: ollama pull mistral:7b-instruct")

    if not health["healthy"]:
        lines.append(f"• Search index: {health['total_chunks']} chunks (too few — needs rebuild)")
        lines.append("  → Go to Library/Models tab → Rebuild Index")
        if health["source_docs"] == 0:
            lines.append("  → No source documents found in data/library_raw/")
            lines.append("    Add PDF or text files there and rebuild.")
        else:
            lines.append(f"  → {health['source_docs']} source document(s) found — rebuilding now…")
            _trigger_reindex(force=True)
    else:
        lines.append(f"• Search index: {health['total_chunks']} chunks across {health['jsonl_files']} file(s)")
        lines.append(f"• No relevant passages found for: '{q}'")
        lines.append("  Try rephrasing or check the Library tab to see what's indexed.")

    return "\n".join(lines)


# ── Startup check (hooks into GUI) ───────────────────────────────────────────

_STARTUP_DONE = False


def attach_startup_check(app) -> None:
    """
    Call this from App.__init__ after _build_ui().
    Runs a background health check and updates the GUI status label.
    app must have: fb_status_var, fb_health_var, fb_health_label, after()
    """
    global _STARTUP_DONE
    if _STARTUP_DONE:
        return
    _STARTUP_DONE = True

    def _bg():
        time.sleep(1.0)  # let GUI finish drawing

        try:
            host = getattr(app, "fb_host_var", None)
            host = host.get() if host else "http://127.0.0.1:11434"
        except Exception:
            host = "http://127.0.0.1:11434"

        problems: List[str] = []
        fixes:    List[str] = []

        # 1. Ollama check
        ollama_up, models = _check_ollama(host)
        if not ollama_up:
            problems.append("Ollama offline")
            fixes.append("Run: ollama serve")
        elif not models:
            problems.append("No LLM installed")
            fixes.append("Run: ollama pull mistral:7b-instruct")

        # 2. Index check
        health = _check_index_health()
        reindex_triggered = False
        if not health["healthy"]:
            if health["source_docs"] > 0:
                problems.append(f"Index thin ({health['total_chunks']} chunks)")
                fixes.append("Rebuilding index in background…")
                _trigger_reindex(force=False,
                                  progress_cb=lambda n, c: _on_reindex_progress(app, n, c))
                reindex_triggered = True
            else:
                problems.append("No source documents in data/library_raw/")
                fixes.append("Add course PDFs/text files to data/library_raw/ and rebuild index")

        # 3. Update GUI
        def _update():
            try:
                if not problems:
                    status = (
                        f"✓  Ollama OK ({len(models)} model{'s' if len(models)!=1 else ''})"
                        f"  |  Index: {health['total_chunks']:,} chunks across"
                        f" {health['jsonl_files']} file(s)"
                    )
                    app.fb_health_var.set(status)
                    app.fb_health_label.configure(foreground="#2e7d32")
                    app.fb_status_var.set("Ready.")
                else:
                    problem_str = "  |  ".join(problems)
                    fix_str     = "  •  ".join(fixes)
                    app.fb_health_var.set(f"⚠  {problem_str}   →  {fix_str}")
                    app.fb_health_label.configure(foreground="#c62828")
                    app.fb_status_var.set(
                        f"Action needed: {problems[0]} — see status bar above")
            except Exception:
                pass

        app.after(0, _update)

    threading.Thread(target=_bg, daemon=True).start()


def _on_reindex_progress(app, name: str, count) -> None:
    """Callback from background reindex — updates GUI when done."""
    if name == "__done__":
        def _update():
            try:
                health = _check_index_health()
                app.fb_health_var.set(
                    f"✓  Index rebuilt — {health['total_chunks']:,} chunks ready")
                app.fb_health_label.configure(foreground="#2e7d32")
                app.fb_status_var.set("Index rebuild complete. Ready.")
            except Exception:
                pass
        app.after(0, _update)
    elif name == "__error__":
        def _upd_err():
            try:
                app.fb_health_var.set(f"⚠  Index rebuild error: {count}")
                app.fb_health_label.configure(foreground="#c62828")
            except Exception:
                pass
        app.after(0, _upd_err)


# ── FLEX Troubleshooter patch (query_flex.py) ─────────────────────────────────

def flex_resilient_answer(question: str, corpus_path: Path,
                           model: str, host: str) -> str:
    """
    Resilient answer for the FLEX Troubleshooter.
    Falls back gracefully when the FLEX corpus is missing or corrupt.
    """
    q = (question or "").strip()
    if not q:
        return ""

    # Try normal FLEX RAG first
    if corpus_path.exists():
        try:
            from query_flex import load_corpus, embed_query, top_k, gen_with_context
            emb, chunks = load_corpus(corpus_path)
            if len(chunks) > 0:
                qvec  = embed_query(q)
                ctx   = "\n---\n".join(top_k(emb, chunks, qvec, 6))[:3000]
                result = gen_with_context(q, ctx)
                if result and not result.startswith("["):
                    return result
        except Exception:
            pass

    # Corpus missing or failed — explain and guide
    ollama_up, models = _check_ollama(host)
    if not corpus_path.exists():
        msg = (
            "⚠  FLEX corpus not built yet.\n\n"
            "Go to the Index Builder tab and click 'Build / Rebuild Index'.\n"
            "This only needs to be done once (or when the source document is updated).\n\n"
        )
        if not ollama_up:
            msg += "Also: Ollama is not running. Start it with: ollama serve\n"
        return msg

    # Corpus exists but RAG failed — keyword fallback on corpus text
    try:
        data = json.loads(corpus_path.read_text(encoding="utf-8"))
        chunks_raw = data.get("chunks", [])
        words = set(re.findall(r"\b\w{3,}\b", q.lower()))
        scored = []
        for c in chunks_raw:
            t = (c.get("text") or "").lower()
            score = sum(1 for w in words if w in t)
            if score > 0:
                scored.append((score, c.get("text", "")))
        scored.sort(reverse=True)
        top = [t for _, t in scored[:5]]
        if top and ollama_up and models:
            ctx = "\n---\n".join(t[:500] for t in top)
            use_model = model if model in models else models[0]
            result = _generate(
                f"Context:\n{ctx}\n\nQuestion: {q}\nAnswer:",
                "You are the CITL FLEX Troubleshooter. Answer using only the context.",
                use_model, host, timeout=60.0,
            )
            if result:
                return result
        if top:
            return _format_hits_as_answer(q, [{"title": "", "source": "FLEX corpus",
                                                 "text": t} for t in top])
    except Exception:
        pass

    return (
        f"⚠  Could not retrieve an answer for: '{q}'\n\n"
        "Possible causes:\n"
        "• Corpus may be corrupt — try rebuilding in the Index Builder tab\n"
        "• Ollama may not be running — run: ollama serve\n"
        f"• Ollama status: {'running' if ollama_up else 'OFFLINE'}\n"
    )
