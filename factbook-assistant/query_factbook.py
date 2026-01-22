#!/usr/bin/env python3
"""
Query the CIA World Factbook using a local Ollama model with RAG.

Supports:
  - Semantic RAG over prebuilt index (default)
  - Shortcut queries like:  capital:laos, population:japan, gdp:france
  - Raw regex over factbook.txt via --regex

Requires that build_factbook_index.py has already been run.
"""

import os
import re
import sys
import json
import argparse
import pathlib
from typing import List, Tuple

import numpy as np
import requests
# Always anchor paths to this file's folder, not the shell CWD
ROOT = Path(__file__).resolve().parent

DATA = ROOT / "factbook_embeddings.json"
FACTBOOK = ROOT / "factbook.txt"

LLM = "mistral:7b-instruct"
GEN_URL = "http://localhost:11434/api/generate"
EMB_URL = "http://localhost:11434/api/embed"
EMBED_MODEL = "nomic-embed-text"
# ---------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
GEN_URL = f"{OLLAMA_HOST}/api/generate"
EMB_URL = f"{OLLAMA_HOST}/api/embeddings"

LLM_MODEL = os.environ.get("FACTBOOK_MODEL", "mistral:7b-instruct")
EMB_MODEL = os.environ.get("FACTBOOK_EMBED", "nomic-embed-text")

ROOT = pathlib.Path(__file__).resolve().parent
INDEX_DIR = ROOT / "index"
EMB_PATH = INDEX_DIR / "factbook.emb.npy"
CH_PATH = INDEX_DIR / "factbook.chunks.jsonl"
TXT_PATH = ROOT / "factbook.txt"


# ---------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------

def load_index() -> Tuple[np.ndarray, List[dict]]:
    """
    Load the precomputed embeddings and chunk metadata.
    """
    if not EMB_PATH.exists() or not CH_PATH.exists():
        raise SystemExit(
            "ERROR: index files not found.\n"
            "Run build_factbook_index.py first to create:\n"
            f"  {EMB_PATH}\n"
            f"  {CH_PATH}\n"
        )

    emb = np.load(EMB_PATH)

    chunks: List[dict] = []
    with CH_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                chunks.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    return emb, chunks


# ---------------------------------------------------------------------
# Embedding helper for queries
# ---------------------------------------------------------------------

def embed_query(text: str) -> np.ndarray:
    """
    Call Ollama /api/embeddings for the query text and return a normalized vector.
    """
    payload = {
        "model": EMB_MODEL,
        "input": text,
    }
    r = requests.post(EMB_URL, json=payload, timeout=120)
    r.raise_for_status()
    data = r.json()

    vec = None

    if isinstance(data, dict):
        if "embedding" in data:
            vec = data["embedding"]
        elif "embeddings" in data:
            first = data["embeddings"][0]
            if isinstance(first, dict) and "embedding" in first:
                vec = first["embedding"]
            else:
                vec = first
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
# Retrieval
# ---------------------------------------------------------------------

def top_k(emb: np.ndarray, chunks: List[dict], qvec: np.ndarray, k: int) -> List[str]:
    """
    Return the top-k chunk texts most similar to qvec (cosine via dot-product).
    """
    if emb.ndim != 2:
        raise ValueError(f"Expected 2D embeddings array, got shape {emb.shape}")

    if emb.shape[0] == 0:
        return []

    sims = emb @ qvec  # (N,)

    k = max(1, min(k, sims.shape[0]))
    idx = np.argpartition(-sims, k - 1)[:k]
    idx = idx[np.argsort(-sims[idx])]

    return [chunks[int(i)]["text"] for i in idx]


# ---------------------------------------------------------------------
# LLM call with context
# ---------------------------------------------------------------------

def gen_with_context(question: str, ctx: str) -> str:
    """
    Ask the LLM to answer using ONLY the provided Factbook context.
    """
    system_prompt = (
        "You are CITL Assistant, a college learning and accessibility coach.\n"
        "You answer ONLY with facts that appear in the CIA World Factbook context "
        "provided below.\n"
        "If the answer is not clearly present in the context, say you do not know "
        "instead of guessing.\n"
        "Keep answers concise and easy to read for community college students. Use "
        "short paragraphs or bullet points.\n"
    )

    payload = {
        "model": LLM_MODEL,
        "system": system_prompt,
        "prompt": f"Context:\n{ctx}\n\nQuestion: {question}\nAnswer:",
        "stream": False,
        "options": {"temperature": 0.2},
    }

    r = requests.post(GEN_URL, json=payload, timeout=600)
    r.raise_for_status()
    data = r.json()
    return str(data.get("response", "")).strip()


# ---------------------------------------------------------------------
# Regex search over raw text
# ---------------------------------------------------------------------

def regex_search(pat: str, maxhits: int = 8) -> List[str]:
    """
    Search factbook.txt directly with a regex and return surrounding snippets.
    """
    if not TXT_PATH.exists():
        raise SystemExit(
            f"ERROR: {TXT_PATH} not found.\n"
            "Place the Factbook text file as 'factbook.txt' in this folder."
        )

    flags = re.IGNORECASE | re.MULTILINE | re.DOTALL
    data = TXT_PATH.read_text(encoding="utf-8", errors="ignore")
    out: List[str] = []

    for m in re.finditer(pat, data, flags):
        lo = max(0, m.start() - 400)
        hi = min(len(data), m.end() + 400)
        out.append(data[lo:hi])
        if len(out) >= maxhits:
            break

    return out


# ---------------------------------------------------------------------
# Shortcut parsing (capital:laos etc.)
# ---------------------------------------------------------------------

# Fixing the `shortcut` function definition
def shortcut(q: str):
    """
    Supported forms (case-insensitive), examples:

      capital:laos
      population:japan
      gdp:france
      internet code: united states
      currency:canada
      neighbors:laos
      languages:thailand
      religion:japan
      area:germany
      government:italy
      location:peru
      life expectancy:mexico
    """
    m = re.match(
        r"(?i)\s*("
        r"capital|population|gdp|internet code|currency|"
        r"neighbors?|neighbours?|languages?|language|"
        r"religion|religions|area|government|location|life expectancy"
        r")\s*:\s*(.+)$",
        q.strip(),
    )
    if not m:
        return None

    raw_field = m.group(1).lower()
    country = m.group(2).strip()
    country_esc = re.escape(country)

    # Normalize synonyms to canonical field keys
    if raw_field in ("neighbor", "neighbors", "neighbour", "neighbours"):
        field = "neighbors"
    elif raw_field in ("language", "languages"):
        field = "languages"
    elif raw_field in ("religion", "religions"):
        field = "religion"
    else:
        field = raw_field

    # Regex patterns are tuned to CIA Factbook style headings/labels.
    # They work within a single country's block that starts at ^CountryName.
    pats = {
        # already-existing ones
        "capital":       rf"(?mis)^{country_esc}\b.*?(?:Capital[^:\n]*:\s*)([^\n]+)",
        "population":    rf"(?mis)^{country_esc}\b.*?(?:Population[^:\n]*:\s*)([^\n]+)",
        "gdp":           rf"(?mis)^{country_esc}\b.*?GDP.*?(?:\n.*){{0,3}}",
        "internet code": rf"(?mis)^{country_esc}\b.*?Internet country code:\s*([^\n]+)",
        "currency":      rf"(?mis)^{country_esc}\b.*?Currency[^:\n]*:\s*([^\n]+)",

        # new shortcuts
        # e.g. under "Land boundaries:" -> "border countries:"
        "neighbors":     rf"(?mis)^{country_esc}\b.*?border countries:\s*([^\n]+)",

        # e.g. "Languages: Lao (official) ..."
        "languages":     rf"(?mis)^{country_esc}\b.*?Languages?:\s*([^\n]+)",

        # e.g. "Religions: Buddhist 64.7%, Christian 1.7%, none 31.4%..."
        "religion":      rf"(?mis)^{country_esc}\b.*?Religions?:\s*([^\n]+)",

        # e.g. "Area: total: 236,800 sq km; land: ...; water: ..."
        "area":          rf"(?mis)^{country_esc}\b.*?Area:\s*([^\n]+)",

        # e.g. "Government type: parliamentary constitutional monarchy"
        "government":    rf"(?mis)^{country_esc}\b.*?Government type:\s*([^\n]+)",

        # e.g. "Location: Southeastern Asia, bordering the Andaman Sea..."
        "location":      rf"(?mis)^{country_esc}\b.*?Location:\s*([^\n]+)",

        # e.g. "Life expectancy at birth: total population: 75.6 years ..."
        "life expectancy": rf"(?mis)^{country_esc}\b.*?Life expectancy at birth:\s*([^\n]+)",
    }

    if field not in pats:
        # Should not happen given the regex above, but keep it safe.
        return None

    return pats[field]

# ---------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(
        description="Query CIA World Factbook via local Ollama + RAG"
    )
    ap.add_argument(
        "query",
        help="Question or shortcut like 'capital:laos'",
    )
    ap.add_argument(
        "--regex",
        action="store_true",
        help="Treat query as a raw regex over factbook.txt",
    )
    ap.add_argument(
        "-k",
        "--topk",
        type=int,
        default=8,
        help="Number of chunks/snippets to retrieve (default: 8)",
    )
    ap.add_argument(
        "--maxctx",
        type=int,
        default=2400,
        help="Max characters of context to send to the LLM (default: 2400)",
    )
    args = ap.parse_args()

    # 1) Raw regex mode
    if args.regex:
        snippets = regex_search(args.query, args.topk)
        ctx = "\n---\n".join(snippets)[: args.maxctx]
        print(gen_with_context(args.query, ctx))
        return

    # 2) Shortcut mode (capital:laos etc.)
    sc_pat = shortcut(args.query)
    if sc_pat:
        snippets = regex_search(sc_pat, args.topk)
        if snippets:
            ctx = "\n---\n".join(snippets)[: args.maxctx]
            print(gen_with_context(args.query, ctx))
            return

    # 3) Semantic RAG over embeddings
    emb, chunks = load_index()
    qvec = embed_query(args.query)
    ctx_chunks = top_k(emb, chunks, qvec, args.topk)
    ctx = "\n---\n".join(ctx_chunks)[: args.maxctx]
    print(gen_with_context(args.query, ctx))


if __name__ == "__main__":
    main()