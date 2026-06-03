import json
import numpy as np
from pathlib import Path
import requests
from tqdm import tqdm

FACTBOOK = Path("factbook.txt")
EMB_JSON = Path("factbook_embeddings.json")

EMBED_MODEL = "nomic-embed-text"
EMBED_URL = "http://localhost:11434/api/embed"

def embed(text: str):
    r = requests.post(EMBED_URL, json={"model": EMBED_MODEL, "input": text})
    r.raise_for_status()
    out = r.json()
    vec = out.get("embedding") or out.get("embeddings", [{}])[0].get("embedding")
    return np.asarray(vec, dtype=np.float32)

def main():
    raw = FACTBOOK.read_text(encoding="utf-8", errors="ignore")

    # break Factbook into ~1500-char chunks
    chunks = []
    CHUNK = 1500
    for i in range(0, len(raw), CHUNK):
        text = raw[i:i+CHUNK]
        chunks.append({"i": len(chunks), "text": text})

    print(f"Embedding {len(chunks)} chunks…")

    all_vecs = []
    for c in tqdm(chunks):
        v = embed(c["text"])
        v = v / (np.linalg.norm(v) + 1e-8)
        all_vecs.append(v.tolist())

    result = {"embeddings": all_vecs, "chunks": chunks}

    EMB_JSON.write_text(json.dumps(result), encoding="utf-8")
    print(f"Wrote: {EMB_JSON}")

if __name__ == "__main__":
    main()
