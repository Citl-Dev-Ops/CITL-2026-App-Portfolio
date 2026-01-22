#!/usr/bin/env python3
"""
Builds a semantic search index over factbook.txt using Ollama embeddings.

Outputs:
  index/factbook.emb.npy      - numpy array of shape (N, D)
  index/factbook.chunks.jsonl - one JSON per line: {"id": int, "text": str}
"""

import os
import json
import pathlib
from typing import List

import numpy as np
import requests
from tqdm import tqdm

ROOT = Path(__file__).resolve().parent

FACTBOOK = ROOT / "factbook.txt"
EMB_JSON = ROOT / "factbook_embeddings.json"
# ---------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------

# Ollama endpoint & embedding model
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
EMB_URL = f"{OLLAMA_HOST}/api/embeddings"
EMB_MODEL = os.environ.get("FACTBOOK_EMBED", "nomic-embed-text")

# Paths (all relative to this script's folder)
ROOT = pathlib.Path(__file__).resolve().parent
FACTBOOK_TXT = ROOT / "factbook.txt"
INDEX_DIR = ROOT / "index"
EMB_PATH = INDEX_DIR / "factbook.emb.npy"
CH_PATH = INDEX_DIR / "factbook.chunks.jsonl"


# ---------------------------------------------------------------------
# Ollama embedding helper (robust to different JSON shapes)
# ---------------------------------------------------------------------

def ollama_embed(text: str) -> np.ndarray:
    """
    Call Ollama /api/embeddings and return a **normalized** float32 vector.

    Handles responses shaped like:
      {"embedding": [...]}
      {"embeddings": [[...]]}
      [{"embedding": [...]}]
      [{"embeddings": [[...]]}]
    """
    payload = {
        "model": EMB_MODEL,
        "input": text,
    }
    r = requests.post(EMB_URL, json=payload, timeout=120)
    r.raise_for_status()
    data = r.json()

    vec = None

    # Case 1: dict
    if isinstance(data, dict):
        if "embedding" in data:
            vec = data["embedding"]
        elif "embeddings" in data:
            first = data["embeddings"][0]
            if isinstance(first, dict) and "embedding" in first:
                vec = first["embedding"]
            else:
                vec = first

    # Case 2: list
    elif isinstance(data, list) and data:
        first = data[0]
        if isinstance(first, dict):
            if "embedding" in first:
                vec = first["embedding"]
            elif "embeddings" in first:
                inner = first["embeddings"][0]
                if isinstance(inner, dict) and "embedding" in inner:
                    vec = inner["embedding"]
                else:
                    vec = inner
        else:
            vec = first

    if vec is None:
        raise RuntimeError(f"Could not find embedding in Ollama response: {data}")

    v = np.asarray(vec, dtype=np.float32)
    v /= (np.linalg.norm(v) + 1e-8)
    return v


# ---------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------

def make_chunks(text: str, max_chars: int = 1200, overlap: int = 200) -> List[str]:
    """
    Simple paragraph-aware chunker for the Factbook text.
    """
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks: List[str] = []
    current = ""

    for p in paragraphs:
        if not current:
            current = p
            continue

        # If we can append this paragraph without exceeding max_chars
        if len(current) + 2 + len(p) <= max_chars:
            current += "\n\n" + p
        else:
            chunks.append(current)
            # start new chunk with an overlap from the end of the previous
            tail = current[-overlap:]
            current = tail + "\n\n" + p

    if current:
        chunks.append(current)

    return chunks


# ---------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------

def main() -> None:
    if not FACTBOOK_TXT.exists():
        raise SystemExit(
            f"ERROR: {FACTBOOK_TXT} not found.\n"
            f"Make sure 'factbook.txt' is in this folder:\n  {ROOT}"
        )

    INDEX_DIR.mkdir(exist_ok=True)

    print(f"Reading Factbook from: {FACTBOOK_TXT}")
    raw_text = FACTBOOK_TXT.read_text(encoding="utf-8", errors="ignore")

    chunks = make_chunks(raw_text)
    print(f"Total chunks to embed: {len(chunks)}", flush=True)

    embeddings: List[np.ndarray] = []
    with tqdm(total=len(chunks), desc="Embedding") as bar:
        for c in chunks:
            v = ollama_embed(c)
            embeddings.append(v)
            bar.update(1)

    emb_arr = np.stack(embeddings, axis=0)
    # row-normalize again, just to be safe
    emb_arr /= (np.linalg.norm(emb_arr, axis=1, keepdims=True) + 1e-8)

    np.save(EMB_PATH, emb_arr)

    with CH_PATH.open("w", encoding="utf-8") as f:
        for i, c in enumerate(chunks):
            f.write(json.dumps({"id": i, "text": c}, ensure_ascii=False) + "\n")

    print()
    print(f"Saved embeddings -> {EMB_PATH}")
    print(f"Saved chunks     -> {CH_PATH}")


if __name__ == "__main__":
    main()