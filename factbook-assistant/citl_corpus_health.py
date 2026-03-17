"""
CITL Corpus Health Scanner  — comprehensive edition
------------------------------------------------------
Validates:
  1. DB field coverage  — for every canonical field, what % of all
                          countries in the DB have a value populated?
  2. Embedding integrity — shape (N vectors × dim) for every .json index
  3. Index schemas       — JSONL record validity per index file
  4. Corpus source files — presence, size, parser-profile detection
  5. Smoke tests         — 3 full-pipeline queries exercising entity
                          detection, field routing, and answer rendering

The overall status is only OK when ALL metrics meet their thresholds.
"""
from __future__ import annotations

import json
import re
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

try:
    import executors as _executors
    _HAS_EXECUTORS = True
except Exception:
    _HAS_EXECUTORS = False

try:
    from parsers import CANONICAL_FIELD_SPECS as _CFS
    _CANONICAL_FIELDS = list(_CFS.keys())
except Exception:
    _CANONICAL_FIELDS = [
        "capital", "population", "languages", "religions", "ethnic groups",
        "literacy", "median age", "urbanization", "coastline", "climate",
        "area", "border countries",
    ]

HERE      = Path(__file__).resolve().parent
_DATA_DIR = HERE / "data"
_LIB_RAW  = _DATA_DIR / "library_raw"
_IDX_DIR  = _DATA_DIR / "indexes"
_DEFAULT_DB  = _DATA_DIR / "factbook_2023.sqlite"
_DEFAULT_SRC = HERE / "factbook.txt"

# Thresholds for OK / WARNING / ERROR
_THRESHOLD_COUNTRY_MIN   = 200        # DB must have >= this many countries
_THRESHOLD_FIELD_WARN    = 0.60       # field coverage < 60% → warning
_THRESHOLD_FIELD_ERR     = 0.30       # field coverage < 30% → error
_THRESHOLD_SMOKE_WARN    = 0.67       # < 2/3 smoke tests pass → warning
_THRESHOLD_VEC_DIM       = 256        # embedding dim must be >= this


# ── Data classes ─────────────────────────────────────────────────────────────

@dataclass
class FieldCoverageRow:
    field:       str
    count:       int     # countries with this field populated
    total:       int     # total countries in DB
    pct:         float   # count / total * 100
    sample_gaps: List[str] = field(default_factory=list)  # ≤5 missing examples


@dataclass
class EmbeddingReport:
    name:       str
    path:       Path
    exists:     bool
    vec_count:  int    # number of vectors (rows)
    vec_dim:    int    # dimension per vector
    size_bytes: int
    error:      str = ""


@dataclass
class IndexReport:
    name:          str
    path:          Path
    exists:        bool
    record_count:  int
    valid_records: int    # records that parsed as valid JSON with expected keys
    size_bytes:    int
    error:         str = ""


@dataclass
class CorpusFileReport:
    name:              str
    path:              Path
    exists:            bool
    size_bytes:        int
    line_count:        int
    word_count_approx: int
    detected_profile:  str
    error:             str = ""


@dataclass
class DbReport:
    path:          Path
    exists:        bool
    size_bytes:    int
    country_count: int
    section_count: int
    fts5_enabled:  bool
    error:         str = ""


@dataclass
class SmokeTestResult:
    question:    str
    answered:    bool
    snippet:     str
    elapsed_sec: float


@dataclass
class HealthReport:
    timestamp:      str
    overall_status: str                        # OK | WARNING | ERROR
    db:             DbReport
    field_coverage: List[FieldCoverageRow]     # per-field coverage across all countries
    embeddings:     List[EmbeddingReport]      # one per embedding file
    corpus_files:   List[CorpusFileReport]
    indexes:        List[IndexReport]
    smoke_tests:    List[SmokeTestResult]
    notes:          List[str]


# ── Parser profile detection ──────────────────────────────────────────────────

_PROFILE_SIGS: Dict[str, List[str]] = {
    "factbook":   [r"(?m)^\s*INTRODUCTION\s*$", r"Background:", r"GEOGRAPHY", r"GOVERNMENT", r"ECONOMY"],
    "nursing":    [r"(?i)\bnursing\b", r"(?i)\bpatient care\b", r"(?i)\bclinical\b", r"(?i)\bpharmacology\b"],
    "rcw":        [r"\bRCW\b", r"Revised Code of Washington", r"(?i)\bstatute\b"],
    "law":        [r"(?i)estate planning", r"(?i)property law", r"§\s*\d", r"(?i)easement"],
    "dictionary": [r"\bpronunciation\b", r"[|/][^\s|/]{1,12}[|/]", r"(?i)etymology", r"(?i)\babbr\.\b"],
}

def _detect_profile(text_head: str) -> str:
    scores: Dict[str, float] = {}
    for profile, sigs in _PROFILE_SIGS.items():
        scores[profile] = sum(1 for s in sigs if re.search(s, text_head)) / len(sigs)
    best = max(scores, key=lambda k: scores[k])
    return best if scores[best] >= 0.20 else "unknown"


# ── DB scans ──────────────────────────────────────────────────────────────────

def _scan_db(db_path: Path) -> DbReport:
    if not db_path.exists():
        return DbReport(path=db_path, exists=False, size_bytes=0,
                        country_count=0, section_count=0, fts5_enabled=False,
                        error="database not found — will auto-create on first query")
    try:
        size   = db_path.stat().st_size
        conn   = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row

        def _count(sql: str) -> int:
            try:
                row = conn.execute(sql).fetchone()
                return int(row[0]) if row else 0
            except Exception:
                return 0

        country_count = _count("SELECT COUNT(*) FROM countries")
        section_count = _count("SELECT COUNT(*) FROM sections")

        fts5_enabled = False
        try:
            row = conn.execute("SELECT value FROM meta WHERE key='fts5_enabled'").fetchone()
            fts5_enabled = bool(row and str(row["value"]).strip() in ("1", "true", "yes"))
        except Exception:
            pass

        conn.close()
        return DbReport(path=db_path, exists=True, size_bytes=size,
                        country_count=country_count, section_count=section_count,
                        fts5_enabled=fts5_enabled)
    except Exception as e:
        return DbReport(path=db_path, exists=True, size_bytes=0,
                        country_count=0, section_count=0, fts5_enabled=False,
                        error=str(e)[:200])


def _check_db_field_coverage(db_path: Path) -> List[FieldCoverageRow]:
    """
    Open the DB, iterate every country row, parse the JSON data column,
    and compute how many countries have each canonical field populated.
    This is the primary data-quality metric.
    """
    if not db_path.exists():
        return []
    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT country_name, data FROM countries").fetchall()
        conn.close()
    except Exception:
        return []

    total = len(rows)
    if total == 0:
        return []

    # {field: count_with_value}
    counts: Dict[str, int] = {f: 0 for f in _CANONICAL_FIELDS}
    # {field: [sample countries missing it]}
    gaps: Dict[str, List[str]] = {f: [] for f in _CANONICAL_FIELDS}

    for row in rows:
        country = str(row["country_name"])
        try:
            data = json.loads(row["data"] or "{}")
            cf   = data.get("canonical_fields") or {} if isinstance(data, dict) else {}
        except Exception:
            cf = {}

        for f in _CANONICAL_FIELDS:
            item = cf.get(f)
            has_value = bool(
                isinstance(item, dict)
                and str(item.get("value") or "").strip()
            )
            if has_value:
                counts[f] += 1
            elif len(gaps[f]) < 5:
                gaps[f].append(country)

    return [
        FieldCoverageRow(
            field=f,
            count=counts[f],
            total=total,
            pct=round(counts[f] / total * 100, 1),
            sample_gaps=gaps[f],
        )
        for f in _CANONICAL_FIELDS
    ]


# ── Embedding files ───────────────────────────────────────────────────────────

_EMBEDDING_FILES = [
    ("factbook_embeddings.json",    HERE / "factbook_embeddings.json"),
    ("corpus_embeddings.json",      HERE / "corpus_embeddings.json"),
    ("dictionary_embeddings.json",  HERE / "dictionary_embeddings.json"),
    ("law_embeddings.json",         HERE / "law_embeddings.json"),
    ("nursing_embeddings.json",     HERE / "nursing_embeddings.json"),
]

def _check_embedding_file(name: str, path: Path) -> EmbeddingReport:
    if not path.exists():
        return EmbeddingReport(name=name, path=path, exists=False,
                               vec_count=0, vec_dim=0, size_bytes=0)
    size = path.stat().st_size
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        return EmbeddingReport(name=name, path=path, exists=True,
                               vec_count=0, vec_dim=0, size_bytes=size,
                               error=f"JSON parse error: {e}"[:120])

    # Locate the embeddings list — handles both dict and bare-list formats.
    embs = None
    if isinstance(obj, dict):
        # Prefer declared dim when available (avoids loading full array).
        declared_dim = obj.get("dim") or 0
        embs = obj.get("embeddings") or obj.get("embedding") or []
        if isinstance(embs, list) and embs and declared_dim:
            return EmbeddingReport(name=name, path=path, exists=True,
                                   vec_count=len(embs), vec_dim=int(declared_dim),
                                   size_bytes=size)
    elif isinstance(obj, list):
        embs = obj

    if not embs or not isinstance(embs, list):
        return EmbeddingReport(name=name, path=path, exists=True,
                               vec_count=0, vec_dim=0, size_bytes=size,
                               error="embeddings array not found or empty")

    # Measure dimension from first vector.
    first = embs[0]
    if isinstance(first, list):
        vec_dim = len(first)
    elif isinstance(first, dict):
        inner = first.get("embedding") or []
        vec_dim = len(inner) if isinstance(inner, list) else 0
    else:
        vec_dim = 0

    err = "" if vec_dim >= _THRESHOLD_VEC_DIM else f"dim={vec_dim} is unexpectedly small"
    return EmbeddingReport(name=name, path=path, exists=True,
                           vec_count=len(embs), vec_dim=vec_dim,
                           size_bytes=size, error=err)


# ── Index files ───────────────────────────────────────────────────────────────

_EXPECTED_JSONL_KEYS = {"id", "text", "title", "content", "chunk", "source"}  # any one suffices

def _scan_index_file(path: Path, name: str) -> IndexReport:
    if not path.exists():
        return IndexReport(name=name, path=path, exists=False,
                           record_count=0, valid_records=0, size_bytes=0,
                           error="file not found")
    size = path.stat().st_size
    count = valid = json_errors = 0
    try:
        with path.open(encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                count += 1
                try:
                    rec = json.loads(line)
                    if isinstance(rec, dict) and _EXPECTED_JSONL_KEYS.intersection(rec.keys()):
                        valid += 1
                except Exception:
                    json_errors += 1
        err = f"{json_errors} JSON errors" if json_errors else ""
        if valid < count * 0.80 and count > 0:
            err = (err + " | " if err else "") + f"only {valid}/{count} records have expected keys"
        return IndexReport(name=name, path=path, exists=True,
                           record_count=count, valid_records=valid,
                           size_bytes=size, error=err)
    except Exception as e:
        return IndexReport(name=name, path=path, exists=True,
                           record_count=0, valid_records=0, size_bytes=size,
                           error=str(e)[:120])


# ── Corpus source files ───────────────────────────────────────────────────────

def _scan_corpus_file(path: Path) -> CorpusFileReport:
    if not path.exists():
        return CorpusFileReport(name=path.name, path=path, exists=False,
                                size_bytes=0, line_count=0, word_count_approx=0,
                                detected_profile="unknown", error="file not found")
    try:
        size = path.stat().st_size
        text = path.read_text(encoding="utf-8", errors="ignore")
        lines = text.splitlines()
        words = len(text.split())
        profile = _detect_profile(text[:8_000])
        return CorpusFileReport(name=path.name, path=path, exists=True,
                                size_bytes=size, line_count=len(lines),
                                word_count_approx=words, detected_profile=profile)
    except Exception as e:
        return CorpusFileReport(name=path.name, path=path, exists=True,
                                size_bytes=0, line_count=0, word_count_approx=0,
                                detected_profile="unknown", error=str(e)[:120])


# ── Smoke tests ───────────────────────────────────────────────────────────────

# Three queries chosen to exercise different code paths:
#   1. capital  → entity detection + new capital field + GOVERNMENT section
#   2. population → PEOPLE AND SOCIETY section, numeric value
#   3. languages  → multi-value field, same section as population
_SMOKE_PROBES = [
    "What is the capital of Romania?",
    "What is the population of Brazil?",
    "What languages are spoken in France?",
]

def _run_smoke_tests(source_path: Path, db_path: Path) -> List[SmokeTestResult]:
    if not _HAS_EXECUTORS:
        return [SmokeTestResult(question=q, answered=False,
                                snippet="executors module unavailable",
                                elapsed_sec=0.0)
                for q in _SMOKE_PROBES]
    results: List[SmokeTestResult] = []
    for q in _SMOKE_PROBES:
        t0 = time.monotonic()
        try:
            answer = _executors.try_answer_text(q,
                                                source_path=source_path,
                                                db_path=db_path)
            elapsed = time.monotonic() - t0
            answered = bool(
                answer
                and "Cannot answer" not in answer
                and len(answer.strip()) > 10
            )
            snippet = (answer or "no answer")[:180].replace("\n", " ")
        except Exception as e:
            elapsed = time.monotonic() - t0
            answered = False
            snippet   = f"Exception: {e}"[:180]
        results.append(SmokeTestResult(question=q, answered=answered,
                                       snippet=snippet,
                                       elapsed_sec=round(elapsed, 2)))
    return results


# ── Overall status computation ────────────────────────────────────────────────

def _compute_status(
    db:             DbReport,
    field_coverage: List[FieldCoverageRow],
    embeddings:     List[EmbeddingReport],
    indexes:        List[IndexReport],
    smoke_tests:    List[SmokeTestResult],
) -> Tuple[str, List[str]]:
    notes: List[str] = []
    is_error   = False
    is_warning = False

    # DB
    if not db.exists:
        notes.append("ERROR: DB missing — will auto-create on first query")
        is_error = True
    elif db.country_count == 0:
        notes.append("ERROR: DB exists but has 0 countries (not yet ingested)")
        is_error = True
    elif db.country_count < _THRESHOLD_COUNTRY_MIN:
        notes.append(f"WARNING: DB has only {db.country_count} countries (expected ≥{_THRESHOLD_COUNTRY_MIN})")
        is_warning = True
    else:
        notes.append(f"DB: {db.country_count} countries, {db.section_count} sections"
                     f", FTS5={'on' if db.fts5_enabled else 'off'}")

    # Field coverage
    if field_coverage:
        low_err  = [r for r in field_coverage if r.total > 0 and r.pct / 100 < _THRESHOLD_FIELD_ERR]
        low_warn = [r for r in field_coverage if r.total > 0 and _THRESHOLD_FIELD_ERR <= r.pct / 100 < _THRESHOLD_FIELD_WARN]
        if low_err:
            for r in low_err:
                notes.append(f"ERROR: '{r.field}' coverage {r.pct:.1f}% ({r.count}/{r.total})")
            is_error = True
        if low_warn:
            for r in low_warn:
                notes.append(f"WARNING: '{r.field}' coverage {r.pct:.1f}% ({r.count}/{r.total})")
            is_warning = True
        # Brief summary for fields that are fine
        ok_fields = [r for r in field_coverage if r.pct >= _THRESHOLD_FIELD_WARN * 100]
        if ok_fields:
            notes.append(f"Coverage OK for {len(ok_fields)}/{len(field_coverage)} fields")

    # Embeddings
    present = [e for e in embeddings if e.exists]
    if not present:
        notes.append("WARNING: no embedding files found — semantic search unavailable")
        is_warning = True
    for e in embeddings:
        if e.exists and e.error:
            notes.append(f"WARNING: {e.name} — {e.error}")
            is_warning = True
        elif e.exists:
            notes.append(f"{e.name}: {e.vec_count:,} vectors × {e.vec_dim}d")

    # Indexes
    missing_idx = [i for i in indexes if not i.exists]
    if missing_idx:
        notes.append(f"WARNING: {len(missing_idx)} index file(s) missing: "
                     + ", ".join(i.name for i in missing_idx))
        is_warning = True
    for i in indexes:
        if i.exists and i.error:
            notes.append(f"WARNING: {i.name} — {i.error}")
            is_warning = True

    # Smoke tests
    if smoke_tests:
        passed = sum(1 for s in smoke_tests if s.answered)
        total  = len(smoke_tests)
        rate   = passed / total
        if rate < _THRESHOLD_SMOKE_WARN:
            notes.append(f"WARNING: only {passed}/{total} smoke tests passed")
            is_warning = True
        else:
            notes.append(f"Smoke tests: {passed}/{total} passed")
    else:
        notes.append("Smoke tests: not run")

    if is_error:
        return "ERROR", notes
    if is_warning:
        return "WARNING", notes
    return "OK", notes


# ── Public entry point ────────────────────────────────────────────────────────

def scan_corpus_health(
    source_path: Optional[Path] = None,
    db_path:     Optional[Path] = None,
) -> HealthReport:
    """Run a comprehensive corpus health scan and return a HealthReport."""
    ts  = time.strftime("%Y-%m-%d %H:%M:%S")
    src = Path(source_path) if source_path else _DEFAULT_SRC
    dbp = Path(db_path)     if db_path     else _DEFAULT_DB

    # 1. DB presence + counts
    db_report = _scan_db(dbp)

    # 2. DB field coverage across all countries (THE key metric)
    field_coverage = _check_db_field_coverage(dbp)

    # 3. Embedding shape checks
    embeddings = [
        _check_embedding_file(name, path)
        for name, path in _EMBEDDING_FILES
        if path.exists()   # skip entirely-absent files silently (not an error for optional corpora)
    ]
    # Always include factbook embeddings even if missing
    fb_emb_path = HERE / "factbook_embeddings.json"
    if not any(e.name == "factbook_embeddings.json" for e in embeddings):
        embeddings.insert(0, _check_embedding_file("factbook_embeddings.json", fb_emb_path))

    # 4. JSONL index files
    indexes: List[IndexReport] = []
    if _IDX_DIR.is_dir():
        for p in sorted(_IDX_DIR.glob("*.jsonl")):
            indexes.append(_scan_index_file(p, p.name))

    # 5. Corpus source files (deduped by name)
    corpus_files: List[CorpusFileReport] = []
    seen_names: set = set()
    candidate_dirs = [_LIB_RAW] if _LIB_RAW.is_dir() else [src.parent]
    for d in candidate_dirs:
        for ext in ("*.txt", "*.md", "*.pdf", "*.docx"):
            for p in sorted(d.glob(ext)):
                nm = p.name.lower()
                if nm not in seen_names:
                    seen_names.add(nm)
                    corpus_files.append(_scan_corpus_file(p))
    if src.name.lower() not in seen_names and src.exists():
        corpus_files.insert(0, _scan_corpus_file(src))

    # 6. Smoke tests (full pipeline, not just DB lookup)
    smoke_tests = _run_smoke_tests(src, dbp)

    # 7. Overall status + notes
    overall_status, notes = _compute_status(
        db_report, field_coverage, embeddings, indexes, smoke_tests
    )

    return HealthReport(
        timestamp=ts,
        overall_status=overall_status,
        db=db_report,
        field_coverage=field_coverage,
        embeddings=embeddings,
        corpus_files=corpus_files,
        indexes=indexes,
        smoke_tests=smoke_tests,
        notes=notes,
    )
