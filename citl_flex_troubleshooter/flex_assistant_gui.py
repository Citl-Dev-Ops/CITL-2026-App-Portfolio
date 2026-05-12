"""
Adapt Factbook UI for the FLEX Troubleshooter by reusing the Factbook App
and redirecting its query function to the FLEX RAG backend (query_flex).
This preserves the Factbook layout, theme, and tools while answering from
the FLEX corpus.
"""
from pathlib import Path
import importlib.util
import sys


HERE = Path(__file__).resolve().parent
REPO = HERE.parent


def _load_factbook_module():
    """Load the real factbook_assistant_gui.py file, not the frozen wrapper."""
    candidates = [
        REPO / "factbook-assistant" / "factbook_assistant_gui.py",
        HERE / "factbook-assistant" / "factbook_assistant_gui.py",
        REPO / "_internal" / "factbook-assistant" / "factbook_assistant_gui.py",
    ]

    fb_gui = next((p for p in candidates if p.is_file()), None)
    if fb_gui is None:
        looked = "\n  - " + "\n  - ".join(str(p) for p in candidates)
        raise FileNotFoundError(
            "Could not locate factbook_assistant_gui.py in expected paths:" + looked
        )

    factbook_dir = fb_gui.parent
    if str(factbook_dir) not in sys.path:
        sys.path.insert(0, str(factbook_dir))

    spec = importlib.util.spec_from_file_location("factbook_assistant_gui_real", str(fb_gui))
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load module spec from: {fb_gui}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


fb = _load_factbook_module()

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
    app.title("CITL FLEX Troubleshooter - Factbook UI")
    app.mainloop()


if __name__ == '__main__':
    main()
