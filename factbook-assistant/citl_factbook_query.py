from __future__ import annotations

import json
import os
import math
import re
import time
from pathlib import Path
from typing import Dict, List, Tuple, Optional

try:
    import numpy as np
except Exception:
    np = None
import requests

from citl_text_extract import extract_text as _extract_doc_text
from citl_text_extract import is_searchable_file as _is_searchable_file

HERE = Path(__file__).resolve().parent
# Canonical library location.  data/library_raw/ is where documents actually live.
# library/ is kept for backward compat (older copies may exist there).
LIB_DIR      = HERE / "library"
LIB_RAW_DIR  = HERE / "data" / "library_raw"
EMB_JSON = HERE / "factbook_embeddings.json"
CHUNK_JSON = HERE / "factbook_chunks.json"
FACTBOOK_TXT = HERE / "factbook.txt"

DEFAULT_EMBED_MODEL = os.environ.get("CITL_EMBED_MODEL", "nomic-embed-text").strip() or "nomic-embed-text"

STRICT_GROUNDING = str(os.environ.get("CITL_STRICT_GROUNDING", "1")).strip().lower() not in ("0", "false", "no", "off")
INSUFFICIENT_CONTEXT_MSG = "I do not have enough verified context to answer this safely."
_TAG_CACHE = {"host": "", "at": 0.0, "models": []}
_COUNTRY_SECTION_CACHE = {"mtime": 0.0, "sections": {}}
_INDEX_REBUILD_ATTEMPTED = False


def _require_numpy() -> None:
    if np is None:
        raise RuntimeError("numpy is required for embedding-based retrieval; install numpy or use deterministic country-locked queries.")

def _min_similarity_threshold() -> float:
    raw = str(os.environ.get("CITL_MIN_SIMILARITY", "0.18")).strip()
    try:
        return float(raw)
    except Exception:
        return 0.18

def _book_source_roots() -> List[Path]:
    # Always include both the canonical data/library_raw/ location AND the
    # legacy library/ folder so nothing is missed regardless of where files landed.
    roots: List[Path] = [LIB_RAW_DIR, LIB_DIR, HERE]
    extra = str(os.environ.get("CITL_EXTRA_BOOK_DIRS", "") or "").strip()
    if extra:
        parts = [p.strip() for p in re.split(r"[,:;]", extra) if p.strip()]
        for p in parts:
            roots.append(Path(p).expanduser())
    uniq: List[Path] = []
    seen = set()
    for r in roots:
        key = str(r)
        if key in seen:
            continue
        seen.add(key)
        if r.exists():
            uniq.append(r)
    return uniq

def _collect_text_files(roots: List[Path]) -> List[Path]:
    out: List[Path] = []
    seen = set()
    seen_names = set()
    raw_min = str(os.environ.get("CITL_MIN_BOOK_BYTES", "0")).strip()
    try:
        min_bytes = max(0, int(raw_min))
    except Exception:
        min_bytes = 0
    for root in roots:
        if root.is_file() and _is_searchable_file(root):
            try:
                if root.stat().st_size < min_bytes:
                    continue
            except Exception:
                continue
            rp = str(root.resolve())
            name_key = root.name.lower()
            if rp not in seen:
                if name_key in seen_names:
                    continue
                seen.add(rp)
                seen_names.add(name_key)
                out.append(root)
            continue
        if not root.is_dir():
            continue
        if root.resolve() == HERE.resolve():
            iterator = root.glob("*")
        else:
            iterator = root.rglob("*")
        for p in iterator:
            if not p.is_file() or not _is_searchable_file(p):
                continue
            low_name = p.name.lower()
            if low_name.startswith("warn-"):
                continue
            if any(part in {"__pycache__", ".git", ".venv", "build", "dist"} for part in p.parts):
                continue
            # Ignore package metadata or tiny helper text files.
            if any(part.endswith(".egg-info") for part in p.parts):
                continue
            if low_name.endswith("_all.txt"):
                continue
            try:
                if p.stat().st_size < min_bytes:
                    continue
            except Exception:
                continue
            rp = str(p.resolve())
            name_key = low_name
            if rp in seen:
                continue
            if name_key in seen_names:
                continue
            seen.add(rp)
            seen_names.add(name_key)
            out.append(p)
    out.sort(key=lambda p: (p.name.lower() != "factbook.txt", p.name.lower()))
    return out

def _index_source_files() -> List[Path]:
    return _collect_text_files(_book_source_roots())

def _installed_materials_summary() -> str:
    lines: List[str] = []
    lines.append("Installed local materials:")
    if FACTBOOK_TXT.exists():
        lines.append(f"- factbook.txt ({FACTBOOK_TXT.stat().st_size} bytes)")
    else:
        lines.append("- factbook.txt (missing)")

    if LIB_DIR.exists():
        docs = sorted([p for p in LIB_DIR.rglob("*") if p.is_file() and p.suffix.lower() in (".txt", ".md", ".pdf", ".docx")])
        lines.append(f"- library files: {len(docs)}")
        for p in docs[:20]:
            lines.append(f"  - {p.name}")
        if len(docs) > 20:
            lines.append(f"  - ... +{len(docs)-20} more")
    else:
        lines.append("- library directory missing")

    books = _index_source_files()
    lines.append(f"- indexed text sources discovered: {len(books)}")
    for p in books[:20]:
        try:
            sz = p.stat().st_size
        except Exception:
            sz = 0
        lines.append(f"  - {p.name} ({sz} bytes)")
    if len(books) > 20:
        lines.append(f"  - ... +{len(books)-20} more")

    for p in (EMB_JSON, CHUNK_JSON):
        lines.append(f"- {p.name}: {'present' if p.exists() else 'missing'}")
    return "\n".join(lines)

def _country_key(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (name or "").lower())

def _country_aliases(heading: str) -> List[str]:
    h = re.sub(r"\s+", " ", (heading or "").strip())
    if not h:
        return []
    out = [h]
    # Handle headings like "GAMBIA, THE".
    m = re.match(r"^(.*?),\s*THE$", h, re.IGNORECASE)
    if m:
        stem = m.group(1).strip()
        if stem:
            out.extend([stem, f"The {stem}"])
    return out

def _load_country_sections() -> Dict[str, Tuple[str, str]]:
    if not FACTBOOK_TXT.exists():
        return {}
    try:
        mtime = float(FACTBOOK_TXT.stat().st_mtime)
    except Exception:
        mtime = 0.0

    cached_mtime = float(_COUNTRY_SECTION_CACHE.get("mtime") or 0.0)
    cached_sections = _COUNTRY_SECTION_CACHE.get("sections") or {}
    if cached_sections and mtime == cached_mtime:
        return cached_sections

    data = FACTBOOK_TXT.read_text(encoding="utf-8", errors="ignore")
    starts: List[Tuple[int, str]] = []
    heading_re = re.compile(r"(?m)^\s*([A-Z][A-Z0-9 ,.'()/&-]{2,})\s*$")
    for m in heading_re.finditer(data):
        heading = re.sub(r"\s+", " ", (m.group(1) or "").strip())
        if not heading:
            continue
        # Gate: valid country sections contain INTRODUCTION + Background close to heading.
        probe = data[m.start():min(len(data), m.start() + 2200)]
        if not re.search(r"(?i)\bINTRODUCTION\b", probe):
            continue
        if not re.search(r"(?i)\bBackground\s*:", probe):
            continue
        starts.append((m.start(), heading))

    sections: Dict[str, Tuple[str, str]] = {}
    for i, (start, heading) in enumerate(starts):
        end = starts[i + 1][0] if i + 1 < len(starts) else len(data)
        section = data[start:end]
        for alias in _country_aliases(heading):
            k = _country_key(alias)
            if k and k not in sections:
                sections[k] = (heading, section)

    _COUNTRY_SECTION_CACHE["mtime"] = mtime
    _COUNTRY_SECTION_CACHE["sections"] = sections
    return sections

def _section_looks_valid(section: str) -> bool:
    t = (section or "").lower()
    if "background:" not in t:
        return False
    # Require at least one core demographic/government marker to avoid map snippets.
    return any(k in t for k in ("population:", "capital:", "people and society", "government"))

def _find_country_section_by_background(country: str) -> Optional[Tuple[str, str]]:
    if not FACTBOOK_TXT.exists():
        return None
    data = FACTBOOK_TXT.read_text(encoding="utf-8", errors="ignore")
    if not data:
        return None

    raw = re.sub(r"\s+", " ", (country or "").strip())
    if not raw:
        return None
    aliases = [raw]
    if raw.lower().startswith("the "):
        aliases.append(raw[4:].strip())
    else:
        aliases.append(f"The {raw}")
    aliases = [a for a in aliases if a]

    bg_marks = list(re.finditer(r"(?i)\bBackground:\s*", data))
    if not bg_marks:
        return None

    for i, bm in enumerate(bg_marks):
        sent_end = data.find(".", bm.end(), min(len(data), bm.end() + 500))
        if sent_end < 0:
            sent_end = min(len(data), bm.end() + 500)
        first_sentence = data[bm.end():sent_end]

        hit = False
        for a in aliases:
            # Strong gate: country name must act as a subject in first sentence.
            if re.search(rf"(?i)\b{re.escape(a)}\b\s*(?:,|is\b|was\b|has\b|had\b|became\b|remains\b)", first_sentence):
                hit = True
                break
        if not hit:
            continue

        start = max(0, bm.start() - 2800)
        intro = data.rfind("INTRODUCTION", max(0, bm.start() - 2800), bm.start())
        if intro >= 0:
            # Shift start near the INTRODUCTION header when available.
            nl = data.rfind("\n", 0, intro)
            start = (nl + 1) if nl >= 0 else intro
        end = bg_marks[i + 1].start() if i + 1 < len(bg_marks) else len(data)
        section = data[start:end]
        if _section_looks_valid(section):
            return raw.upper(), section
    return None

def _find_country_section(country: str) -> Optional[Tuple[str, str]]:
    raw = re.sub(r"\s+", " ", (country or "").strip())
    if not raw:
        return None

    sections = _load_country_sections()
    if sections:
        # Direct key hit.
        k = _country_key(raw)
        if k in sections and _section_looks_valid(sections[k][1]):
            return sections[k]

        # "the X" normalization.
        if raw.lower().startswith("the "):
            k2 = _country_key(raw[4:])
            if k2 in sections and _section_looks_valid(sections[k2][1]):
                return sections[k2]

        # Fuzzy heading fallback, but only if section passes validity gate.
        toks = [t for t in re.findall(r"[a-z0-9]+", raw.lower()) if t != "the"]
        if toks:
            for _, (heading, section) in sections.items():
                h = heading.lower()
                if all(t in h for t in toks) and _section_looks_valid(section):
                    return heading, section

    return _find_country_section_by_background(raw)

def _extract_field_from_country_section(field_key: str, section: str) -> Optional[str]:
    if not section:
        return None
    patterns = {
        "population": [r"(?is)\bPopulation:\s*([^\n]+)"],
        "capital": [r"(?is)\bCapital:\s*([^\n]+)"],
        "currency": [
            r"(?is)\b(?:National\s+)?Currency(?:[^:\n]*)?:\s*([^\n]+)",
            r"(?is)\bExchange rates:\s*([^\n]+?)\s+per\s+US\s+dollar",
        ],
        "internet code": [r"(?is)\bInternet country code:\s*([^\n]+)"],
    }
    pats = patterns.get(field_key)
    if not pats:
        return None
    value = ""
    for pat in pats:
        m = re.search(pat, section)
        if not m:
            continue
        value = re.sub(r"\s+", " ", (m.group(1) or "").strip())
        if value:
            break
    if not value:
        return None
    if field_key == "capital":
        m_name = re.search(r"(?i)\bname:\s*([^;]+?)(?:\s+geographic coordinates:|\s+time difference:|$)", value)
        if m_name:
            value = m_name.group(1).strip()
    if len(value) > 260:
        return None
    return value

def _extract_country_field_answer(question: str) -> Optional[str]:
    if not FACTBOOK_TXT.exists():
        return None

    q = (question or "").strip().rstrip("?")
    field_aliases = [
        ("population", "Population"),
        ("capital", "Capital"),
        ("currency", "Currency"),
        ("internet code", "Internet country code"),
    ]

    parsed = None
    for field_key, _ in field_aliases:
        m = re.search(
            rf"(?i)\b{re.escape(field_key)}\b(?:\s*:\s*|\s+(?:of|for|in)\s+)([A-Za-z][A-Za-z0-9 .,'()/-]+)$",
            q,
        )
        if m:
            parsed = (field_key, m.group(1).strip())
            break
        m2 = re.search(
            rf"(?i)\b{re.escape(field_key)}\b.*?\bof\s+([A-Za-z][A-Za-z0-9 .,'()/-]+)",
            q,
        )
        if m2:
            parsed = (field_key, m2.group(1).strip())
            break

    if not parsed:
        return None

    field_key, country = parsed
    found = _find_country_section(country)
    if not found:
        return None
    heading, section = found
    value = _extract_field_from_country_section(field_key, section)
    if not value:
        return None
    label = re.sub(r"\s+", " ", country).strip()
    if not label:
        label = heading.title()
    return f"{label}: {field_key}: {value}\nSource: factbook.txt (country-scoped parser)"

def _extract_regex_query(question: str) -> Optional[str]:
    q = (question or "").strip()
    m = re.match(r"(?is)^\s*(?:regex|re)\s*:\s*(.+)\s*$", q)
    if m:
        return m.group(1).strip()
    return None

def _snippet(text: str, start: int, end: int, pad: int = 160) -> str:
    lo = max(0, start - pad)
    hi = min(len(text), end + pad)
    return re.sub(r"\s+", " ", text[lo:hi]).strip()

def _regex_search_books(pattern: str, max_books: int = 8, max_hits_per_book: int = 2) -> str:
    try:
        rx = re.compile(pattern, re.IGNORECASE | re.MULTILINE)
    except re.error as e:
        return f"Invalid regex pattern: {e}"

    files = _index_source_files()
    if not files:
        return "No text sources found."

    lines: List[str] = [f"Regex results for /{pattern}/:"]
    shown_books = 0
    total_hits = 0
    for fp in files:
        data = _extract_doc_text(fp)
        if not data:
            continue
        hits = list(rx.finditer(data))
        if not hits:
            continue
        total_hits += len(hits)
        shown_books += 1
        lines.append(f"- {fp.name}: {len(hits)} match(es)")
        for h in hits[:max_hits_per_book]:
            lines.append(f"  > {_snippet(data, h.start(), h.end())}")
        if shown_books >= max_books:
            break
    if total_hits == 0:
        return f"No matches found for /{pattern}/ across {len(files)} source files."
    lines.append(f"Total matches: {total_hits}")
    return "\n".join(lines)

def _try_rcw_lookup(question: str) -> Optional[str]:
    m = re.search(r"(?i)\bRCW\s+([0-9A-Za-z]+\.[0-9A-Za-z.()-]+)", question or "")
    if not m:
        return None
    cite = m.group(1).strip()
    pat = rf"\bRCW\s+{re.escape(cite)}\b"
    res = _regex_search_books(pat, max_books=3, max_hits_per_book=2)
    if res.lower().startswith("no matches"):
        return None
    return res

def _try_entity_locked_answer(question: str) -> Optional[str]:
    try:
        from executors import try_answer_text
    except Exception:
        return None
    try:
        return try_answer_text(question, source_path=FACTBOOK_TXT, source_year=2023)
    except Exception:
        return None

def _keyword_search_hits(question: str, top_k: int = 8, source_filter: Optional[str] = None) -> List[Dict]:
    """Return ranked JSONL records from all indexed books. Never returns raw text — callers synthesize."""
    try:
        from citl_auto_index import keyword_search, IDX_DIR
        return keyword_search(question, idx_dir=IDX_DIR, top_k=top_k, source_filter=source_filter) or []
    except Exception:
        return []


def _load_book_catalog() -> Dict:
    """Load the auto-index book catalog (domain, sections per book)."""
    try:
        from citl_auto_index import load_book_catalog, IDX_DIR
        return load_book_catalog(IDX_DIR)
    except Exception:
        return {}


def _catalog_summary_for_prompt(catalog: Dict) -> str:
    """Format catalog as a compact LLM context block listing each book and its domain."""
    if not catalog:
        return ""
    lines = ["Available library books (use these as sources):"]
    for name, info in catalog.items():
        domain = info.get("domain", "general")
        chunks = info.get("chunks", 0)
        sections = info.get("top_sections", [])[:5]
        sec_str = "; ".join(sections) if sections else "no section index"
        lines.append(f"  - {name} [{domain}, {chunks} passages] — sections include: {sec_str}")
    return "\n".join(lines)


def _auto_route_to_source(question: str, catalog: Dict) -> Optional[str]:
    """
    If the question strongly matches a single book's domain, return that book's
    source name so the search can be focused there first.
    Returns None to search all books.
    """
    if not catalog:
        return None
    q = question.lower()

    # Domain keyword sets for routing
    domain_signals: Dict[str, List[str]] = {
        "law / legal":        ["rcw","statute","law","legal","property law","estate law",
                               "landlord","tenant","contract","tort","plaintiff","defendant",
                               "court","judge","jurisdiction","washington law","us law"],
        "medicine / nursing": ["nursing","patient","medication","dosage","clinical","nurse",
                               "anatomy","diagnosis","treatment","hospital","symptom"],
        "geography / world":  ["country","capital of","population of","factbook","continent",
                               "geography","what country","which country","nation","territory"],
        "dictionary / reference": ["define ","definition of","what does","word for","synonym",
                                   "noun","verb","adjective"],
    }

    # Find best domain match
    best_domain, best_score = None, 0
    for domain, signals in domain_signals.items():
        score = sum(1 for s in signals if s in q)
        if score > best_score:
            best_score = score
            best_domain = domain

    if best_domain and best_score >= 1:
        # Find catalog book with this domain
        matches = [name for name, info in catalog.items()
                   if info.get("domain", "") == best_domain]
        if len(matches) == 1:
            return matches[0]

    return None


def _try_local_truth_answer(question: str) -> Optional[str]:
    """
    Handles ONLY deterministic / structured lookups that need no LLM synthesis:
      - corpus inventory queries
      - explicit regex: prefix queries
      - RCW statute lookups
      - entity-locked factbook field extraction
      - direct country-field regex extraction
    Returns None for everything else so answer_question() can route through LLM.
    """
    qlow = (question or "").lower()
    if any(k in qlow for k in ("installed material", "installed materials", "what materials", "corpus", "what sources", "what documents", "what books")):
        return _installed_materials_summary()

    rx = _extract_regex_query(question)
    if rx:
        return _regex_search_books(rx)

    rcw = _try_rcw_lookup(question)
    if rcw:
        return rcw

    locked = _try_entity_locked_answer(question)
    if locked:
        return locked

    ans = _extract_country_field_answer(question)
    if ans:
        return ans

    return None

def _extract_embedding_vector(data) -> Optional[List[float]]:
    if isinstance(data, dict):
        vec = data.get("embedding")
        if isinstance(vec, list) and vec:
            return vec
        embs = data.get("embeddings")
        if isinstance(embs, list) and embs:
            first = embs[0]
            if isinstance(first, dict):
                first = first.get("embedding")
            if isinstance(first, list) and first:
                return first
        d = data.get("data")
        if isinstance(d, list) and d:
            first = d[0]
            if isinstance(first, dict):
                vec = first.get("embedding")
                if isinstance(vec, list) and vec:
                    return vec
    elif isinstance(data, list) and data:
        first = data[0]
        if isinstance(first, dict):
            vec = first.get("embedding")
            if isinstance(vec, list) and vec:
                return vec
    return None

def _extract_generation_text(data) -> str:
    if isinstance(data, dict):
        val = data.get("response")
        if isinstance(val, str) and val.strip():
            return val.strip()
        msg = data.get("message")
        if isinstance(msg, dict):
            val = msg.get("content")
            if isinstance(val, str) and val.strip():
                return val.strip()
        choices = data.get("choices")
        if isinstance(choices, list) and choices:
            first = choices[0]
            if isinstance(first, dict):
                msg = first.get("message")
                if isinstance(msg, dict):
                    val = msg.get("content")
                    if isinstance(val, str) and val.strip():
                        return val.strip()
                val = first.get("text")
                if isinstance(val, str) and val.strip():
                    return val.strip()
    return ""

def _fetch_installed_models(host: str) -> List[str]:
    h = (host or "").rstrip("/")
    now = time.time()
    if _TAG_CACHE.get("host") == h and (now - float(_TAG_CACHE.get("at") or 0.0)) < 8.0:
        cached = _TAG_CACHE.get("models") or []
        return [str(x) for x in cached if str(x).strip()]

    names: List[str] = []
    endpoints = [f"{h}/api/tags", f"{h}/v1/models"]
    for url in endpoints:
        try:
            r = requests.get(url, timeout=8)
        except Exception:
            continue
        if r.status_code >= 400:
            continue
        try:
            data = r.json()
        except Exception:
            continue
        if isinstance(data, dict):
            rows = data.get("models")
            if isinstance(rows, list):
                for row in rows:
                    if isinstance(row, dict):
                        n = row.get("name") or row.get("model") or row.get("id")
                        if n:
                            names.append(str(n))
            rows = data.get("data")
            if isinstance(rows, list):
                for row in rows:
                    if isinstance(row, dict):
                        n = row.get("id") or row.get("name") or row.get("model")
                        if n:
                            names.append(str(n))
        if names:
            break

    uniq = sorted({n.strip() for n in names if n and n.strip()})
    _TAG_CACHE["host"] = h
    _TAG_CACHE["at"] = now
    _TAG_CACHE["models"] = uniq
    return uniq

def _resolve_model_name(host: str, requested: str) -> Tuple[str, Optional[str]]:
    req = (requested or "").strip()
    installed = _fetch_installed_models(host)
    if not installed:
        return req, None
    if req in installed:
        return req, None
    if req and ":" not in req and f"{req}:latest" in installed:
        return f"{req}:latest", f"[Model notice] Using installed '{req}:latest' (requested '{req}')."

    base = req.split(":", 1)[0].lower().strip()
    if base:
        base_matches = [m for m in installed if m.split(":", 1)[0].lower() == base]
        if base_matches:
            preferred = sorted(base_matches, key=lambda m: ("instruct" not in m.lower(), ":latest" not in m.lower(), m))[0]
            return preferred, f"[Model notice] Using installed '{preferred}' (requested '{req}')."

    for preferred in ("mistral:7b-instruct", "llama3.1:8b", "llama3.1:latest"):
        if preferred in installed:
            return preferred, f"[Model notice] Requested model '{req}' not installed; using '{preferred}'."

    fallback = installed[0]
    return fallback, f"[Model notice] Requested model '{req}' not installed; using '{fallback}'."

def _resolve_embed_model(host: str, requested: str) -> str:
    req = (requested or "").strip()
    installed = _fetch_installed_models(host)
    if not installed:
        return req
    if req in installed:
        return req
    if req and ":" not in req and f"{req}:latest" in installed:
        return f"{req}:latest"

    embeds = [m for m in installed if "embed" in m.lower()]
    for pref in ("nomic-embed-text", "nomic-embed-text:latest", "all-minilm"):
        if pref in installed:
            return pref
    if embeds:
        return embeds[0]
    return req

def _ollama_embed(text: str, host: str, model: str) -> np.ndarray:
    _require_numpy()
    h = host.rstrip("/")
    use_model = _resolve_embed_model(h, model)
    tries = [
        (f"{h}/api/embeddings", {"model": use_model, "prompt": text}),
        (f"{h}/api/embeddings", {"model": use_model, "input": text}),
        (f"{h}/api/embed", {"model": use_model, "input": text}),
        (f"{h}/v1/embeddings", {"model": use_model, "input": text}),
    ]
    errs: List[str] = []
    for url, payload in tries:
        try:
            r = requests.post(url, json=payload, timeout=60)
        except Exception as e:
            errs.append(f"{url}: {e}")
            continue
        if r.status_code >= 400:
            errs.append(f"{url}: HTTP {r.status_code} {r.text[:160]}")
            continue
        try:
            data = r.json()
        except Exception as e:
            errs.append(f"{url}: invalid JSON ({e})")
            continue
        vec = _extract_embedding_vector(data)
        if vec:
            return np.array(vec, dtype=np.float32)
        errs.append(f"{url}: no embedding vector in response")

    raise RuntimeError(
        "Unable to retrieve embeddings from local LLM host. "
        f"host={h} model={use_model}. Last errors: {' | '.join(errs[-3:])}"
    )

def _ollama_generate(prompt: str, host: str, model: str) -> str:
    h = host.rstrip("/")
    tries = [
        (f"{h}/api/generate", {"model": model, "prompt": prompt, "stream": False}),
        (f"{h}/api/chat", {"model": model, "messages": [{"role": "user", "content": prompt}], "stream": False}),
        (f"{h}/v1/chat/completions", {"model": model, "messages": [{"role": "user", "content": prompt}], "stream": False}),
    ]
    errs: List[str] = []
    for url, payload in tries:
        try:
            r = requests.post(url, json=payload, timeout=120)
        except Exception as e:
            errs.append(f"{url}: {e}")
            continue
        if r.status_code >= 400:
            errs.append(f"{url}: HTTP {r.status_code} {r.text[:160]}")
            continue
        try:
            data = r.json()
        except Exception as e:
            errs.append(f"{url}: invalid JSON ({e})")
            continue
        text = _extract_generation_text(data)
        if text:
            return text
        errs.append(f"{url}: no text content in response")

    raise RuntimeError(
        "Unable to generate answer from local LLM host. "
        f"host={h} model={model}. Last errors: {' | '.join(errs[-3:])}"
    )

def _iter_text_files(root: Path) -> List[Path]:
    out: List[Path] = []
    if root.is_file():
        return [root] if _is_searchable_file(root) else []
    if root.is_dir():
        for p in root.rglob("*"):
            if p.is_file() and _is_searchable_file(p):
                out.append(p)
    return out

def _chunk_text(text: str, chunk_chars: int = 900, overlap: int = 150) -> List[str]:
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return []
    chunks = []
    i = 0
    n = len(text)
    while i < n:
        j = min(n, i + chunk_chars)
        chunk = text[i:j].strip()
        if chunk:
            chunks.append(chunk)
        i = max(i + chunk_chars - overlap, i + 1)
    return chunks

def build_index(
    src: Optional[Path],
    host: str,
    embed_model: str = DEFAULT_EMBED_MODEL,
    files: Optional[List[Path]] = None,
) -> Tuple[np.ndarray, List[str]]:
    _require_numpy()
    use_files = files or []
    if not use_files:
        if src is None:
            raise RuntimeError("No index source files were provided.")
        use_files = _iter_text_files(src)
    if not use_files:
        raise RuntimeError("No text files found to index.")

    all_chunks: List[str] = []
    for fp in use_files:
        raw = _extract_doc_text(fp)
        if not raw:
            continue
        for c in _chunk_text(raw):
            all_chunks.append(f"[{fp.name}]\n{c}")

    if not all_chunks:
        raise RuntimeError("Index build produced 0 chunks (empty input).")

    # Embed
    embs = []
    for c in all_chunks:
        embs.append(_ollama_embed(c, host=host, model=embed_model))
    emb = np.vstack(embs)
    return emb, all_chunks

def save_index(emb: np.ndarray, chunks: List[str], source_files: Optional[List[Path]] = None) -> None:
    payload = {
        "embed_model": DEFAULT_EMBED_MODEL,
        "dim": int(emb.shape[1]) if emb.ndim == 2 and emb.shape else 0,
        "source_files": [str(p) for p in (source_files or [])],
        "chunks": chunks,
        "embeddings": emb.tolist(),
    }
    EMB_JSON.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    CHUNK_JSON.write_text(json.dumps(chunks, ensure_ascii=False), encoding="utf-8")

def load_index() -> Tuple[Optional[np.ndarray], Optional[List[str]]]:
    _require_numpy()
    if not EMB_JSON.exists():
        return None, None

    try:
        payload = json.loads(EMB_JSON.read_text(encoding="utf-8"))
    except Exception:
        return None, None

    emb_data = None
    payload_chunks = None
    if isinstance(payload, dict):
        emb_data = payload.get("embeddings")
        payload_chunks = payload.get("chunks")
    elif isinstance(payload, list):
        # Legacy format: plain embeddings list.
        emb_data = payload

    if not emb_data:
        return None, None

    try:
        emb = np.asarray(emb_data, dtype=np.float32)
    except Exception:
        return None, None

    chunks: Optional[List[str]] = None
    if CHUNK_JSON.exists():
        try:
            raw_chunks = json.loads(CHUNK_JSON.read_text(encoding="utf-8"))
            if isinstance(raw_chunks, list):
                chunks = [str(c) for c in raw_chunks]
        except Exception:
            chunks = None

    if chunks is None and isinstance(payload_chunks, list):
        chunks = [str(c) for c in payload_chunks]

    if emb.ndim != 2 or not chunks:
        return None, None
    if len(chunks) != emb.shape[0]:
        # If sidecar chunks are stale but payload chunks match, use payload chunks.
        if isinstance(payload_chunks, list) and len(payload_chunks) == emb.shape[0]:
            chunks = [str(c) for c in payload_chunks]
        else:
            return None, None
    return emb, chunks

def _chunk_sources(chunks: List[str]) -> set:
    out = set()
    for c in chunks:
        m = re.match(r"^\[(.*?)\]\s*\n", str(c or ""))
        if m:
            s = (m.group(1) or "").strip()
            if s:
                out.add(s)
    return out

def _index_needs_multi_source_rebuild(chunks: List[str]) -> bool:
    expected = {p.name for p in _index_source_files()}
    # If we only have one source available, no multi-book rebuild is needed.
    if len(expected) <= 1:
        return False
    have = _chunk_sources(chunks)
    if not have:
        return True
    overlap = expected.intersection(have)
    return len(overlap) < min(2, len(expected))

def ensure_index(host: str) -> Tuple[np.ndarray, List[str]]:
    _require_numpy()
    global _INDEX_REBUILD_ATTEMPTED
    emb, chunks = load_index()
    if emb is not None and chunks is not None:
        auto = str(os.environ.get("CITL_AUTO_MULTI_REBUILD", "1")).strip().lower() not in ("0", "false", "no", "off")
        if auto and not _INDEX_REBUILD_ATTEMPTED and _index_needs_multi_source_rebuild(chunks):
            _INDEX_REBUILD_ATTEMPTED = True
            try:
                files = _index_source_files()
                emb2, chunks2 = build_index(src=None, host=host, files=files)
                save_index(emb2, chunks2, source_files=files)
                return emb2, chunks2
            except Exception:
                # Keep existing index if rebuild fails.
                return emb, chunks
        return emb, chunks

    files = _index_source_files()
    if not files:
        # Fallback for older layouts.
        src = LIB_DIR if LIB_DIR.exists() else HERE
        files = _iter_text_files(src)
    emb, chunks = build_index(src=None, host=host, files=files)
    save_index(emb, chunks, source_files=files)
    return emb, chunks

def _extract_source_and_text(chunk: str) -> Tuple[str, str]:
    t = str(chunk or "").strip()
    m = re.match(r"^\[(.*?)\]\s*\n(.*)$", t, re.DOTALL)
    if m:
        src = (m.group(1) or "").strip() or "local-corpus"
        body = (m.group(2) or "").strip()
        return src, (body or t)
    return "local-corpus", t

def top_k_chunks(question: str, host: str, k: int = 6) -> List[Tuple[str, str, float]]:
    _require_numpy()
    emb, chunks = ensure_index(host=host)
    qv = _ollama_embed(question, host=host, model=DEFAULT_EMBED_MODEL)
    # cosine-ish normalization
    embn = emb / (np.linalg.norm(emb, axis=1, keepdims=True) + 1e-8)
    qvn  = qv  / (np.linalg.norm(qv) + 1e-8)
    sims = embn @ qvn
    idx = np.argsort(-sims)[:k]
    out: List[Tuple[str, str, float]] = []
    for i in idx:
        chunk = chunks[int(i)]
        src, text = _extract_source_and_text(chunk)
        out.append((src, text, float(sims[int(i)])))
    return out

def answer_question(
    question: str,
    model: str,
    ollama_host: str,
    topk: int = 6,
    maxctx: int = 6000,
    source_filter: Optional[str] = None,
) -> str:
    # ── Pass 1: deterministic structured answers (no LLM needed) ──────────────
    local = _try_local_truth_answer(question)
    if local:
        return local

    # ── Pass 2: auto-route to most relevant book if no explicit filter ─────────
    catalog = _load_book_catalog()
    effective_filter = source_filter
    if not effective_filter:
        auto_routed = _auto_route_to_source(question, catalog)
        if auto_routed:
            effective_filter = auto_routed

    # ── Pass 3: gather context from indexed books ──────────────────────────────
    # Keyword search runs without Ollama — always attempt it first.
    kw_hits = _keyword_search_hits(question, top_k=topk, source_filter=effective_filter)
    # If filter gave no results, fall back to all books
    if not kw_hits and effective_filter and effective_filter != source_filter:
        kw_hits = _keyword_search_hits(question, top_k=topk)

    # Semantic embedding search — requires Ollama embed model (optional).
    emb_ranked: List[Tuple[str, str, float]] = []
    try:
        emb_ranked = top_k_chunks(question, host=ollama_host, k=topk)
        # Apply source filter to embedding results too
        if effective_filter and emb_ranked:
            sf = effective_filter.lower()
            filtered = [(src, txt, sc) for src, txt, sc in emb_ranked if sf in src.lower()]
            if filtered:
                emb_ranked = filtered
    except Exception:
        pass  # embeddings unavailable — keyword hits carry the load

    # ── Pass 4: build unified ranked context ──────────────────────────────────
    source_map: Dict[str, str] = {}
    parts: List[str] = []
    seen_texts: set = set()
    n = 0

    # Keyword hits first (title-boosted relevance, no Ollama dependency)
    for rec in kw_hits:
        src  = rec.get("source", "corpus")
        title = rec.get("title", "")
        text  = (rec.get("text") or rec.get("content") or "").strip()
        if not text:
            continue
        key = text[:120]
        if key in seen_texts:
            continue
        seen_texts.add(key)
        n += 1
        sid = f"S{n}"
        source_map[sid] = f"{src}" + (f" — {title}" if title else "")
        parts.append(f"[{sid}] source={src}\n{title}\n{text}" if title else f"[{sid}] source={src}\n{text}")

    # Embedding hits (higher semantic precision when available)
    for src, text, score in emb_ranked:
        if not text:
            continue
        key = text[:120]
        if key in seen_texts:
            continue
        seen_texts.add(key)
        n += 1
        sid = f"S{n}"
        source_map[sid] = src
        parts.append(f"[{sid}] source={src} relevance={score:.3f}\n{text}")

    if not parts:
        return INSUFFICIENT_CONTEXT_MSG

    ctx = "\n\n---\n\n".join(parts)[:maxctx]

    # ── Pass 5: LLM synthesis ─────────────────────────────────────────────────
    catalog_block = _catalog_summary_for_prompt(catalog)
    source_note = f"Focused search: {effective_filter}\n" if effective_filter else ""

    prompt = (
        "You are CITL Assistant — a professional academic study and research assistant.\n"
        "You help students and researchers understand course material from their own library.\n"
        "Answer the question thoroughly using ONLY the provided source context below.\n"
        "Do NOT use outside knowledge. If the context is insufficient, say so clearly.\n"
        "Cite your sources with [S#] inline. Be thorough, clear, and academically precise.\n"
        "When the question is about law, legal procedures, or statutes, look for content from "
        "the law/legal book and cite specific sections, chapters, or rules found in the text.\n\n"
        + (f"{catalog_block}\n\n" if catalog_block else "")
        + source_note
        + f"CONTEXT:\n{ctx}\n\n"
        f"QUESTION:\n{question}\n\n"
        "ANSWER:\n"
    )
    use_model, model_notice = _resolve_model_name(ollama_host, model)
    try:
        answer = _ollama_generate(prompt, host=ollama_host, model=use_model).strip()
    except Exception as gen_err:
        # Ollama unavailable — return the best keyword context with a note.
        header = (
            f"[LLM offline — showing retrieved source passages]\n"
            f"Model: {use_model}  Error: {gen_err}\n\n"
        )
        if model_notice:
            header = model_notice + "\n" + header
        return header + "\n\n---\n\n".join(parts[:4])

    if not answer:
        return INSUFFICIENT_CONTEXT_MSG

    if "INSUFFICIENT_VERIFIED_CONTEXT" in answer.upper():
        # Fall back to keyword hit summary rather than dead-end message
        if kw_hits:
            fallback = "[Context available but model flagged as insufficient — top passages:]\n\n"
            fallback += "\n\n---\n\n".join(parts[:3])
            if model_notice:
                fallback = model_notice + "\n" + fallback
            return fallback
        return INSUFFICIENT_CONTEXT_MSG

    cited = sorted({f"S{m}" for m in re.findall(r"\[S(\d+)\]", answer)})
    cited = [sid for sid in cited if sid in source_map]
    if STRICT_GROUNDING and not cited:
        cited = [sid for sid in list(source_map)[:2]]
        prefix = "[Grounding notice] Model did not emit inline citations; top sources attached.\n"
        answer = prefix + answer.strip()

    if cited and "Sources:" not in answer:
        answer = answer.rstrip() + "\n\nSources:\n" + "\n".join(
            f"- [{sid}] {source_map[sid]}" for sid in cited
        )
    if model_notice:
        answer = model_notice + "\n" + answer
    return answer
