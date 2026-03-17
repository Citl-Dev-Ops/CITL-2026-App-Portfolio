import argparse
import os
import sys
from pathlib import Path

from citl_factbook.retrieve import retrieve
from citl_factbook.ollama_client import ollama_generate

try:
    from executors import try_answer_text as _try_answer_text
except Exception:
    _try_answer_text = None

try:
    from citl_factbook.reference_query import answer_reference_question as _answer_reference_question
    from citl_factbook.reference_query import render_reference_result as _render_reference_result
except Exception:
    _answer_reference_question = None
    _render_reference_result = None
SYSTEM = """You are CITL Factbook Assistant.
Rules:
- Use ONLY the FACTBOOK EXCERPTS provided below.
- If the answer is not in the excerpts, output exactly: NOT FOUND IN FACTBOOK.
- Cite each claim with [doc_id].
"""


def _default_source() -> str:
    # package dir: .../factbook-assistant/citl_factbook
    root = Path(__file__).resolve().parents[1]
    return str(root / "factbook.txt")


def main():
    ap = argparse.ArgumentParser(description="CITL offline reference QA")
    ap.add_argument("question", nargs="+", help="Question text")
    ap.add_argument("--corpus", default=os.environ.get("CITL_CORPUS_NAME", "factbook_2023"))
    ap.add_argument("--source", default=os.environ.get("CITL_REFERENCE_SOURCE", _default_source()))
    ap.add_argument("--db", default=os.environ.get("CITL_REFERENCE_DB", str(Path(__file__).resolve().parents[1] / "data" / "reference_corpora.sqlite")))
    ap.add_argument("--config", default=os.environ.get("CITL_CORPUS_CONFIG", ""))
    ap.add_argument("--source-year", type=int, default=int(os.environ.get("CITL_SOURCE_YEAR", "2023")))
    ap.add_argument("--no-auto-ingest", action="store_true")
    args = ap.parse_args()
    question = " ".join(args.question).strip()

    # Generic reference pipeline (corpus-agnostic).
    if _answer_reference_question is not None and _render_reference_result is not None:
        try:
            res = _answer_reference_question(
                question=question,
                corpus_name=args.corpus,
                db_path=args.db,
                source_path=(args.source or None),
                config_path=(args.config or None),
                source_year=int(args.source_year),
                auto_ingest=not bool(args.no_auto_ingest),
            )
        except Exception:
            res = None
        if isinstance(res, dict) and res.get("handled"):
            print(_render_reference_result(res))
            return

    # Preferred path: deterministic entity-locked answer with citations/confidence.
    if _try_answer_text is not None:
        try:
            safe = _try_answer_text(question)
        except Exception:
            safe = None
        if safe:
            print(safe)
            return

    # enforce backend variable (optional sanity check)
    backend = os.environ.get("CITL_LLM_BACKEND", "ollama").lower()
    if backend != "ollama":
        print("ERROR: CITL_LLM_BACKEND must be 'ollama'.")
        raise SystemExit(2)
    excerpts = retrieve(question, k=int(os.environ.get("CITL_TOPK", "6")))
    if not excerpts:
        # hard fail-safe so nobody thinks it's making stuff up
        print("NOT FOUND IN FACTBOOK.")
        raise SystemExit(0)
    context = "\n\n".join(
        f"[{d.get('id','?')}] {d.get('title','')}\n{d.get('text','')}"
        for d in excerpts
    )
    prompt = f"""{SYSTEM}
FACTBOOK EXCERPTS:
{context}
QUESTION:
{question}
ANSWER (with citations):
"""
    print(ollama_generate(prompt))
if __name__ == "__main__":
    main()
