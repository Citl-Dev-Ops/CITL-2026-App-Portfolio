#!/usr/bin/env python3
import argparse, json, os
from pathlib import Path
import numpy as np
import requests

def _embed(host: str, embed_model: str, text: str) -> np.ndarray:
    r = requests.post(f"{host}/api/embeddings", json={"model": embed_model, "prompt": text}, timeout=60)
    r.raise_for_status()
    j = r.json()
    if "embedding" not in j or not j["embedding"]:
        raise RuntimeError(f"Embedding failed: {j}")
    return np.array(j["embedding"], dtype=np.float32)

def _generate(host: str, model: str, prompt: str) -> str:
    r = requests.post(f"{host}/api/generate", json={"model": model, "prompt": prompt, "stream": False}, timeout=180)
    r.raise_for_status()
    j = r.json()
    return (j.get("response") or "").strip()

def answer_question(question: str, model: str = "llama3.1", ollama_host: str = "http://127.0.0.1:11434",
                    index_path: str | None = None, embed_model: str = "nomic-embed-text",
                    topk: int = 6, maxctx: int = 8000) -> str:
    here = Path(__file__).resolve().parent
    if index_path is None:
        index_path = str(here / "factbook_embeddings.json")
    idxp = Path(index_path)
    if not idxp.exists():
        raise RuntimeError(f"Index missing: {idxp} (run build_corpus_index.py)")

    idx = json.loads(idxp.read_text(encoding="utf-8"))
    chunks = idx["chunks"]
    emb = np.array(idx["embeddings"], dtype=np.float32)
    q = _embed(ollama_host, embed_model, question)

    if emb.shape[1] != q.shape[0]:
        raise RuntimeError(f"Dim mismatch: index dim={emb.shape[1]} vs query dim={q.shape[0]} (embed_model={embed_model})")

    sims = emb @ q
    order = np.argsort(-sims)[:topk]
    ctx = "\n---\n".join(chunks[i] for i in order)[:maxctx]

    prompt = (
        "You are a careful reference assistant.\n"
        "Use ONLY the provided context.\n"
        "Do NOT use outside knowledge.\n"
        "If context is insufficient, output exactly: INSUFFICIENT_VERIFIED_CONTEXT.\n\n"
        f"CONTEXT:\n{ctx}\n\n"
        f"QUESTION:\n{question}\n\n"
        "ANSWER:\n"
    )
    return _generate(ollama_host, model, prompt)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="http://127.0.0.1:11434")
    ap.add_argument("--model", default="llama3.1")
    ap.add_argument("--embed-model", default="nomic-embed-text")
    ap.add_argument("--index", default=None)
    ap.add_argument("question", nargs="+")
    a = ap.parse_args()
    q = " ".join(a.question).strip()
    print(answer_question(q, model=a.model, ollama_host=a.host, index_path=a.index, embed_model=a.embed_model))

if __name__ == "__main__":
    main()
