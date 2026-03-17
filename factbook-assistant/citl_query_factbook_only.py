from __future__ import annotations
import os, re, json, argparse
from pathlib import Path
import numpy as np
import requests

ROOT = Path(__file__).resolve().parent
IDX = ROOT / "index_factbook"
EMB_NPY = IDX / "factbook.emb.npy"
CHUNKS = IDX / "factbook.chunks.jsonl"

def load_chunks():
    chunks = []
    with CHUNKS.open("r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                text = obj.get("text") if isinstance(obj, dict) else str(obj)
                src  = obj.get("source","factbook.txt") if isinstance(obj, dict) else "factbook.txt"
            except Exception:
                text = line
                src = "factbook.txt"
            chunks.append({"text": text, "source": src})
    return chunks

def session_no_proxy():
    s = requests.Session()
    s.trust_env = False
    return s

def ollama_embeddings(sess, host: str, model: str, prompt: str) -> np.ndarray:
    url = host.rstrip("/") + "/api/embeddings"
    r = sess.post(url, json={"model": model, "prompt": prompt}, timeout=120)
    r.raise_for_status()
    data = r.json()
    v = data.get("embedding") or data.get("data", {}).get("embedding")
    if not v:
        raise RuntimeError(f"Empty embedding response: keys={list(data.keys())}")
    q = np.asarray(v, dtype=np.float32)
    q = q / (np.linalg.norm(q) + 1e-9)
    return q

def ollama_generate(sess, host: str, model: str, prompt: str) -> str:
    url = host.rstrip("/") + "/api/generate"
    r = sess.post(url, json={"model": model, "prompt": prompt, "stream": False}, timeout=600)
    if r.status_code == 404:
        # show body for clarity
        raise RuntimeError(f"/api/generate 404: {r.text[:200]}")
    r.raise_for_status()
    data = r.json()
    return (data.get("response") or "").strip()

def parse_shortcut(q: str) -> str:
    # support "capital:laos"
    m = re.match(r"^\s*capital\s*:\s*(.+?)\s*$", q, flags=re.I)
    if m:
        country = m.group(1).strip()
        return f"What is the capital of {country}?"
    return q.strip()

def hybrid_topk(E: np.ndarray, chunks, query: str, qvec: np.ndarray, k: int, debug: bool):
    qlow = query.lower()
    # keyword boost: prioritize chunks containing important tokens
    tokens = []
    # include country token for capital shortcut
    m = re.match(r"^\s*capital\s*:\s*(.+?)\s*$", query, flags=re.I)
    if m:
        tokens.append(m.group(1).strip().lower())
    # also add all “words” >=4 chars
    tokens += [t for t in re.findall(r"[a-zA-Z]{4,}", qlow)]
    tokens = list(dict.fromkeys(tokens))  # uniq, keep order

    sims = E @ qvec  # cosine
    boost = np.zeros_like(sims)
    if tokens:
        for i, c in enumerate(chunks):
            text = c["text"].lower()
            b = 0.0
            for t in tokens[:6]:
                if t and t in text:
                    b += 1.0
            boost[i] = b

    score = sims + 3.0 * boost  # heavy keyword boost
    idx = np.argsort(-score)[:k]

    if debug:
        print("---- DEBUG TOPK ----")
        for rank, i in enumerate(idx, 1):
            txt = chunks[i]["text"]
            hit = any(t in txt.lower() for t in tokens[:6]) if tokens else False
            print(f"{rank:02d} score={score[i]:.4f} sim={sims[i]:.4f} boost={boost[i]:.1f} hit={hit} src={chunks[i]['source']}")
            print(txt[:220].replace("\n"," ") + ("..." if len(txt)>220 else ""))
        print("--------------------")
    return idx

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("query")
    ap.add_argument("-k","--topk", type=int, default=8)
    ap.add_argument("--maxctx", type=int, default=2400)
    ap.add_argument("--debug", action="store_true")
    args = ap.parse_args()

    host = os.environ.get("CITL_OLLAMA_HOST") or os.environ.get("OLLAMA_HOST") or "http://127.0.0.1:11434"
    emb_model = os.environ.get("FACTBOOK_EMBED") or "nomic-embed-text:latest"
    gen_model = os.environ.get("FACTBOOK_MODEL") or "mistral:7b-instruct"

    if not EMB_NPY.exists() or not CHUNKS.exists():
        raise SystemExit(f"ERROR: index_factbook missing. Build it first: python {ROOT/'build_factbook_index_factbook_only.py'}")

    E = np.load(EMB_NPY)
    chunks = load_chunks()

    sess = session_no_proxy()
    raw_q = args.query.strip()
    prompt_q = parse_shortcut(raw_q)

    qvec = ollama_embeddings(sess, host, emb_model, prompt_q)

    idx = hybrid_topk(E, chunks, raw_q, qvec, args.topk, args.debug)
    ctx_parts = []
    for i in idx:
        ctx_parts.append(chunks[i]["text"])
        if sum(len(x) for x in ctx_parts) >= args.maxctx:
            break
    ctx = "\n\n---\n\n".join(ctx_parts)[: args.maxctx]

    prompt = (
        "You are CITL Factbook Assistant.\n"
        "Answer the question using the provided context from the CIA World Factbook.\n"
        "If the answer is clearly present in context, answer directly and briefly.\n"
        "If not present, say: 'Not found in corpus.'\n\n"
        f"QUESTION: {prompt_q}\n\n"
        f"CONTEXT:\n{ctx}\n\n"
        "ANSWER:"
    )

    ans = ollama_generate(sess, host, gen_model, prompt)
    print(ans.strip() if ans.strip() else "Not found in corpus.")

if __name__ == "__main__":
    main()
