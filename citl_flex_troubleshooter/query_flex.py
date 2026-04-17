#!/usr/bin/env python3
"""query_flex.py

Simple query CLI for the FLEX corpus produced by `flex_builder.py`.

Reads `flex_embeddings.json` in the same folder and calls Ollama for embeddings
and generation. Designed to be a drop-in demo for students and for building an EXE.
"""
from __future__ import annotations
import json
import os
import sys
from pathlib import Path
from typing import List

import numpy as np
import requests

HERE = Path(__file__).resolve().parent
CORPUS = HERE / "flex_embeddings.json"

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
EMB_URL = f"{OLLAMA_HOST}/api/embed"
GEN_URL = f"{OLLAMA_HOST}/api/generate"
EMB_MODEL = os.environ.get("CITL_EMBED_MODEL", "nomic-embed-text")
LLM_MODEL = os.environ.get("CITL_FLEX_MODEL", "mistral:7b-instruct")


def _safe_json(r):
    try:
        return r.json()
    except Exception:
        return None


def load_corpus(path: Path):
    if not path.exists():
        raise SystemExit(f"Corpus not found: {path}\nRun flex_builder.py first.")
    data = json.loads(path.read_text(encoding="utf-8"))
    emb = np.asarray(data["embeddings"], dtype=np.float32)
    chunks = data["chunks"]
    # normalize
    emb /= (np.linalg.norm(emb, axis=1, keepdims=True) + 1e-8)
    return emb, chunks


def embed_query(text: str) -> np.ndarray:
    tries = [
        (f"{OLLAMA_HOST}/api/embed", {"model": EMB_MODEL, "input": text}),
        (f"{OLLAMA_HOST}/api/embeddings", {"model": EMB_MODEL, "prompt": text}),
    ]
    last_err = ""
    for url, payload in tries:
        try:
            r = requests.post(url, json=payload, timeout=60)
        except Exception as e:
            last_err = str(e)
            continue
        if r.status_code >= 400:
            last_err = f"HTTP {r.status_code} from {url}"
            continue
        j = _safe_json(r)
        if not j:
            last_err = f"Invalid JSON from {url}"
            continue
        # Ollama and other servers may return several shapes; check common keys
        if isinstance(j, dict):
            if "embeddings" in j and j["embeddings"]:
                vec = j["embeddings"][0]
            elif "embedding" in j:
                vec = j["embedding"]
            elif "data" in j and isinstance(j["data"], list) and j["data"]:
                # e.g., {'data':[{'embedding':[...]}]}
                dd = j["data"][0]
                vec = dd.get("embedding") or dd.get("embeddings")
                if isinstance(vec, list) and len(vec) == 1 and isinstance(vec[0], list):
                    vec = vec[0]
            else:
                vec = None
            if vec is None:
                last_err = f"No embedding in response: {j}"
                continue
            v = np.asarray(vec, dtype=np.float32)
            norm = np.linalg.norm(v) + 1e-8
            if norm == 0:
                last_err = "Zero-length embedding"
                continue
            v /= norm
            return v
        last_err = f"Unexpected response shape from {url}: {type(j)}"
    raise RuntimeError(f"Embedding failed: {last_err}")


def top_k(emb: np.ndarray, chunks: List[dict], qvec: np.ndarray, k: int) -> List[str]:
    sims = emb @ qvec
    if len(sims) == 0:
        return []
    k = max(1, min(k, len(sims)))
    idx = np.argpartition(-sims, k - 1)[:k]
    idx = idx[np.argsort(-sims[idx])]
    return [chunks[int(i)]["text"] for i in idx]


def gen_with_context(question: str, ctx: str) -> str:
    system_prompt = (
        "You are the CITL FLEX Troubleshooter. Answer ONLY using facts in the context.\n"
        "If information is missing, say you do not know. Keep answers concise.\n"
    )
    payload = {
        "model": LLM_MODEL,
        "system": system_prompt,
        "prompt": f"Context:\n{ctx}\n\nQuestion: {question}\nAnswer:",
        "stream": False,
        "options": {"temperature": 0.1},
    }
    try:
        r = requests.post(GEN_URL, json=payload, timeout=600)
        r.raise_for_status()
    except Exception as e:
        raise RuntimeError(f"Generation request failed: {e}")
    j = _safe_json(r)
    if not j:
        return "[Generation failed: invalid JSON response]"
    # Ollama-like responses may put text under several keys
    if isinstance(j, dict):
        if "response" in j:
            return str(j.get("response", "")).strip()
        if "text" in j:
            return str(j.get("text", "")).strip()
        if "choices" in j and isinstance(j["choices"], list) and j["choices"]:
            c = j["choices"][0]
            for k in ("content", "text", "message", "response"):
                if k in c:
                    return str(c.get(k, "")).strip()
    # Fallback: stringified JSON
    return str(j).strip()


def answer_question(question: str, model: str = None, host: str = None) -> str:
    """Resilient answer wrapper — falls back gracefully on any failure."""
    # Try the full RAG pipeline first
    try:
        emb, chunks = load_corpus(CORPUS)
        if len(chunks) > 0:
            qvec = embed_query(question)
            ctx_chunks = top_k(emb, chunks, qvec, 6)
            ctx = "\n---\n".join(ctx_chunks)[:2400]
            result = gen_with_context(question, ctx)
            if result and not result.startswith("["):
                return result
    except Exception:
        pass

    # Resilience patch fallback — import dynamically after path is set
    try:
        _fa = str(HERE.parent / "factbook-assistant")
        if _fa not in sys.path:
            sys.path.insert(0, _fa)
        import importlib
        _patch = importlib.import_module("citl_rag_patch")
        return _patch.flex_resilient_answer(
            question, CORPUS,
            model=model or LLM_MODEL,
            host=host or OLLAMA_HOST,
        )
    except Exception:
        pass

    # Last resort: tell the student what to do
    return (
        f"⚠  Could not answer: '{question}'\n\n"
        "Steps to fix:\n"
        "1. Make sure Ollama is running:  ollama serve\n"
        "2. In the app, go to Index Builder tab and click 'Build / Rebuild Index'\n"
        "3. Try your question again\n"
    )


def main():
    import argparse

    ap = argparse.ArgumentParser(description="Query the FLEX Troubleshooter corpus via local Ollama + RAG")
    ap.add_argument("query", help="Question to ask")
    ap.add_argument("-k", "--topk", type=int, default=6, help="Number of context chunks to retrieve")
    ap.add_argument("--maxctx", type=int, default=2400, help="Max chars of context")
    args = ap.parse_args()

    emb, chunks = load_corpus(CORPUS)
    qvec = embed_query(args.query)
    ctx_chunks = top_k(emb, chunks, qvec, args.topk)
    ctx = "\n---\n".join(ctx_chunks)[: args.maxctx]
    print(gen_with_context(args.query, ctx))


if __name__ == '__main__':
    main()
