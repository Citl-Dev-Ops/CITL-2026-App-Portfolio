$dest = "C:\00 HENOSIS CODING PROJECTS\CITL PROJECTS\CITL - Desktop LLM EZ Install Kits\factbook-assistant\query_factbook.py"

$code = @'
#!/usr/bin/env python3
from __future__ import annotations

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
import json
import argparse
from pathlib import Path
from typing import List, Tuple, Optional, Dict, Any

import numpy as np
import requests


# ---------------------------------------------------------------------
# Paths (anchored to THIS file; safe when launched from other folders)
# ---------------------------------------------------------------------

ROOT = Path(__file__).resolve().parent
INDEX_DIR = ROOT / "index"

# Preferred index format (fast + small)
EMB_PATH = INDEX_DIR / "factbook.emb.npy"
CH_PATH  = INDEX_DIR / "factbook.chunks.jsonl"

# Raw text (regex mode needs this)
TXT_PATH = ROOT / "factbook.txt"

# Legacy (older) format fallback (large JSON)
LEGACY_JSON = ROOT / "factbook_embeddings.json"


# ---------------------------------------------------------------------
# Ollama config
# ---------------------------------------------------------------------

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")

# Generation + embeddings endpoints (Ollama has used both over time)
GEN_URL        = f"{OLLAMA_HOST}/api/generate"
EMB_URL_NEW    = f"{OLLAMA_HOST}/api/embed"
EMB_URL_OLD    = f"{OLLAMA_HOST}/api/embeddings"

LLM_MODEL = os.environ.get("FACTBOOK_MODEL", "mistral:7b-instruct")
EMB_MODEL = os.environ.get("FACTBOOK_EMBED", "nomic-embed-text")


# ---------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------

def load_index() -> Tuple[np.ndarray, List[dict]]:
    """
    Load the precomputed embeddings and chunk metadata.

    Prefers:
      index/factbook.emb.npy + index/factbook.chunks.jsonl

    Falls back to:
      factbook_embeddings.json (legacy)
    """
    # Preferred: .npy + .jsonl
    if EMB_PATH.exists() and CH_PATH.exists():
        emb = np.load(EMB_PATH).astype(np.float32, copy=False)

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

        if emb.ndim != 2 or emb.shape[0] != len(chunks):
            raise SystemExit(
                "ERROR: index files look inconsistent.\n"
                f"  {EMB_PATH} has shape {emb.shape}\n"
                f"  {CH_PATH} has {len(chunks)} chunks\n"
                "Re-run build_factbook_index.py to rebuild the index."
            )

        return emb, chunks

    # Fallback: legacy JSON
    if LEGACY_JSON.exists():
        d = json.loads(LEGACY_JSON.read_text(encoding="utf-8"))
        emb = np.asarray(d.get("embeddings", []), dtype=np.float32)
        chunks = d.get("chunks", [])
        if emb.ndim != 2 or not chunks:
            raise SystemExit(
                "ERROR: legacy factbook_embeddings.json exists but is not usable.\n"
                "Re-run build_factbook_index.py to rebuild the index."
            )
        return emb, chunks

    raise SystemExit(
        "ERROR: Factbook index not found.\n"
        "Expected one of:\n"
        f"  {EMB_PATH}\n"
        f"  {CH_PATH}\n"
        f"  {LEGACY_JSON}\n"
        "Run build_factbook_index.py first."
    )


# ---------------------------------------------------------------------
# Embedding helper for queries (handles Ollama response variants)
# ---------------------------------------------------------------------

def _extract_embedding(payload: Any) -> Optional[List[float]]:
    """
    Accepts multiple Ollama embedding response shapes and extracts a vector.
    """
    # Dict forms
    if isinstance(payload, dict):
        if isinstance(payload.get("embedding"), list):
            return payload["embedding"]
        if isinstance(payload.get("embeddings"), list) and payload["embeddings"]:
            first = payload["embeddings"][0]
            if isinstance(first, dict) and isinstance(first.get("embedding"), list):
                return first["embedding"]
            if isinstance(first, list):
                return first
        return None

    # List forms
    if isinstance(payload, list) and payload:
        first = payload[0]
        if isinstance(first, dict) and isinstance(first.get("embedding"), list):
            return first["embedding"]
        if isinstance(first, list):
            return first

    return None


def embed_query(text: str) -> np.ndarray:
    """
    Call Ollama to embed query text and return a normalized float32 vector.
    Tries /api/embed first, then /api/embeddings as fallback.
    """
    req = {"model": EMB_MODEL, "input": text}

    # Try new endpoint
    for url in (EMB_URL_NEW, EMB_URL_OLD):
        try:
            r = requests.post(url, json=req, timeout=120)
            r.raise_for_status()
            data = r.json()
            vec = _extract_embedding(data)
            if vec is not None:
                v = np.asarray(vec, dtype=np.float32)
                v /= (np.linalg.norm(v) + 1e-8)
                return v
        except Exception:
            continue

    raise RuntimeError("Could not get a usable embedding from Ollama. Is Ollama running and is the embedding model pulled?")


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

    out: List[str] = []
    for i in idx:
        c = chunks[int(i)]
        # support both {"text":...} and {"i":..., "text":...}
        out.append(c.get("text", ""))
    return out


# ---------------------------------------------------------------------
# LLM call with context
# ---------------------------------------------------------------------

def gen_with_context(question: str, ctx: str) -> str:
    """
    Ask the LLM to answer using ONLY the provided Factbook context.
    """
    system_prompt = (
        "You are CITL Assistant, a college learning and accessibility coach.\n"
        "You answer ONLY with facts that appear in the CIA World Factbook context provided.\n"
        "If the answer is not clearly present in the context, say you do not know instead of guessing.\n"
        "Keep answers concise and easy to read for community college students.\n"
        "Use short paragraphs or bullet points.\n"
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
            "Place the Factbook text file as 'factbook.txt' in the factbook-assistant folder."
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

def shortcut(q: str) -> Optional[str]:
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

    # Normalize synonyms
    if raw_field in ("neighbor", "neighbors", "neighbour", "neighbours"):
        field = "neighbors"
    elif raw_field in ("language", "languages"):
        field = "languages"
    elif raw_field in ("religion", "religions"):
        field = "religion"
    else:
        field = raw_field

    # NOTE: These patterns depend on your factbook.txt formatting.
    # They search within a block that starts at ^CountryName.
    pats: Dict[str, str] = {
        "capital":          rf"(?mis)^{country_esc}\b.*?(?:Capital[^:\n]*:\s*)([^\n]+)",
        "population":       rf"(?mis)^{country_esc}\b.*?(?:Population[^:\n]*:\s*)([^\n]+)",
        "gdp":              rf"(?mis)^{country_esc}\b.*?GDP.*?(?:\n.*){{0,6}}",
        "internet code":    rf"(?mis)^{country_esc}\b.*?Internet country code:\s*([^\n]+)",
        "currency":         rf"(?mis)^{country_esc}\b.*?Currency[^:\n]*:\s*([^\n]+)",
        "neighbors":        rf"(?mis)^{country_esc}\b.*?border countries:\s*([^\n]+)",
        "languages":        rf"(?mis)^{country_esc}\b.*?Languages?:\s*([^\n]+)",
        "religion":         rf"(?mis)^{country_esc}\b.*?Religions?:\s*([^\n]+)",
        "area":             rf"(?mis)^{country_esc}\b.*?Area:\s*([^\n]+)",
        "government":       rf"(?mis)^{country_esc}\b.*?Government type:\s*([^\n]+)",
        "location":         rf"(?mis)^{country_esc}\b.*?Location:\s*([^\n]+)",
        "life expectancy":  rf"(?mis)^{country_esc}\b.*?Life expectancy at birth:\s*([^\n]+)",
    }

    return pats.get(field)


# ---------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description="Query CIA World Factbook via local Ollama + RAG")
    ap.add_argument("query", help="Question or shortcut like 'capital:laos'")
    ap.add_argument("--regex", action="store_true", help="Treat query as a raw regex over factbook.txt")
    ap.add_argument("-k", "--topk", type=int, default=8, help="Number of chunks/snippets to retrieve (default: 8)")
    ap.add_argument("--maxctx", type=int, default=2400, help="Max characters of context sent to the LLM (default: 2400)")
    args = ap.parse_args()

    # 1) Raw regex mode
    if args.regex:
        snippets = regex_search(args.query, args.topk)
        ctx = "\n---\n".join(snippets)[: args.maxctx]
        print(gen_with_context(args.query, ctx))
        return

    # 2) Shortcut mode
    sc_pat = shortcut(args.query)
    if sc_pat:
        snippets = regex_search(sc_pat, args.topk)
        if snippets:
            ctx = "\n---\n".join(snippets)[: args.maxctx]
            print(gen_with_context(args.query, ctx))
            return

    # 3) Semantic RAG
    emb, chunks = load_index()
    qvec = embed_query(args.query)
    ctx_chunks = top_k(emb, chunks, qvec, args.topk)
    ctx = "\n---\n".join(ctx_chunks)[: args.maxctx]
    print(gen_with_context(args.query, ctx))


if __name__ == "__main__":
    main()
'@

[IO.File]::WriteAllText($dest, $code, [Text.UTF8Encoding]::new($false))
Write-Host "Wrote: $dest"