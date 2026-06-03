import re
import json
import numpy as np
from pathlib import Path
import argparse
import requests

DATA = Path("factbook_embeddings.json")
FACTBOOK = Path("factbook.txt")

LLM = "mistral:7b-instruct"
GEN_URL = "http://localhost:11434/api/generate"
EMB_URL = "http://localhost:11434/api/embed"
EMBED_MODEL = "nomic-embed-text"

def load_data():
    d = json.loads(DATA.read_text(encoding="utf-8"))
    emb = np.asarray(d["embeddings"], dtype=np.float32)
    ch = d["chunks"]
    return emb, ch

def embed_query(q: str):
    r = requests.post(EMB_URL, json={"model": EMBED_MODEL, "input": q})
    r.raise_for_status()
    out = r.json()
    vec = out.get("embedding") or out.get("embeddings", [{}])[0].get("embedding")
    v = np.asarray(vec, dtype=np.float32)
    return v / (np.linalg.norm(v) + 1e-8)

def top_k(emb, chunks, qvec, k):
    sims = emb @ qvec
    k = min(k, len(sims))
    idx = np.argpartition(-sims, k)[:k]
    idx = idx[np.argsort(-sims[idx])]
    return [chunks[int(i)]["text"] for i in idx]

def regex_search(pattern: str, max_hits=8):
    raw = FACTBOOK.read_text(encoding="utf-8", errors="ignore")
    flags = re.IGNORECASE | re.DOTALL | re.MULTILINE

    results = []
    for m in re.finditer(pattern, raw, flags):
        start = max(0, m.start() - 400)
        end = min(len(raw), m.end() + 400)
        results.append(raw[start:end])
        if len(results) >= max_hits:
            break
    return results

def shortcut(q: str):
    m = re.match(r"(?i)\s*(capital|population|gdp|internet code|currency)\s*:\s*(.+)$", q.strip())
    if not m:
        return None
    field, name = m.group(1).lower(), m.group(2).strip()
    esc = re.escape(name)

    mapping = {
        "capital": rf"^{esc}\b.*?(Capital[^:\n]*:\s*[^\n]+)",
        "population": rf"^{esc}\b.*?(Population[^:\n]*:\s*[^\n]+)",
        "gdp": rf"^{esc}\b.*?(GDP.*?(?:\n.*){{0,3}})",
        "internet code": rf"^{esc}\b.*?(Internet country code.*)",
        "currency": rf"^{esc}\b.*?(Currency.*?(?:\n.*){{0,3}})"
    }
    return mapping[field]

def gen_response(q, ctx):
    sys_msg = (
        "You are CITL Assistant. "
        "You answer ONLY using the provided factbook context. "
        "If the answer is not present, respond 'I do not know'."
    )

    payload = {
        "model": LLM,
        "system": sys_msg,
        "prompt": f"Context:\n{ctx}\n\nQuestion: {q}\nAnswer:",
        "stream": False,
        "options": {"temperature": 0.2}
    }

    r = requests.post(GEN_URL, json=payload)
    r.raise_for_status()
    return r.json().get("response", "").strip()

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("query", type=str)
    parser.add_argument("--regex", action="store_true")
    parser.add_argument("--topk", type=int, default=5)
    parser.add_argument("--maxctx", type=int, default=5000)
    args = parser.parse_args()

    emb, chunks = load_data()

    if args.regex:
        ctx = "\n---\n".join(regex_search(args.query, args.topk))[:args.maxctx]
        print(gen_response(args.query, ctx))
        return

    sc = shortcut(args.query)
    if sc:
        ctx = "\n---\n".join(regex_search(sc, args.topk))[:args.maxctx]
        print(gen_response(args.query, ctx))
        return

    qvec = embed_query(args.query)
    ctx = "\n---\n".join(top_k(emb, chunks, qvec, args.topk))[:args.maxctx]
    print(gen_response(args.query, ctx))

if __name__ == "__main__":
    main()
