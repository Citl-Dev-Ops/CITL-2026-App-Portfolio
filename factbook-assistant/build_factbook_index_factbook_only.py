from __future__ import annotations
import os, json, time
from pathlib import Path
import numpy as np
import requests

ROOT = Path(__file__).resolve().parent
FACTBOOK = ROOT / "factbook.txt"
OUTDIR = ROOT / "index_factbook"
OUTDIR.mkdir(parents=True, exist_ok=True)

EMB_NPY = OUTDIR / "factbook.emb.npy"
CHUNKS = OUTDIR / "factbook.chunks.jsonl"
MANIFEST = OUTDIR / "manifest.json"

HOST = os.environ.get("CITL_OLLAMA_HOST") or os.environ.get("OLLAMA_HOST") or "http://127.0.0.1:11434"
EMB_MODEL = os.environ.get("FACTBOOK_EMBED") or "nomic-embed-text:latest"

def chunk_text(text: str, chunk_chars: int = 1800, overlap: int = 200):
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    i = 0
    n = len(text)
    while i < n:
        j = min(n, i + chunk_chars)
        yield text[i:j]
        if j >= n:
            break
        i = max(j - overlap, i + 1)

def emb_one(session: requests.Session, s: str):
    url = HOST.rstrip("/") + "/api/embeddings"
    r = session.post(url, json={"model": EMB_MODEL, "prompt": s}, timeout=120)
    r.raise_for_status()
    data = r.json()
    v = data.get("embedding") or data.get("data", {}).get("embedding")
    if not v:
        raise RuntimeError(f"Empty embedding response keys={list(data.keys())}")
    return np.asarray(v, dtype=np.float32)

def main():
    if not FACTBOOK.exists():
        raise SystemExit(f"Missing {FACTBOOK}")

    raw = FACTBOOK.read_text(errors="ignore")

    # build chunks
    chunks = []
    for k, ch in enumerate(chunk_text(raw)):
        t = ch.strip()
        if not t:
            continue
        chunks.append({"id": k, "source": "factbook.txt", "text": t})

    # embed
    session = requests.Session()
    session.trust_env = False  # ignore proxies
    embs = []
    t0 = time.time()
    for i, c in enumerate(chunks, 1):
        v = emb_one(session, c["text"][:4000])
        embs.append(v)
        if i % 50 == 0 or i == len(chunks):
            print(f"[index_factbook] embedded {i}/{len(chunks)}  elapsed={time.time()-t0:.1f}s", flush=True)

    E = np.vstack(embs)
    # normalize for dot product cosine
    denom = np.linalg.norm(E, axis=1, keepdims=True) + 1e-9
    E = E / denom

    np.save(EMB_NPY, E)

    with CHUNKS.open("w", encoding="utf-8") as f:
        for c in chunks:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")

    MANIFEST.write_text(json.dumps({
        "host": HOST,
        "embed_model": EMB_MODEL,
        "chunks": len(chunks),
        "emb_dim": int(E.shape[1]),
        "factbook_path": str(FACTBOOK),
        "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }, indent=2), encoding="utf-8")

    print("[index_factbook] DONE:", EMB_NPY, CHUNKS, MANIFEST)

if __name__ == "__main__":
    main()
