"""
CITL Universal Auto-Indexer
----------------------------
Builds dense JSONL keyword indexes for ANY document in the library,
no Ollama required.  Runs on startup and after every "Add Books" action.

Output format per record:
    {"id": "stem::N", "source": "filename.txt", "title": "heading", "text": "..."}

This matches the schema already used by the factbook_index.jsonl.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path
from typing import Dict, List, Optional

try:
    from citl_text_extract import extract_text as _extract, is_searchable_file as _is_ok
    _HAS_EXTRACT = True
except Exception:
    _HAS_EXTRACT = False

HERE      = Path(__file__).resolve().parent
LIB_RAW   = HERE / "data" / "library_raw"
IDX_DIR   = HERE / "data" / "indexes"
MANIFEST  = IDX_DIR / "_auto_index_manifest.json"

CHUNK_CHARS  = 1_100    # target characters per JSONL record
OVERLAP      = 120      # overlap between adjacent chunks
MIN_CHUNK    = 80       # discard chunks shorter than this


# ── Text extraction ───────────────────────────────────────────────────────────

def _read_text(path: Path) -> str:
    if _HAS_EXTRACT:
        try:
            return _extract(path) or ""
        except Exception:
            pass
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""


# ── Heading detection (works for any document type) ──────────────────────────

# Patterns ordered from most-specific to least.  A line matches if it
# satisfies at least one pattern AND is not just a number or short noise.
_HEADING_RE = re.compile(r"""(?mx)^(
    (?:Chapter|CHAPTER|Unit|UNIT|Module|MODULE|Part|PART|Article|ARTICLE
      |Section|SECTION|Lesson|LESSON|Topic|TOPIC)\s+[\w.]+[^\n]{0,80}   |
    \#{1,3}\s+[^\n]{3,80}                   |   # markdown headings
    (?:RCW\s+\d[\d.A-Za-z-]+\s*[-—]).*     |   # RCW statute numbers
    \d+\.\d*\s+[A-Z][^\n]{4,70}            |   # 1.1 Numbered sections
    [IVX]+\.\s+[A-Z][^\n]{4,70}            |   # Roman numeral sections
    [A-Z][A-Z0-9 /,.'()\-]{5,72}               # ALL-CAPS headings (factbook style)
)$""")

_NOISE_RE = re.compile(r"^\s*[\d\s.,:;|–—-]{1,12}\s*$")


def _find_headings(text: str) -> List[tuple]:
    """Return list of (char_offset, heading_text) pairs."""
    found = []
    for m in _HEADING_RE.finditer(text):
        h = m.group(1).strip()
        if not h or _NOISE_RE.match(h):
            continue
        # Skip headings that appear to be mid-sentence (prev char isn't newline/start)
        prev = text[max(0, m.start()-1):m.start()]
        if prev and prev[-1] not in ("\n", "\r"):
            continue
        found.append((m.start(), h))
    return found


# ── Chunking ──────────────────────────────────────────────────────────────────

def _fixed_chunks(text: str, source: str, title: str, offset: int) -> List[Dict]:
    """Fixed-size overlap chunks for sections with no sub-structure."""
    text = text.strip()
    if not text:
        return []
    chunks = []
    i = 0
    part = 0
    while i < len(text):
        body = text[i:i + CHUNK_CHARS].strip()
        if len(body) >= MIN_CHUNK:
            sub_title = f"{title} (part {part+1})" if part > 0 else title
            cid = f"{source}::{offset}:{part}"
            chunks.append({"id": cid, "source": source,
                           "title": sub_title, "text": body})
            part += 1
        step = max(CHUNK_CHARS - OVERLAP, 1)
        i += step
    return chunks


def _split_document(text: str, source: str) -> List[Dict]:
    """
    Split any document into chunks using heading boundaries when available,
    falling back to fixed-size chunking.
    """
    headings = _find_headings(text)

    if len(headings) < 3:
        # Document has no useful heading structure — use fixed-size chunking.
        return _fixed_chunks(text, source, source, 0)

    chunks: List[Dict] = []
    for i, (start, title) in enumerate(headings):
        end = headings[i + 1][0] if i + 1 < len(headings) else len(text)
        body = text[start:end].strip()
        if not body or len(body) < MIN_CHUNK:
            continue
        # Recursively sub-chunk large sections
        if len(body) > CHUNK_CHARS * 4:
            sub = _fixed_chunks(body, source, title, i * 100)
            chunks.extend(sub)
        else:
            cid = f"{source}::{i}"
            chunks.append({"id": cid, "source": source,
                           "title": title, "text": body})
    return chunks


# ── Index file management ─────────────────────────────────────────────────────

def _index_path(src_path: Path) -> Path:
    """Canonical JSONL index path for a given source file."""
    IDX_DIR.mkdir(parents=True, exist_ok=True)
    stem = re.sub(r"[^\w.-]", "_", src_path.stem)
    return IDX_DIR / f"{stem}_index.jsonl"


def _file_fingerprint(path: Path) -> str:
    """mtime + size fingerprint — fast, no hashing."""
    try:
        st = path.stat()
        return f"{int(st.st_mtime)}:{st.st_size}"
    except Exception:
        return ""


def _load_manifest() -> Dict[str, str]:
    try:
        return json.loads(MANIFEST.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_manifest(m: Dict[str, str]) -> None:
    try:
        MANIFEST.write_text(json.dumps(m, indent=2), encoding="utf-8")
    except Exception:
        pass


def needs_reindex(src_path: Path) -> bool:
    """True if the source file has changed since last index build."""
    manifest = _load_manifest()
    key = str(src_path.resolve())
    fp  = _file_fingerprint(src_path)
    if not fp:
        return False
    idx = _index_path(src_path)
    if not idx.exists():
        return True
    # Existing index with very few records is considered stale regardless.
    try:
        lines = [l for l in idx.read_text(encoding="utf-8").splitlines() if l.strip()]
        if len(lines) < 5:
            return True
    except Exception:
        return True
    return manifest.get(key) != fp


# ── Public API ────────────────────────────────────────────────────────────────

def index_file(src_path: Path, force: bool = False) -> int:
    """
    Build (or rebuild) the JSONL index for a single source file.
    Returns the number of records written.
    """
    if not src_path.exists():
        return 0
    if not force and not needs_reindex(src_path):
        return 0

    text = _read_text(src_path)
    if not text.strip():
        return 0

    source = src_path.name
    chunks = _split_document(text, source)
    if not chunks:
        return 0

    idx_path = _index_path(src_path)
    IDX_DIR.mkdir(parents=True, exist_ok=True)
    with idx_path.open("w", encoding="utf-8") as fh:
        for rec in chunks:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

    # Update manifest
    manifest = _load_manifest()
    manifest[str(src_path.resolve())] = _file_fingerprint(src_path)
    _save_manifest(manifest)
    return len(chunks)


def auto_index_library(
    lib_dir: Optional[Path] = None,
    idx_dir: Optional[Path] = None,
    force: bool = False,
    progress_cb=None,   # optional callback(filename, record_count)
) -> Dict[str, int]:
    """
    Scan library_raw/ for documents that need (re)indexing and process them.
    Returns {filename: record_count} for every file that was indexed this run.
    """
    src_dir = lib_dir or LIB_RAW
    if idx_dir:
        global IDX_DIR, MANIFEST
        IDX_DIR  = idx_dir
        MANIFEST = IDX_DIR / "_auto_index_manifest.json"

    if not src_dir.is_dir():
        return {}

    results: Dict[str, int] = {}
    for ext in ("*.txt", "*.md", "*.pdf", "*.docx"):
        for p in sorted(src_dir.glob(ext)):
            if not p.is_file():
                continue
            if _HAS_EXTRACT:
                try:
                    from citl_text_extract import is_searchable_file
                    if not is_searchable_file(p):
                        continue
                except Exception:
                    pass
            n = index_file(p, force=force)
            if n:
                results[p.name] = n
                if progress_cb:
                    progress_cb(p.name, n)
    return results


# ── Book domain detection ─────────────────────────────────────────────────────

_DOMAIN_KEYWORDS: Dict[str, List[str]] = {
    "law / legal":        ["law","legal","statute","court","plaintiff","defendant","tort",
                           "contract","property","estate","landlord","tenant","rcw","title",
                           "chapter","section","amendment","constitution","jurisdiction"],
    "medicine / nursing": ["nursing","patient","medical","clinical","diagnosis","treatment",
                           "medication","dosage","anatomy","physiology","hospital","nurse",
                           "disease","symptom","pharmacology","health","care"],
    "geography / world":  ["country","capital","population","geography","continent","ocean",
                           "government","gdp","exports","imports","ethnic","religion",
                           "factbook","territory","border"],
    "dictionary / reference": ["definition","noun","verb","adjective","pronunciation",
                               "etymology","plural","informal","archaic","variant"],
    "science / technology": ["algorithm","data","computer","network","software","hardware",
                             "physics","chemistry","biology","engineering","research"],
}


def _detect_domain(titles: List[str], texts_sample: List[str]) -> str:
    """Return best-matching domain label for a book based on its section titles + text."""
    combined = " ".join(titles + texts_sample[:10]).lower()
    best_domain, best_score = "general", 0
    for domain, kws in _DOMAIN_KEYWORDS.items():
        score = sum(1 for kw in kws if kw in combined)
        if score > best_score:
            best_score = score
            best_domain = domain
    return best_domain


# ── Book catalog ──────────────────────────────────────────────────────────────

CATALOG_FILE = IDX_DIR / "_book_catalog.json"


def build_book_catalog(idx_dir: Optional[Path] = None) -> Dict[str, Dict]:
    """
    Scan all JSONL indexes and build a catalog of:
      { source_filename: {chunks, domain, top_sections, idx_file} }
    Saves result to _book_catalog.json and returns it.
    """
    search_dir = idx_dir or IDX_DIR
    catalog: Dict[str, Dict] = {}

    for idx_file in sorted(search_dir.glob("*.jsonl")):
        if idx_file.name.startswith("_"):
            continue
        source_counts: Dict[str, int] = {}
        all_titles: List[str] = []
        text_samples: List[str] = []
        total = 0
        try:
            with idx_file.open(encoding="utf-8", errors="ignore") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except Exception:
                        continue
                    total += 1
                    src = (rec.get("source") or "").strip()
                    if src:
                        source_counts[src] = source_counts.get(src, 0) + 1
                    title = (rec.get("title") or "").strip()
                    if title and title not in all_titles:
                        all_titles.append(title)
                    if len(text_samples) < 20:
                        text_samples.append((rec.get("text") or "")[:200])
        except Exception:
            continue

        if total < 5:
            # Skip near-empty / stale index files
            continue

        # Primary source = the filename that contributed most records, or infer from idx filename
        primary_source = max(source_counts, key=lambda k: source_counts[k]) if source_counts else ""
        if not primary_source:
            # Infer from index filename: foo_index.jsonl → foo
            primary_source = re.sub(r"_index$", "", idx_file.stem).replace("_", " ").strip()

        domain = _detect_domain(all_titles, text_samples)
        top_sections = all_titles[:30]  # first 30 unique section titles

        catalog[primary_source] = {
            "chunks": total,
            "domain": domain,
            "top_sections": top_sections,
            "idx_file": idx_file.name,
            "source_counts": source_counts,
        }

    # Save catalog
    try:
        CATALOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        CATALOG_FILE.write_text(json.dumps(catalog, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass

    return catalog


def load_book_catalog(idx_dir: Optional[Path] = None) -> Dict[str, Dict]:
    """Load the saved catalog or build it fresh if missing/stale."""
    cat_path = (idx_dir or IDX_DIR) / "_book_catalog.json"
    try:
        if cat_path.exists():
            return json.loads(cat_path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return build_book_catalog(idx_dir)


def list_indexed_books(idx_dir: Optional[Path] = None) -> Dict[str, int]:
    """Return {source_name: chunk_count} for all non-stale indexes."""
    catalog = load_book_catalog(idx_dir)
    return {name: info["chunks"] for name, info in catalog.items()}


# ── Orphan / stale index cleanup ──────────────────────────────────────────────

def clean_orphan_indexes(
    lib_dir: Optional[Path] = None,
    idx_dir: Optional[Path] = None,
    min_chunks: int = 5,
    dry_run: bool = False,
) -> List[str]:
    """
    Remove index files that:
    - Have fewer than min_chunks records (stale/empty), OR
    - Are duplicates of the same source file (keep the one with more chunks)
    Returns list of removed filenames.
    """
    search_dir = idx_dir or IDX_DIR
    src_dir    = lib_dir  or LIB_RAW
    removed: List[str] = []

    if not search_dir.is_dir():
        return removed

    # Count chunks and gather primary source name per index file
    file_info: List[Dict] = []
    for idx_file in sorted(search_dir.glob("*.jsonl")):
        if idx_file.name.startswith("_"):
            continue
        count = 0
        sources: Dict[str, int] = {}
        try:
            with idx_file.open(encoding="utf-8", errors="ignore") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                        count += 1
                        src = (rec.get("source") or "").strip()
                        if src:
                            sources[src] = sources.get(src, 0) + 1
                    except Exception:
                        pass
        except Exception:
            pass
        primary = max(sources, key=lambda k: sources[k]) if sources else ""
        file_info.append({
            "path": idx_file,
            "count": count,
            "primary": primary,
            "stem_norm": re.sub(r"[^\w]", "", idx_file.stem.lower()),
        })

    # Group by normalised source name; keep highest chunk count
    groups: Dict[str, List[Dict]] = {}
    for fi in file_info:
        key = re.sub(r"[^\w]", "", (fi["primary"] or fi["stem_norm"]).lower())
        groups.setdefault(key, []).append(fi)

    for key, group in groups.items():
        group.sort(key=lambda x: -x["count"])
        for fi in group[1:]:  # all but the winner
            if not dry_run:
                try:
                    fi["path"].unlink()
                except Exception:
                    pass
            removed.append(fi["path"].name)

    # Remove any remaining under-chunk files
    for fi in file_info:
        if fi["path"].exists() and fi["count"] < min_chunks:
            if not dry_run:
                try:
                    fi["path"].unlink()
                except Exception:
                    pass
            if fi["path"].name not in removed:
                removed.append(fi["path"].name)

    # Rebuild catalog after cleanup
    if not dry_run:
        try:
            build_book_catalog(search_dir)
        except Exception:
            pass

    return removed


# ── Keyword search across all JSONL indexes ───────────────────────────────────

def keyword_search(
    query: str,
    idx_dir: Optional[Path] = None,
    top_k: int = 8,
    min_score: int = 1,
    source_filter: Optional[str] = None,
) -> List[Dict]:
    """
    Score every indexed chunk against the query using weighted term overlap.
    Title hits count 3×, body hits 1×.  Fast — no embeddings needed.

    source_filter: if set, only search the index whose primary source matches
                   (case-insensitive substring match on source field).
    """
    search_dir = idx_dir or IDX_DIR
    if not search_dir.is_dir():
        return []

    words = set(re.findall(r"\b\w{3,}\b", query.lower()))
    if not words:
        return []

    # Resolve which index files to search
    all_idx = [f for f in sorted(search_dir.glob("*.jsonl")) if not f.name.startswith("_")]

    if source_filter:
        sf_norm = source_filter.lower()
        catalog = load_book_catalog(search_dir)
        # Find the idx_file(s) that match the filter
        matched_idx_names = set()
        for src, info in catalog.items():
            if sf_norm in src.lower() or sf_norm in (info.get("idx_file") or "").lower():
                matched_idx_names.add(info.get("idx_file", ""))
        if matched_idx_names:
            all_idx = [f for f in all_idx if f.name in matched_idx_names]
        else:
            # Fallback: substring match on filename
            all_idx = [f for f in all_idx if sf_norm in f.name.lower()]

    scored: List[tuple] = []
    for idx_file in all_idx:
        try:
            with idx_file.open(encoding="utf-8", errors="ignore") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except Exception:
                        continue
                    # Skip records with no source field (stale/malformed)
                    if not rec.get("source"):
                        continue
                    title = (rec.get("title") or "").lower()
                    text  = (rec.get("text")  or rec.get("content") or "").lower()
                    # Title scoring: cap at 6 to prevent book-title inflation
                    title_score = min(sum(3 for w in words if w in title), 6)
                    body_score  = sum(1 for w in words if w in text)
                    score = title_score + body_score
                    if score >= min_score:
                        scored.append((score, rec))
        except Exception:
            continue

    scored.sort(key=lambda x: -x[0])
    return [r for _, r in scored[:top_k]]
