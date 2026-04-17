"""
Adapt Factbook UI for the FLEX Troubleshooter by reusing the Factbook App
and redirecting its query function to the FLEX RAG backend (query_flex).
This preserves the Factbook layout, theme, and tools while answering from
the FLEX corpus.
"""
from pathlib import Path
import os
import sys

# Ensure the factbook-assistant package path is importable when run as a script
HERE = Path(__file__).resolve().parent
REPO = HERE.parent
factbook_dir = REPO / 'factbook-assistant'
if str(factbook_dir) not in sys.path:
    sys.path.insert(0, str(factbook_dir))

# Import the Factbook GUI App and monkeypatch its query backend
import importlib
try:
    fb = importlib.import_module('factbook_assistant_gui')
except Exception:
    # Fallback: load by file path
    spec = importlib.util.spec_from_file_location('factbook_assistant_gui', str(factbook_dir / 'factbook_assistant_gui.py'))
    fb = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fb)

try:
    import citl_flex_troubleshooter.query_flex as qf
except Exception:
    # allow relative import when run as script
    from . import query_flex as qf


def _flex_query_replacement(question: str, model: str, host: str) -> str:
    """Replacement for Factbook's `_query_factbook` that uses `query_flex`.

    The signature matches Factbook's expected `(question, model, host)`.
    """
    try:
        corpus_path = Path(__file__).resolve().parent / "flex_embeddings.json"
        emb, chunks = qf.load_corpus(corpus_path)
        qvec = qf.embed_query(question)
        ctx_chunks = qf.top_k(emb, chunks, qvec, 6)
        ctx = "\n---\n".join(ctx_chunks)[:2400]
        return qf.gen_with_context(question, ctx)
    except Exception as e:
        return f"[FLEX error: {e}]"


# Monkeypatch the factbook module function
fb._query_factbook = _flex_query_replacement


def main():
    app = fb.App()
    app.title("CITL FLEX Troubleshooter — Factbook UI")
    app.mainloop()


if __name__ == '__main__':
    main()

