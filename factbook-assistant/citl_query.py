#!/usr/bin/env python3
from __future__ import annotations

import argparse, json, os, sys
from pathlib import Path

import numpy as np
import requests

def session() -> requests.Session:
    s = requests.Session()
    s.trust_env = False
    return s

def host() -> str:
    h = (os.environ.get("CITL_OLLAMA_HOST") or os.environ.get("OLLAMA_HOST") or "http://127.0.0.1:11434").strip().strip('"').strip("'")
    if not h.startswith("http://") and not h.startswith("https://"):
        h = "http://" + h
    h = h.replace("http://localhost","http://127.0.0.1").replace("https://localhost","https://127.0.0.1")
    return h.rstrip("/")

def extract_embedding(data: dict) -> list[float]:
    emb = data.get("embedding") or []
    if not emb and isinstance(data.get("data"), list) and data["data"] and isinstance(data["data"][0], dict):
        emb = data["data"][0].get("embedding") or data["data"][0].get("vector") or []
    if not emb and isinstance(data.get("embeddings"), list) and data["embeddings"]:
        emb = data["embeddings"][0] or []
    if not emb:
        raise RuntimeError(f"No embedding in response. keys={list(data.keys())}")
    return emb

def embed_text(text: str, model: str) -> np.ndarray:
    s = session()
    r = s.post(host() + "/api/embeddings", json={"model": model, "prompt": text}, timeout=90)
    r.raise_for_status()
    v = np.asarray(extract_embedding(r.json()), dtype=np.float32)
    if v.size == 0:
        raise RuntimeError("Embedding returned empty vector")
    # normalize
    n = np.linalg.norm(v)
    return v / (n + 1e-9)

def ollama_generate(prompt: str, model: str, num_ctx: int = 4096, temperature: float = 0.2) -> str:
    s = session()
    h = host()
    gen_url  = h + "/api/generate"
    chat_url = h + "/api/chat"

    options = {"num_ctx": int(num_ctx), "temperature": float(temperature)}
    # try generate first
    r = s.post(gen_url, json={"model": model, "prompt": prompt, "stream": False, "options": options}, timeout=600)
    if r.status_code in (404, 405):
        r = s.post(chat_url, json={"model": model, "messages": [{"role":"user","content": prompt}], "stream": False, "options": options}, timeout=600)
    r.raise_for_status()
    data = r.json()

    if isinstance(data, dict):
        if data.get("response"):
            return str(data["response"])
        msg = data.get("message")
        if isinstance(msg, dict) and msg.get("content"):
            return str(msg["content"])
    return json.dumps(data)[:2000]

def load_index(idx_dir: Path):
    emb_path = idx_dir / "factbook.emb.npy"
    chunks_path = idx_dir / "factbook.chunks.jsonl"
    if not emb_path.exists() or not chunks_path.exists():
        raise FileNotFoundError("Index files missing. Need factbook.emb.npy and factbook.chunks.jsonl")

    emb = np.load(emb_path, mmap_mode="r")
    chunks = []
    with chunks_path.open("r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line: continue
            try:
                chunks.append(json.loads(line))
            except Exception:
                continue
    if len(chunks) == 0:
        raise RuntimeError("chunks.jsonl loaded 0 chunks")
    if emb.shape[0] != len(chunks):
        # allow mismatch if chunks file changed; clamp
        n = min(emb.shape[0], len(chunks))
        emb = emb[:n]
        chunks = chunks[:n]
    return emb, chunks

def top_k(emb: np.ndarray, q: np.ndarray, k: int):
    # normalize emb rows on the fly (safe for memmap)
    norms = np.linalg.norm(emb, axis=1) + 1e-9
    sims = (emb @ q) / norms  # (N,)
    k = max(1, min(int(k), sims.shape[0]))
    idx = np.argpartition(-sims, k-1)[:k]
    idx = idx[np.argsort(-sims[idx])]
    return idx, sims[idx]

def main():
    ap = argparse.ArgumentParser(description="CITL Factbook query (RAG + Ollama)")
    ap.add_argument("query", help="question, e.g. capital:laos")
    ap.add_argument("-k", "--topk", type=int, default=8)
    ap.add_argument("--maxctx", type=int, default=2400)
    ap.add_argument("--temperature", type=float, default=0.2)
    ap.add_argument("--numctx", type=int, default=4096)
    args = ap.parse_args()

    root = Path(__file__).resolve().parent
    idx_dir = root / "index"
    emb, chunks = load_index(idx_dir)

    embed_model = os.environ.get("FACTBOOK_EMBED", "nomic-embed-text:latest")
    llm_model = os.environ.get("FACTBOOK_MODEL", os.environ.get("CITL_LLM_MODEL","mistral:7b-instruct"))

    qvec = embed_text(args.query, embed_model)
    idxs, sims = top_k(emb, qvec, args.topk)

    ctx_parts = []
    total = 0
    for i in idxs:
        t = str(chunks[int(i)].get("text",""))
        if not t: continue
        if total + len(t) > args.maxctx:
            t = t[: max(0, args.maxctx - total)]
        if t:
            ctx_parts.append(t)
            total += len(t)
        if total >= args.maxctx:
            break

    ctx = "\n\n---\n\n".join(ctx_parts)

    prompt = (
        "You are a helpful offline assistant. Answer using ONLY the provided context. "
        "If the context does not contain the answer, say so briefly.\n\n"
        f"CONTEXT:\n{ctx}\n\n"
        f"QUESTION:\n{args.query}\n\n"
        "ANSWER:"
    )

    ans = ollama_generate(prompt, llm_model, num_ctx=args.numctx, temperature=args.temperature)
    print(ans.strip())

if __name__ == "__main__":
    main()
