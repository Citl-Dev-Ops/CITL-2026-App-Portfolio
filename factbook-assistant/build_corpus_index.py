#!/usr/bin/env python3
import argparse, json, os
from pathlib import Path
import requests
import numpy as np

from citl_text_extract import extract_text as _extract_doc_text
from citl_text_extract import is_searchable_file as _is_searchable_file

# === CITL_PATCH_DEFAULT_SRC_OUT_V1 ==========================================
# If GUI calls build_corpus_index.py with no args, argparse exits with:
#   "the following arguments are required: --src, --out"
# This patch auto-injects sensible defaults into sys.argv before argparse runs.
import os as _citl_os
import sys as _citl_sys
from pathlib import Path as _Path

def _citl_choose_src_out():
    base = _Path(__file__).resolve().parent

    # candidate source dirs (pick first existing)
    src_candidates = [
        base,
        base / "library",
        base / "data" / "corpus",
        base / "data" / "docs",
        base / "data",
        base / "corpus",
    ]
    src = None
    for c in src_candidates:
        if c.exists() and c.is_dir():
            src = str(c)
            break
    if src is None:
        src = str(base)

    # candidate output file locations (pick first writable parent)
    out_candidates = [
        base / "factbook_embeddings.json",
        base / "data" / "corpus_embeddings.json",
        base / "data" / "embeddings" / "corpus_embeddings.json",
        base / "corpus_embeddings.json",
        base / "data" / "corpus_index.json",
        base / "corpus_index.json",
    ]
    out = None
    for c in out_candidates:
        try:
            c.parent.mkdir(parents=True, exist_ok=True)
            out = str(c)
            break
        except Exception:
            continue
    if out is None:
        out = str(base / "corpus_embeddings.json")

    return src, out

# Environment overrides (optional)
#   export CITL_CORPUS_SRC=/path/to/corpus
#   export CITL_CORPUS_OUT=/path/to/output.json
_src_default, _out_default = _citl_choose_src_out()
_src_default = _citl_os.environ.get("CITL_CORPUS_SRC", _src_default)
_out_default = _citl_os.environ.get("CITL_CORPUS_OUT", _out_default)

if "--src" not in _citl_sys.argv:
    _citl_sys.argv += ["--src", _src_default]
if "--out" not in _citl_sys.argv:
    _citl_sys.argv += ["--out", _out_default]
# === END CITL_PATCH_DEFAULT_SRC_OUT_V1 ======================================

def _expand_src_paths(src_arg: str) -> list[Path]:
    parts = [s.strip() for s in src_arg.replace(";", ",").split(",") if s.strip()]
    if not parts:
        return []
    return [Path(p).expanduser() for p in parts]

def _iter_source_files(src_paths: list[Path]) -> list[Path]:
    out: list[Path] = []
    seen = set()
    for src in src_paths:
        if src.is_file() and _is_searchable_file(src):
            rp = str(src.resolve())
            if rp not in seen:
                seen.add(rp)
                out.append(src)
            continue
        if not src.is_dir():
            continue
        for fp in sorted(src.rglob("*")):
            if not fp.is_file() or not _is_searchable_file(fp):
                continue
            rp = str(fp.resolve())
            if rp in seen:
                continue
            seen.add(rp)
            out.append(fp)
    return out

def chunk_text(text: str, n: int) -> list[str]:
    text = text.replace("\r\n", "\n")
    out = []
    i = 0
    L = len(text)
    while i < L:
        out.append(text[i:i+n])
        i += n
    return [c.strip() for c in out if c.strip()]

def embed(host: str, model: str, text: str) -> list[float]:
    # Try new /api/embed first (Ollama >=0.5), fall back to legacy /api/embeddings.
    tries = [
        (f"{host}/api/embed",       {"model": model, "input": text}),
        (f"{host}/api/embeddings",  {"model": model, "prompt": text}),
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
        j = r.json()
        # New API: {"embeddings": [[float, ...]]}
        if "embeddings" in j and j["embeddings"]:
            first = j["embeddings"][0]
            if isinstance(first, list) and first:
                return first
        # Legacy API: {"embedding": [float, ...]}
        if "embedding" in j and j["embedding"]:
            return j["embedding"]
        last_err = f"No embedding vector in response from {url}: {j}"
    raise RuntimeError(f"Embedding failed: {last_err}")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--src",
        required=True,
        help="File/dir or comma-separated sources (txt, md, pdf, csv, xls, xlsx, epub, gsheet/url).",
    )
    ap.add_argument("--out", required=True, help="Output JSON path")
    ap.add_argument("--chunk", type=int, default=1200, help="Chunk size (chars)")
    ap.add_argument("--host", default=os.environ.get("OLLAMA_HOST","http://127.0.0.1:11434"))
    ap.add_argument("--embed-model", default=os.environ.get("CITL_EMBED_MODEL","nomic-embed-text"))
    args = ap.parse_args()

    src_paths = _expand_src_paths(args.src)
    outp = Path(args.out)

    files = _iter_source_files(src_paths)
    if not files:
        raise SystemExit(f"No source .txt/.md files found for --src={args.src!r}")

    chunks: list[str] = []
    for fp in files:
        raw = _extract_doc_text(fp)
        if not raw:
            continue
        for c in chunk_text(raw, args.chunk):
            chunks.append(f"[{fp.name}]\n{c}")
    if not chunks:
        raise SystemExit("No chunks produced from source files.")

    embs = []
    for c in chunks:
        embs.append(embed(args.host, args.embed_model, c))

    dim = len(embs[0])
    mat = np.array(embs, dtype=np.float32)

    outp.write_text(json.dumps({
        "embed_model": args.embed_model,
        "dim": dim,
        "source_files": [str(p) for p in files],
        "chunks": chunks,
        "embeddings": mat.tolist(),
    }), encoding="utf-8")

    # Compatibility sidecar used by legacy loaders.
    if outp.name == "factbook_embeddings.json":
        sidecar = outp.with_name("factbook_chunks.json")
        sidecar.write_text(json.dumps(chunks, ensure_ascii=False), encoding="utf-8")

if __name__ == "__main__":
    main()
