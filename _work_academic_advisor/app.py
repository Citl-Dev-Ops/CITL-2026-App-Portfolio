from __future__ import annotations

import csv
import io
import json
import os
import re
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from api.ctclink_scraper import build_live_offerings_snapshot
from api.planner_core import (
    build_course_key_index,
    build_regex_corpus_from_documents,
    build_regex_corpus_records,
    course_key,
    evaluate_rule,
    estimate_pace_scenarios,
    expand_key_set,
    build_provision_summary,
    build_transcript_llm_context,
    equivalency_graph,
    extract_student_name,
    extract_text_with_ocr_fallback,
    regex_search,
    normalize_course_code,
    normalize_program_doc,
    normalize_program_from_pdf,
    normalize_transfer_rules,
    normalize_transcript_courses,
    parse_transcript_text,
    plan_terms,
    student_slug,
    suggest_programs,
)

# -----------------------------
# Paths MUST be defined first
# -----------------------------

def _resolve_project_root() -> Path:
    env_override = os.environ.get("CITL_ACADEMIC_ADVISOR_REPO")
    if env_override:
        candidate = Path(env_override).expanduser().resolve()
        if (candidate / "api" / "app.py").exists():
            return candidate

    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        source_root = exe_dir.parent
        if (source_root / "api" / "app.py").exists():
            return source_root
        return Path(getattr(sys, "_MEIPASS", exe_dir))

    return Path(__file__).resolve().parents[1]

PROJECT_ROOT = _resolve_project_root()
DATA_DIR = PROJECT_ROOT / "data"
BASELINE_DIR = DATA_DIR / "baseline"
SCHEDULES_JSON = BASELINE_DIR / "schedules_2020_2021.json"
DB_PATH = BASELINE_DIR / "schedule_offerings.sqlite"
IMPORTS_DIR = PROJECT_ROOT / "snapshots" / "imports"
PLANNER_DIR = PROJECT_ROOT / "snapshots" / "planner"
PLANNER_PROGRAMS_FILE = PLANNER_DIR / "programs_index.json"
PLANNER_TRANSFER_RULES_FILE = PLANNER_DIR / "transfer_rules.json"
PLANNER_REGEX_CORPUS_FILE = PLANNER_DIR / "regex_corpus_index.jsonl"
PLANNER_LIVE_CATALOG_FILE = PLANNER_DIR / "live_catalog_offerings.json"
PLANNER_LIVE_HISTORY_DIR = PLANNER_DIR / "live_catalog_history"
PLANNER_TRANSCRIPTS_DIR = PLANNER_DIR / "transcripts"
PLANNER_SESSION_FILE = PLANNER_TRANSCRIPTS_DIR / "session_current.json"
PLANNER_STUDENT_SESSIONS_DIR = PLANNER_TRANSCRIPTS_DIR / "students"
PLANNER_PROGRAM_PDFS_DIR = PLANNER_DIR / "program_pdfs"
ADVISOR_UI_DIST_DIR = PROJECT_ROOT / "advisor-ui" / "dist"
ALLOWED_TRANSCRIPT_SUFFIXES = {".pdf", ".txt", ".json", ".csv", ".tsv"}
DEFAULT_REGEX_DOCUMENT_GLOBS = [
    "*.pdf",
    "private/**/*.pdf",
    "snapshots/programs/**/*.pdf",
    "snapshots/planner/program_pdfs/**/*.pdf",
    "snapshots/planner/transcripts/**/*.pdf",
    "data/**/*.json",
    "data/**/*.txt",
    "docs/**/*.md",
    "docs/**/*.txt",
]
REGEX_SKIP_DIR_PARTS = {
    ".git",
    "venv",
    ".venv",
    "node_modules",
    "__pycache__",
    "dist",
    "build",
    "releases",
}
IMPORTS_DIR.mkdir(parents=True, exist_ok=True)
PLANNER_DIR.mkdir(parents=True, exist_ok=True)
PLANNER_LIVE_HISTORY_DIR.mkdir(parents=True, exist_ok=True)
PLANNER_TRANSCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
PLANNER_STUDENT_SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
PLANNER_PROGRAM_PDFS_DIR.mkdir(parents=True, exist_ok=True)

# -----------------------------
# App MUST be defined before decorators
# -----------------------------
app = FastAPI(title="CITL Academic Advisor API", version="1.0.0")

# CORS for Vite dev server(s)
ALLOW_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:5174",
    "http://127.0.0.1:5174",
    "http://localhost:5175",
    "http://127.0.0.1:5175",
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOW_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -----------------------------
# Baseline cache
# -----------------------------
_BASELINE_CACHE: Dict[str, Any] = {}
_COURSE_INDEX: List[Dict[str, Any]] = []
_COURSE_KEY_INDEX: Dict[str, Dict[str, Any]] = {}
_LIVE_COURSE_INDEX: List[Dict[str, Any]] = []
_LIVE_CATALOG_META: Dict[str, Any] = {}
_LIVE_COURSE_KEY_INDEX: Dict[str, Dict[str, Any]] = {}
_LIVE_HISTORY_COURSE_INDEX: List[Dict[str, Any]] = []
_LIVE_HISTORY_COURSE_KEY_INDEX: Dict[str, Dict[str, Any]] = {}
_LIVE_HISTORY_KEY_TIMELINE: Dict[str, Dict[str, Any]] = {}

_PLANNER_PROGRAMS: List[Dict[str, Any]] = []
_PLANNER_TRANSFER_RULES: Dict[str, Any] = {
    "equivalencies": [],
    "sbctc_mandates": [],
    "institution_mandates": {},
}
_LAST_TRANSCRIPT: Dict[str, Any] = {
    "file_name": None,
    "student_name": None,
    "student_slug": None,
    "courses": [],
    "parsed_at": None,
}
_REGEX_CORPUS_RECORDS: List[Dict[str, Any]] = []


def _load_baseline() -> None:
    global _BASELINE_CACHE, _COURSE_INDEX, _COURSE_KEY_INDEX
    if not SCHEDULES_JSON.exists():
        _BASELINE_CACHE = {}
        _COURSE_INDEX = []
        _COURSE_KEY_INDEX = {}
        return

    with SCHEDULES_JSON.open("r", encoding="utf-8") as f:
        _BASELINE_CACHE = json.load(f)

    out: List[Dict[str, Any]] = []
    for sch in _BASELINE_CACHE.get("schedules", []):
        term = sch.get("term") or sch.get("name") or "unknown"
        src = sch.get("source_pdf")
        for e in sch.get("entries", []):
            course = normalize_course_code(str(e.get("course") or ""))
            out.append(
                {
                    "term": term,
                    "course": course,
                    "course_key": course_key(course),
                    "title": e.get("title"),
                    "credits": e.get("credits"),
                    "raw_context": e.get("raw_context", []),
                    "source_pdf": e.get("source_pdf") or src,
                }
            )
    _COURSE_INDEX = out
    _COURSE_KEY_INDEX = build_course_key_index(_COURSE_INDEX)


def _load_planner_state() -> None:
    global _PLANNER_PROGRAMS, _PLANNER_TRANSFER_RULES
    if PLANNER_PROGRAMS_FILE.exists():
        try:
            payload = json.loads(PLANNER_PROGRAMS_FILE.read_text(encoding="utf-8"))
            programs = payload.get("programs") if isinstance(payload, dict) else []
            if isinstance(programs, list):
                _PLANNER_PROGRAMS = [normalize_program_doc(x) for x in programs if isinstance(x, dict)]
        except Exception:
            _PLANNER_PROGRAMS = []

    if PLANNER_TRANSFER_RULES_FILE.exists():
        try:
            payload = json.loads(PLANNER_TRANSFER_RULES_FILE.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                _PLANNER_TRANSFER_RULES = normalize_transfer_rules(payload)
        except Exception:
            _PLANNER_TRANSFER_RULES = {
                "equivalencies": [],
                "sbctc_mandates": [],
                "institution_mandates": {},
            }


def _persist_programs() -> None:
    PLANNER_PROGRAMS_FILE.write_text(
        json.dumps(
            {
                "generated_at": datetime.utcnow().isoformat() + "Z",
                "count": len(_PLANNER_PROGRAMS),
                "programs": _PLANNER_PROGRAMS,
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def _persist_transfer_rules() -> None:
    PLANNER_TRANSFER_RULES_FILE.write_text(
        json.dumps(
            {"generated_at": datetime.utcnow().isoformat() + "Z", **_PLANNER_TRANSFER_RULES},
            indent=2,
        ),
        encoding="utf-8",
    )


def _load_regex_corpus() -> None:
    global _REGEX_CORPUS_RECORDS
    _REGEX_CORPUS_RECORDS = []
    if not PLANNER_REGEX_CORPUS_FILE.exists():
        return
    try:
        with PLANNER_REGEX_CORPUS_FILE.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                if isinstance(rec, dict):
                    _REGEX_CORPUS_RECORDS.append(rec)
    except Exception:
        _REGEX_CORPUS_RECORDS = []


def _persist_regex_corpus(records: List[Dict[str, Any]]) -> None:
    with PLANNER_REGEX_CORPUS_FILE.open("w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def _load_live_catalog() -> None:
    global _LIVE_COURSE_INDEX, _LIVE_CATALOG_META, _LIVE_COURSE_KEY_INDEX
    _LIVE_COURSE_INDEX = []
    _LIVE_CATALOG_META = {}
    _LIVE_COURSE_KEY_INDEX = {}
    if not PLANNER_LIVE_CATALOG_FILE.exists():
        return
    try:
        payload = json.loads(PLANNER_LIVE_CATALOG_FILE.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return
        rows = payload.get("rows")
        if isinstance(rows, list):
            _LIVE_COURSE_INDEX = [r for r in rows if isinstance(r, dict)]
            _LIVE_COURSE_KEY_INDEX = build_course_key_index(_LIVE_COURSE_INDEX)
        _LIVE_CATALOG_META = {
            "generated_at": payload.get("generated_at"),
            "institution_code": payload.get("institution_code"),
            "term_codes": payload.get("term_codes") if isinstance(payload.get("term_codes"), list) else [],
            "term_summaries": payload.get("term_summaries") if isinstance(payload.get("term_summaries"), list) else [],
            "row_count": len(_LIVE_COURSE_INDEX),
            "class_search_api_url": payload.get("class_search_api_url"),
            "search_params": payload.get("search_params") if isinstance(payload.get("search_params"), dict) else {},
            "search_fields": payload.get("search_fields") if isinstance(payload.get("search_fields"), list) else [],
            "delta": payload.get("delta") if isinstance(payload.get("delta"), dict) else {},
            "sync_profiles": payload.get("sync_profiles") if isinstance(payload.get("sync_profiles"), list) else [],
        }
    except Exception:
        _LIVE_COURSE_INDEX = []
        _LIVE_CATALOG_META = {}
        _LIVE_COURSE_KEY_INDEX = {}


def _load_live_catalog_history() -> None:
    global _LIVE_HISTORY_COURSE_INDEX, _LIVE_HISTORY_COURSE_KEY_INDEX, _LIVE_HISTORY_KEY_TIMELINE
    _LIVE_HISTORY_COURSE_INDEX = []
    _LIVE_HISTORY_COURSE_KEY_INDEX = {}
    _LIVE_HISTORY_KEY_TIMELINE = {}
    if not PLANNER_LIVE_HISTORY_DIR.exists():
        return

    history_rows: List[Dict[str, Any]] = []
    timeline: Dict[str, Dict[str, Any]] = {}
    files = sorted(PLANNER_LIVE_HISTORY_DIR.glob("live_catalog_*.json"))
    for snap_path in files:
        try:
            payload = json.loads(snap_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue
        rows = payload.get("rows")
        if not isinstance(rows, list):
            continue

        generated_at = str(payload.get("generated_at") or "").strip() or snap_path.name
        for row in rows:
            if not isinstance(row, dict):
                continue
            normalized_course = normalize_course_code(str(row.get("course") or ""))
            key = course_key(normalized_course)
            if not key:
                continue
            term = str(row.get("term") or "").strip().upper()
            term_code = str(row.get("term_code") or "").strip()
            title = str(row.get("title") or "").strip()

            row_out = dict(row)
            row_out["course"] = normalized_course
            row_out["course_key"] = key
            row_out["_snapshot_generated_at"] = generated_at
            history_rows.append(row_out)

            meta = timeline.setdefault(
                key,
                {
                    "course_key": key,
                    "course_code": normalized_course,
                    "title_counts": {},
                    "terms": set(),
                    "term_codes": set(),
                    "seen_count": 0,
                    "first_seen_snapshot": generated_at,
                    "last_seen_snapshot": generated_at,
                    "last_seen_term": term or None,
                },
            )
            meta["seen_count"] += 1
            meta["last_seen_snapshot"] = generated_at
            if term:
                meta["terms"].add(term)
                meta["last_seen_term"] = term
            if term_code:
                meta["term_codes"].add(term_code)
            if title:
                counts = meta["title_counts"]
                counts[title] = int(counts.get(title, 0)) + 1

    _LIVE_HISTORY_COURSE_INDEX = history_rows
    _LIVE_HISTORY_COURSE_KEY_INDEX = build_course_key_index(_LIVE_HISTORY_COURSE_INDEX)

    timeline_out: Dict[str, Dict[str, Any]] = {}
    for key, meta in timeline.items():
        title_counts = meta.get("title_counts") if isinstance(meta.get("title_counts"), dict) else {}
        top_title = None
        if title_counts:
            top_title = sorted(title_counts.items(), key=lambda x: (-int(x[1]), str(x[0])))[0][0]
        history_index_row = _LIVE_HISTORY_COURSE_KEY_INDEX.get(key, {})
        timeline_out[key] = {
            "course_key": key,
            "course_code": history_index_row.get("course_code") or meta.get("course_code"),
            "title": top_title or history_index_row.get("title"),
            "terms": sorted(list(meta.get("terms") or [])),
            "term_codes": sorted(list(meta.get("term_codes") or [])),
            "seen_count": int(meta.get("seen_count") or 0),
            "first_seen_snapshot": meta.get("first_seen_snapshot"),
            "last_seen_snapshot": meta.get("last_seen_snapshot"),
            "last_seen_term": meta.get("last_seen_term"),
        }
    _LIVE_HISTORY_KEY_TIMELINE = timeline_out


def _persist_transcript_session(last: Dict[str, Any], meta: Dict[str, Any]) -> None:
    """Write enriched transcript to both the global current session and the per-student session file."""
    slug = last.get("student_slug") or "unknown"
    payload: Dict[str, Any] = {
        "file_name": last.get("file_name"),
        "student_name": last.get("student_name"),
        "student_slug": slug,
        "parsed_at": last.get("parsed_at"),
        "extract_method": meta.get("method"),
        "ocr_used": bool(meta.get("ocr_used")),
        "ocr_warnings": list(meta.get("warnings") or []),
        "provision_summary": last.get("provision_summary") or {},
        "courses": last.get("courses") or [],
        "pinned": False,
        "notes": "",
    }
    try:
        PLANNER_SESSION_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except Exception:
        pass
    # Per-student file (preserves existing pinned/notes fields if they exist)
    try:
        student_dir = PLANNER_STUDENT_SESSIONS_DIR / slug
        student_dir.mkdir(parents=True, exist_ok=True)
        student_file = student_dir / "session.json"
        if student_file.exists():
            try:
                existing = json.loads(student_file.read_text(encoding="utf-8"))
                payload["pinned"] = bool(existing.get("pinned", False))
                payload["notes"] = str(existing.get("notes") or "")
            except Exception:
                pass
        student_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except Exception:
        pass


def _load_session_if_present() -> Dict[str, Any]:
    if not PLANNER_SESSION_FILE.exists():
        return {}
    try:
        return json.loads(PLANNER_SESSION_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _list_student_sessions() -> List[Dict[str, Any]]:
    """Return summary records for all saved student sessions, newest first."""
    sessions: List[Dict[str, Any]] = []
    if not PLANNER_STUDENT_SESSIONS_DIR.exists():
        return sessions
    for slug_dir in sorted(PLANNER_STUDENT_SESSIONS_DIR.iterdir()):
        session_file = slug_dir / "session.json"
        if not session_file.is_file():
            continue
        try:
            data = json.loads(session_file.read_text(encoding="utf-8"))
            sessions.append({
                "student_slug": data.get("student_slug") or slug_dir.name,
                "student_name": data.get("student_name") or slug_dir.name.replace("_", " ").title(),
                "file_name": data.get("file_name"),
                "parsed_at": data.get("parsed_at"),
                "course_count": len(data.get("courses") or []),
                "pinned": bool(data.get("pinned", False)),
                "notes": str(data.get("notes") or ""),
                "provision_summary": data.get("provision_summary") or {},
            })
        except Exception:
            continue
    # Pinned first, then by date descending
    sessions.sort(key=lambda s: (not s["pinned"], s.get("parsed_at") or ""), reverse=False)
    return sessions


def _persist_live_catalog(snapshot: Dict[str, Any]) -> None:
    PLANNER_LIVE_CATALOG_FILE.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
    stamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    history_path = PLANNER_LIVE_HISTORY_DIR / f"live_catalog_{stamp}.json"
    history_path.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
    history_files = sorted(PLANNER_LIVE_HISTORY_DIR.glob("live_catalog_*.json"))
    if len(history_files) > 40:
        for old in history_files[: len(history_files) - 40]:
            try:
                old.unlink()
            except Exception:
                pass


def _combined_course_rows() -> List[Dict[str, Any]]:
    return [*_COURSE_INDEX, *_LIVE_COURSE_INDEX]


def _combined_course_key_index() -> Dict[str, Dict[str, Any]]:
    return build_course_key_index(_combined_course_rows())


_TITLE_TOKEN_STOPWORDS = {
    "AND",
    "FOR",
    "THE",
    "WITH",
    "IN",
    "TO",
    "OF",
    "COURSE",
    "INTRODUCTION",
    "FUNDAMENTALS",
    "PRINCIPLES",
}


def _title_tokens(text: str) -> set[str]:
    if not text:
        return set()
    out: set[str] = set()
    for token in re.findall(r"[A-Z0-9]+", text.upper()):
        if len(token) <= 1:
            continue
        if token in _TITLE_TOKEN_STOPWORDS:
            continue
        out.add(token)
    return out


def _subject_and_catalog_number(course_code: str) -> Tuple[str, Optional[int]]:
    normalized = normalize_course_code(course_code)
    match = re.match(r"^(?P<subject>[A-Z&]+)(?P<number>[0-9A-Z]+)$", normalized)
    if not match:
        return "", None
    subject = re.sub(r"[^A-Z]", "", match.group("subject"))
    raw_number = match.group("number")
    num_match = re.match(r"(\d{2,4})", raw_number)
    catalog_number = int(num_match.group(1)) if num_match else None
    return subject, catalog_number


def _equivalency_successor_targets(source_key: str, transfer_rules: Dict[str, Any]) -> List[str]:
    out: List[str] = []
    seen: set[str] = set()
    for eq in transfer_rules.get("equivalencies", []):
        if not isinstance(eq, dict):
            continue
        from_key = str(eq.get("from_key") or "")
        to_key = str(eq.get("to_key") or "")
        if from_key != source_key or not to_key:
            continue
        if to_key in seen:
            continue
        seen.add(to_key)
        out.append(to_key)
    return out


def _rank_successor_candidates(
    *,
    source_row: Dict[str, Any],
    transfer_rules: Dict[str, Any],
    catalog_by_key: Dict[str, Dict[str, Any]],
    max_candidates: int = 5,
) -> List[Dict[str, Any]]:
    source_key = str(source_row.get("course_key") or "")
    if not source_key:
        return []

    source_code = str(source_row.get("course_code") or source_key)
    source_meta = (
        catalog_by_key.get(source_key)
        or _LIVE_HISTORY_COURSE_KEY_INDEX.get(source_key)
        or _COURSE_KEY_INDEX.get(source_key)
        or {}
    )
    source_title = str(source_meta.get("title") or source_row.get("source_line") or "").strip()
    source_subject, source_catalog = _subject_and_catalog_number(source_code)
    source_tokens = _title_tokens(source_title)

    candidates_by_key: Dict[str, Dict[str, Any]] = {}
    live_index = _LIVE_COURSE_KEY_INDEX

    eq_targets = _equivalency_successor_targets(source_key, transfer_rules)
    for target_key in eq_targets:
        target_meta = live_index.get(target_key)
        if not target_meta:
            continue
        candidates_by_key[target_key] = {
            "course_key": target_key,
            "course_code": target_meta.get("course_code") or target_key,
            "title": target_meta.get("title"),
            "offered_terms": target_meta.get("terms") or [],
            "confidence": 0.99,
            "via_equivalency": True,
            "match_reasons": [f"Transfer equivalency map includes {source_key} -> {target_key}."],
        }

    for target_key, target_meta in live_index.items():
        if target_key == source_key:
            continue
        target_code = str(target_meta.get("course_code") or target_key)
        target_title = str(target_meta.get("title") or "").strip()
        target_subject, target_catalog = _subject_and_catalog_number(target_code)

        # Keep matching scoped and deterministic: same subject family only.
        if source_subject and target_subject and source_subject != target_subject:
            continue

        score = 0.0
        reasons: List[str] = []
        if source_subject and target_subject and source_subject == target_subject:
            score += 0.40
            reasons.append("same subject prefix")

        if source_catalog is not None and target_catalog is not None:
            diff = abs(source_catalog - target_catalog)
            if diff <= 5:
                score += 0.35
                reasons.append("catalog number within 5")
            elif diff <= 20:
                score += 0.22
                reasons.append("catalog number within 20")
            elif diff <= 50:
                score += 0.10
                reasons.append("catalog number within 50")

        if source_title and target_title and source_title.lower() == target_title.lower():
            score += 0.35
            reasons.append("same course title")
        else:
            target_tokens = _title_tokens(target_title)
            if source_tokens and target_tokens:
                shared = source_tokens.intersection(target_tokens)
                if shared:
                    overlap = len(shared) / max(len(source_tokens), len(target_tokens))
                    score += overlap * 0.40
                    reasons.append("title token overlap")

        if score < 0.70:
            continue

        payload = {
            "course_key": target_key,
            "course_code": target_code,
            "title": target_title or None,
            "offered_terms": target_meta.get("terms") or [],
            "confidence": round(min(score, 0.98), 2),
            "via_equivalency": False,
            "match_reasons": reasons,
        }
        existing = candidates_by_key.get(target_key)
        if not existing or float(payload["confidence"]) > float(existing.get("confidence") or 0):
            candidates_by_key[target_key] = payload

    ranked = sorted(
        candidates_by_key.values(),
        key=lambda c: (-float(c.get("confidence") or 0), str(c.get("course_code") or "")),
    )
    return ranked[: max(1, min(int(max_candidates), 8))]


def _analyze_transcript_course_lifecycle(
    *,
    normalized_transcript: List[Dict[str, Any]],
    transfer_rules: Dict[str, Any],
    catalog_by_key: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    summary = {
        "transcript_course_count": len(normalized_transcript),
        "currently_offered_count": 0,
        "not_currently_offered_count": 0,
        "not_found_in_catalogs_count": 0,
        "successor_candidate_count": 0,
        "equivalency_successor_count": 0,
    }

    if not normalized_transcript:
        return {
            "summary": summary,
            "catalog_context": {
                "generated_at": _LIVE_CATALOG_META.get("generated_at"),
                "active_terms": [x.get("term_desc") for x in (_LIVE_CATALOG_META.get("term_summaries") or []) if isinstance(x, dict)],
            },
            "alerts": [],
        }

    alerts: List[Dict[str, Any]] = []
    live_keys = set(_LIVE_COURSE_KEY_INDEX.keys())
    history_keys = set(_LIVE_HISTORY_COURSE_KEY_INDEX.keys())
    baseline_keys = set(_COURSE_KEY_INDEX.keys())

    for row in normalized_transcript:
        if not isinstance(row, dict):
            continue
        course_key_value = str(row.get("course_key") or "")
        if not course_key_value:
            continue
        course_code_value = str(row.get("course_code") or course_key_value)
        source_meta = (
            catalog_by_key.get(course_key_value)
            or _LIVE_HISTORY_COURSE_KEY_INDEX.get(course_key_value)
            or _COURSE_KEY_INDEX.get(course_key_value)
            or {}
        )
        title_value = str(source_meta.get("title") or "").strip() or None

        if course_key_value in live_keys:
            summary["currently_offered_count"] += 1
            continue

        seen_in_history = course_key_value in history_keys
        seen_in_baseline = course_key_value in baseline_keys
        timeline = _LIVE_HISTORY_KEY_TIMELINE.get(course_key_value, {})
        successors = _rank_successor_candidates(
            source_row=row,
            transfer_rules=transfer_rules,
            catalog_by_key=catalog_by_key,
            max_candidates=5,
        )
        if successors:
            summary["successor_candidate_count"] += 1
            if any(bool(x.get("via_equivalency")) for x in successors):
                summary["equivalency_successor_count"] += 1

        if seen_in_history or seen_in_baseline:
            summary["not_currently_offered_count"] += 1
            status = "historical_not_currently_offered"
            reason = "Course appears in historical catalog data but not in current active terms."
        else:
            summary["not_found_in_catalogs_count"] += 1
            status = "not_found_in_known_catalogs"
            reason = "Course was not located in baseline or live historical catalog snapshots."

        alerts.append(
            {
                "course_code": course_code_value,
                "course_key": course_key_value,
                "title": title_value,
                "status": status,
                "reason": reason,
                "seen_in_live_history": seen_in_history,
                "seen_in_baseline_catalog": seen_in_baseline,
                "last_seen_term": timeline.get("last_seen_term"),
                "last_seen_snapshot": timeline.get("last_seen_snapshot"),
                "historical_terms": timeline.get("terms") or source_meta.get("terms") or [],
                "successor_candidates": successors,
                "recommended_action": "Validate replacement/substitution with advisor and articulation policy before finalizing degree mapping.",
            }
        )

    alerts.sort(
        key=lambda a: (
            0 if any(bool(x.get("via_equivalency")) for x in (a.get("successor_candidates") or [])) else 1,
            -len(a.get("successor_candidates") or []),
            str(a.get("course_code") or ""),
        )
    )
    return {
        "summary": summary,
        "catalog_context": {
            "generated_at": _LIVE_CATALOG_META.get("generated_at"),
            "active_terms": [x.get("term_desc") for x in (_LIVE_CATALOG_META.get("term_summaries") or []) if isinstance(x, dict)],
            "term_codes": _LIVE_CATALOG_META.get("term_codes") or [],
            "history_snapshot_count": len(list(PLANNER_LIVE_HISTORY_DIR.glob("live_catalog_*.json"))),
        },
        "alerts": alerts,
    }


def _summarize_program_currency(
    *,
    required_courses: List[Dict[str, Any]],
    graph: Dict[str, set[str]],
) -> Dict[str, Any]:
    required_keys = [str(x.get("course_key")) for x in required_courses if isinstance(x, dict) and x.get("course_key")]
    required_total = len(required_keys)
    if required_total == 0:
        return {
            "status": "insufficient_data",
            "required_course_count": 0,
            "covered_current_or_mapped_count": 0,
            "coverage_ratio": 0.0,
            "note": "Program has no normalized required course keys.",
        }
    if not _LIVE_COURSE_KEY_INDEX:
        return {
            "status": "live_catalog_unavailable",
            "required_course_count": required_total,
            "covered_current_or_mapped_count": 0,
            "coverage_ratio": 0.0,
            "note": "Live catalog snapshot is not loaded; cannot measure current offering coverage.",
        }

    live_keys = set(_LIVE_COURSE_KEY_INDEX.keys())
    covered_count = 0
    not_covered: List[str] = []
    for key in required_keys:
        expanded = expand_key_set({key}, graph)
        if expanded.intersection(live_keys):
            covered_count += 1
        else:
            not_covered.append(key)

    ratio = round(covered_count / required_total, 3)
    status = "current_or_mapped"
    note = "Most required courses are currently offered or map to currently offered equivalents."
    if required_total >= 8 and ratio < 0.35:
        status = "likely_retired_or_paused"
        note = "Large share of required courses are not present in current terms; this program may be legacy, paused, or substantially revised."
    elif ratio < 0.65:
        status = "partially_current"
        note = "Program appears partially current; several required courses are not present in active terms."

    return {
        "status": status,
        "required_course_count": required_total,
        "covered_current_or_mapped_count": covered_count,
        "coverage_ratio": ratio,
        "not_current_required_course_keys": not_covered[:40],
        "note": note,
    }


def _collect_regex_source_paths(globs: List[str]) -> List[Path]:
    paths: List[Path] = []
    seen: set[Path] = set()
    for pattern in globs:
        try:
            matches = PROJECT_ROOT.glob(pattern)
        except Exception:
            continue
        for p in matches:
            if not p.is_file():
                continue
            low_parts = {x.lower() for x in p.parts}
            if low_parts.intersection(REGEX_SKIP_DIR_PARTS):
                continue
            rp = p.resolve()
            if rp in seen:
                continue
            seen.add(rp)
            paths.append(rp)
    return sorted(paths)


def _find_program(program_id: Optional[str], program_name: Optional[str]) -> Optional[Dict[str, Any]]:
    if program_id:
        for p in _PLANNER_PROGRAMS:
            if p.get("program_id") == program_id:
                return p
    if program_name:
        pn = program_name.strip().lower()
        if pn:
            exact = [p for p in _PLANNER_PROGRAMS if str(p.get("program_name") or "").strip().lower() == pn]
            if exact:
                return exact[0]
            fuzzy = [p for p in _PLANNER_PROGRAMS if pn in str(p.get("program_name") or "").strip().lower()]
            if fuzzy:
                return fuzzy[0]
    return None


def _sqlite_has_offerings_table(path: Path) -> bool:
    if not path.exists() or path.stat().st_size == 0:
        return False
    try:
        conn = sqlite3.connect(path)
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='offerings'")
        row = cur.fetchone()
        conn.close()
        return row is not None
    except Exception:
        return False


def _decode_text_bytes(raw: bytes) -> str:
    for enc in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return raw.decode(enc)
        except Exception:
            continue
    return raw.decode("utf-8", errors="ignore")


def _transcript_rows_from_json_text(text: str) -> List[Dict[str, Any]]:
    payload = json.loads(text)
    rows: List[Dict[str, Any]] = []
    candidate_rows: List[Any] = []
    text_blobs: List[str] = []

    if isinstance(payload, list):
        candidate_rows.extend(payload)
    elif isinstance(payload, dict):
        for key in ("courses", "rows", "transcript_courses", "completed_courses"):
            if isinstance(payload.get(key), list):
                candidate_rows.extend(payload.get(key) or [])
        for key in ("text", "transcript_text", "raw_text"):
            val = payload.get(key)
            if isinstance(val, str) and val.strip():
                text_blobs.append(val)
    else:
        return []

    for item in candidate_rows:
        if isinstance(item, dict):
            raw_course = str(
                item.get("course_code")
                or item.get("course")
                or item.get("course_id")
                or item.get("code")
                or ""
            ).strip()
            if raw_course:
                rows.append(
                    {
                        "course_code": raw_course,
                        "credits": item.get("credits") or item.get("credit"),
                        "item_number": item.get("item_number") or item.get("class_number") or item.get("class_nbr"),
                        "source_line": item.get("source_line") or item.get("raw"),
                    }
                )
                continue
            flattened = " ".join(
                [str(v).strip() for v in item.values() if isinstance(v, (str, int, float)) and str(v).strip()]
            ).strip()
            if flattened:
                rows.extend(parse_transcript_text(flattened))
        elif isinstance(item, str):
            rows.extend(parse_transcript_text(item))

    for blob in text_blobs:
        rows.extend(parse_transcript_text(blob))
    return rows


def _transcript_rows_from_delimited_text(text: str, delimiter: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    if not reader.fieldnames:
        return parse_transcript_text(text)
    for row in reader:
        if not isinstance(row, dict):
            continue
        lowered = {str(k).strip().lower(): v for k, v in row.items() if k}
        raw_course = str(
            lowered.get("course_code")
            or lowered.get("course")
            or lowered.get("course id")
            or lowered.get("courseid")
            or lowered.get("code")
            or ""
        ).strip()
        if raw_course:
            rows.append(
                {
                    "course_code": raw_course,
                    "credits": lowered.get("credits") or lowered.get("credit"),
                    "item_number": lowered.get("item_number")
                    or lowered.get("class_number")
                    or lowered.get("class_nbr")
                    or lowered.get("item"),
                    "source_line": " ".join([str(v).strip() for v in row.values() if str(v).strip()])[:260],
                }
            )
            continue
        flattened = " ".join([str(v).strip() for v in row.values() if str(v).strip()]).strip()
        if flattened:
            rows.extend(parse_transcript_text(flattened))
    return rows


def _extract_transcript_courses_from_file(path: Path) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    suffix = path.suffix.lower()
    warnings: List[str] = []

    if suffix == ".pdf":
        text, meta = extract_text_with_ocr_fallback(path)
        if not text.strip():
            return [], {
                "method": "pdf",
                "ocr_used": bool(meta.get("ocr_used")),
                "warnings": list(meta.get("warnings") or []),
            }
        parsed = parse_transcript_text(text)
        return normalize_transcript_courses(parsed), {
            "method": f"pdf:{meta.get('method')}",
            "ocr_used": bool(meta.get("ocr_used")),
            "warnings": list(meta.get("warnings") or []),
        }

    raw = path.read_bytes()
    text = _decode_text_bytes(raw)
    if not text.strip():
        return [], {"method": f"text:{suffix or 'unknown'}", "ocr_used": False, "warnings": []}

    parsed_rows: List[Dict[str, Any]] = []
    method = f"text:{suffix or 'unknown'}"
    if suffix == ".json":
        try:
            parsed_rows = _transcript_rows_from_json_text(text)
            method = "json"
        except Exception as e:
            warnings.append(f"JSON parse failed; fell back to regex text parse ({e})")
            parsed_rows = parse_transcript_text(text)
            method = "json:fallback_text"
    elif suffix == ".csv":
        parsed_rows = _transcript_rows_from_delimited_text(text, ",")
        method = "csv"
    elif suffix == ".tsv":
        parsed_rows = _transcript_rows_from_delimited_text(text, "\t")
        method = "tsv"
    else:
        parsed_rows = parse_transcript_text(text)
        method = "text"

    return normalize_transcript_courses(parsed_rows), {"method": method, "ocr_used": False, "warnings": warnings}


def _live_row_key(row: Dict[str, Any]) -> str:
    return "|".join(
        [
            str(row.get("institution_code") or ""),
            str(row.get("term_code") or row.get("term") or ""),
            str(row.get("class_nbr") or ""),
            str(row.get("course_key") or ""),
            str(row.get("section") or ""),
        ]
    )


def _live_row_signature(row: Dict[str, Any]) -> str:
    fields = {
        "status": row.get("status"),
        "enrl_status": row.get("enrl_status"),
        "delivery": row.get("delivery"),
        "instructor": row.get("instructor"),
        "credits": row.get("credits"),
        "start_dt": row.get("start_dt"),
        "end_dt": row.get("end_dt"),
        "location": row.get("location"),
        "campus": row.get("campus"),
        "title": row.get("title"),
    }
    return json.dumps(fields, sort_keys=True, default=str)


def _compute_live_catalog_delta(
    previous_rows: List[Dict[str, Any]],
    current_rows: List[Dict[str, Any]],
) -> Dict[str, Any]:
    prev_map = {_live_row_key(r): r for r in previous_rows if isinstance(r, dict)}
    curr_map = {_live_row_key(r): r for r in current_rows if isinstance(r, dict)}
    prev_keys = set(prev_map.keys())
    curr_keys = set(curr_map.keys())

    added_keys = sorted(list(curr_keys - prev_keys))
    removed_keys = sorted(list(prev_keys - curr_keys))
    shared_keys = prev_keys.intersection(curr_keys)
    changed_keys: List[str] = []
    for key in shared_keys:
        if _live_row_signature(prev_map[key]) != _live_row_signature(curr_map[key]):
            changed_keys.append(key)

    added_samples = [curr_map[k] for k in added_keys[:25]]
    removed_samples = [prev_map[k] for k in removed_keys[:25]]
    changed_samples = [
        {"key": key, "before": prev_map[key], "after": curr_map[key]}
        for key in sorted(changed_keys)[:25]
    ]
    return {
        "previous_row_count": len(prev_map),
        "current_row_count": len(curr_map),
        "added_count": len(added_keys),
        "removed_count": len(removed_keys),
        "changed_count": len(changed_keys),
        "added_samples": added_samples,
        "removed_samples": removed_samples,
        "changed_samples": changed_samples,
    }


SUPPORTED_POLICY_RULE_TYPES = {
    "min_transfer_credits",
    "requires_course",
    "any_of_courses",
    "min_courses_with_prefix",
    "min_courses_with_ampersand",
    "requires_item_number",
    "min_credits_in_prefixes",
    "max_transfer_credits",
    "disallow_courses",
    "admin_approval_if_missing_courses",
    "hard_block_if_missing_courses",
}


def _policy_rules_with_scope(institution: Optional[str], include_all_institutions: bool) -> List[Tuple[str, Dict[str, Any]]]:
    out: List[Tuple[str, Dict[str, Any]]] = []
    for rule in _PLANNER_TRANSFER_RULES.get("sbctc_mandates", []):
        if isinstance(rule, dict):
            out.append(("SBCTC", rule))
    inst_rules = _PLANNER_TRANSFER_RULES.get("institution_mandates", {})
    if not isinstance(inst_rules, dict):
        return out
    if include_all_institutions or not institution:
        for inst_name, rules in inst_rules.items():
            if not isinstance(rules, list):
                continue
            for rule in rules:
                if isinstance(rule, dict):
                    out.append((str(inst_name), rule))
        return out
    rules = inst_rules.get(institution) if isinstance(inst_rules.get(institution), list) else []
    for rule in rules:
        if isinstance(rule, dict):
            out.append((str(institution), rule))
    return out


def _add_policy_issue(issues: List[Dict[str, Any]], severity: str, scope: str, rule_id: str, message: str) -> None:
    issues.append(
        {
            "severity": severity,
            "scope": scope,
            "rule_id": rule_id,
            "message": message,
        }
    )


def _run_policy_qa(
    *,
    institution: Optional[str],
    include_all_institutions: bool,
    include_regex_hints: bool,
    regex_hint_limit: int,
) -> Dict[str, Any]:
    issues: List[Dict[str, Any]] = []
    rules_scoped = _policy_rules_with_scope(institution, include_all_institutions)
    if not rules_scoped:
        _add_policy_issue(issues, "medium", "global", "no_rules", "No transfer/mandate policy rules are loaded.")

    id_seen: Dict[str, str] = {}
    min_credit_rules: List[Tuple[str, str, float]] = []
    max_credit_rules: List[Tuple[str, str, float]] = []
    required_keys: set[str] = set()
    disallowed_keys: set[str] = set()
    approval_keys: set[str] = set()
    hard_block_keys: set[str] = set()
    catalog_keys = set(_combined_course_key_index().keys())

    for scope, rule in rules_scoped:
        rid = str(rule.get("id") or "unknown")
        rtype = str(rule.get("type") or "").strip()
        if not rtype:
            _add_policy_issue(issues, "high", scope, rid, "Rule type is missing.")
            continue
        if rtype not in SUPPORTED_POLICY_RULE_TYPES:
            _add_policy_issue(issues, "high", scope, rid, f"Unsupported rule type: {rtype}")
            continue
        if rid in id_seen:
            _add_policy_issue(
                issues,
                "high",
                scope,
                rid,
                f"Duplicate rule id also used in scope {id_seen[rid]}",
            )
        else:
            id_seen[rid] = scope
        if not str(rule.get("description") or "").strip():
            _add_policy_issue(issues, "low", scope, rid, "Rule has no description (harder to explain to students).")

        if rtype in {"requires_course", "disallow_courses", "admin_approval_if_missing_courses", "hard_block_if_missing_courses"}:
            keys = []
            if rule.get("course_key"):
                keys.append(str(rule.get("course_key")))
            keys.extend([str(x) for x in (rule.get("course_keys") or []) if str(x)])
            if not keys:
                _add_policy_issue(issues, "high", scope, rid, f"{rtype} requires course_key/course_keys.")
            unknown = [k for k in keys if k and k not in catalog_keys]
            if unknown:
                _add_policy_issue(
                    issues,
                    "low",
                    scope,
                    rid,
                    f"{len(unknown)} course key(s) not in current catalog index: {unknown[:6]}",
                )
            if rtype == "requires_course":
                required_keys.update(keys)
            if rtype == "disallow_courses":
                disallowed_keys.update(keys)
            if rtype == "admin_approval_if_missing_courses":
                approval_keys.update(keys)
                if int(rule.get("min_missing") or 1) < 1:
                    _add_policy_issue(issues, "medium", scope, rid, "min_missing should be >= 1.")
            if rtype == "hard_block_if_missing_courses":
                hard_block_keys.update(keys)
                if int(rule.get("min_missing") or 1) < 1:
                    _add_policy_issue(issues, "medium", scope, rid, "min_missing should be >= 1.")

        if rtype == "min_transfer_credits":
            try:
                min_val = float(rule.get("min") or 0)
                min_credit_rules.append((scope, rid, min_val))
                if min_val < 0:
                    _add_policy_issue(issues, "high", scope, rid, "min_transfer_credits cannot be negative.")
            except Exception:
                _add_policy_issue(issues, "high", scope, rid, "min_transfer_credits value is invalid.")

        if rtype == "max_transfer_credits":
            try:
                max_val = float(rule.get("max") or 0)
                max_credit_rules.append((scope, rid, max_val))
                if max_val < 0:
                    _add_policy_issue(issues, "high", scope, rid, "max_transfer_credits cannot be negative.")
            except Exception:
                _add_policy_issue(issues, "high", scope, rid, "max_transfer_credits value is invalid.")

    if required_keys.intersection(disallowed_keys):
        overlap = sorted(list(required_keys.intersection(disallowed_keys)))
        _add_policy_issue(
            issues,
            "high",
            "cross_scope",
            "contradiction:req_vs_disallow",
            f"Course keys appear in both required and disallowed rules: {overlap[:10]}",
        )
    if approval_keys.intersection(hard_block_keys):
        overlap = sorted(list(approval_keys.intersection(hard_block_keys)))
        _add_policy_issue(
            issues,
            "medium",
            "cross_scope",
            "overlap:approval_vs_hardblock",
            f"Same keys appear in both approval-required and hard-block rules: {overlap[:10]}",
        )

    for min_scope, min_id, min_val in min_credit_rules:
        for max_scope, max_id, max_val in max_credit_rules:
            if min_val > max_val:
                _add_policy_issue(
                    issues,
                    "high",
                    f"{min_scope}|{max_scope}",
                    f"{min_id}|{max_id}",
                    f"min_transfer_credits ({min_val}) exceeds max_transfer_credits ({max_val}).",
                )

    severity_counts = {"high": 0, "medium": 0, "low": 0}
    for item in issues:
        sev = str(item.get("severity") or "low")
        if sev not in severity_counts:
            severity_counts[sev] = 0
        severity_counts[sev] += 1

    score = 100 - (severity_counts.get("high", 0) * 20) - (severity_counts.get("medium", 0) * 8) - (severity_counts.get("low", 0) * 2)
    score = max(0, min(100, score))

    regex_hints = []
    if include_regex_hints and _REGEX_CORPUS_RECORDS:
        regex_hints = regex_search(
            _REGEX_CORPUS_RECORDS,
            "approval required hard limit not transferable excluded equivalency articulation",
            max(1, min(regex_hint_limit, 120)),
        )

    return {
        "ok": True,
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "institution": institution,
        "include_all_institutions": include_all_institutions,
        "rule_count": len(rules_scoped),
        "severity_counts": severity_counts,
        "issues": issues,
        "policy_readiness_score": score,
        "regex_hints": regex_hints,
    }


def _estimate_remaining_credits(
    rows: List[Dict[str, Any]],
    catalog_by_key: Dict[str, Dict[str, Any]],
) -> float:
    total = 0.0
    for item in rows:
        if not isinstance(item, dict):
            continue
        cr = item.get("credits")
        if cr is None:
            ckey = item.get("course_key")
            if ckey:
                cr = catalog_by_key.get(str(ckey), {}).get("credits_guess")
        total += float(cr or 0)
    return round(total, 3)


def _build_program_plan_data(
    *,
    program: Dict[str, Any],
    institution: str,
    begin_term: str,
    max_credits_per_term: float,
    horizon_terms: int,
    normalized_transcript: List[Dict[str, Any]],
    transfer_rules: Dict[str, Any],
    catalog_by_key: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    graph = equivalency_graph(transfer_rules)
    transcript_keys = {x.get("course_key") for x in normalized_transcript if x.get("course_key")}
    expanded_keys = expand_key_set(set(transcript_keys), graph)
    total_credits = round(sum(float(x.get("credits") or 0) for x in normalized_transcript), 3)

    required_courses = program.get("required_courses") or []
    missing_required: List[Dict[str, Any]] = []
    satisfied_required: List[Dict[str, Any]] = []
    for item in required_courses:
        if not isinstance(item, dict):
            continue
        ckey = item.get("course_key")
        if not ckey:
            continue
        if ckey in expanded_keys:
            satisfied_required.append(item)
        else:
            missing_required.append(item)

    elective_results = []
    elective_course_keys: set[str] = set()
    for group in program.get("elective_groups") or []:
        if not isinstance(group, dict):
            continue
        choose = int(group.get("choose") or 1)
        courses = group.get("courses") if isinstance(group.get("courses"), list) else []
        for c in courses:
            if isinstance(c, dict) and c.get("course_key"):
                elective_course_keys.add(str(c.get("course_key")))
        hits = [c for c in courses if isinstance(c, dict) and c.get("course_key") in expanded_keys]
        elective_results.append(
            {
                "id": group.get("id"),
                "name": group.get("name"),
                "choose": choose,
                "have": len(hits),
                "ok": len(hits) >= choose,
                "hits": [h.get("course_code") for h in hits],
            }
        )

    program_required_keys = {
        str(x.get("course_key"))
        for x in required_courses
        if isinstance(x, dict) and x.get("course_key")
    }
    program_relevant_keys = set(program_required_keys).union(elective_course_keys)

    disallowed_keys: set[str] = set()
    for rule in transfer_rules.get("sbctc_mandates", []):
        if str(rule.get("type") or "").strip() == "disallow_courses":
            for key in rule.get("course_keys") or []:
                disallowed_keys.add(str(key))
    for rule in transfer_rules.get("institution_mandates", {}).get(institution, []):
        if str(rule.get("type") or "").strip() == "disallow_courses":
            for key in rule.get("course_keys") or []:
                disallowed_keys.add(str(key))

    compatible_courses: List[Dict[str, Any]] = []
    incompatible_courses: List[Dict[str, Any]] = []
    unmapped_courses: List[Dict[str, Any]] = []
    for row in normalized_transcript:
        if not isinstance(row, dict):
            continue
        row_key = str(row.get("course_key") or "")
        if not row_key:
            continue
        row_expanded = expand_key_set({row_key}, graph)
        payload = {
            "course_code": row.get("course_code"),
            "course_key": row_key,
            "credits": row.get("credits"),
            "item_number": row.get("item_number"),
        }
        if row_expanded.intersection(disallowed_keys):
            incompatible_courses.append({**payload, "reason": "Disallowed by transfer policy rule."})
            continue
        if row_expanded.intersection(program_relevant_keys):
            compatible_courses.append({**payload, "reason": "Matches required/elective or mapped equivalent."})
            continue
        unmapped_courses.append({**payload, "reason": "Not mapped to target program requirements."})

    mandates = []
    for r in transfer_rules.get("sbctc_mandates", []):
        mandates.append({"scope": "SBCTC", **evaluate_rule(r, normalized_transcript, expanded_keys, total_credits)})
    for r in transfer_rules.get("institution_mandates", {}).get(institution, []):
        mandates.append({"scope": institution, **evaluate_rule(r, normalized_transcript, expanded_keys, total_credits)})
    hard_block_flags = [m for m in mandates if bool(m.get("hard_block"))]
    approval_required_flags = [m for m in mandates if bool(m.get("approval_required"))]
    decision_status = "ok"
    if hard_block_flags:
        decision_status = "blocked"
    elif approval_required_flags:
        decision_status = "approval_required"

    pathway, remaining = plan_terms(
        missing_courses=missing_required,
        begin_term=begin_term,
        max_credits_per_term=max_credits_per_term,
        horizon_terms=horizon_terms,
        catalog_by_key=catalog_by_key,
    )

    remaining_credits = _estimate_remaining_credits(missing_required, catalog_by_key)
    remaining_after_horizon_credits = _estimate_remaining_credits(remaining, catalog_by_key)
    planned_credits_total = round(sum(float(t.get("planned_credits") or 0) for t in pathway), 3)
    program_currency = _summarize_program_currency(
        required_courses=required_courses,
        graph=graph,
    )

    return {
        "required_courses": required_courses,
        "missing_required": missing_required,
        "satisfied_required": satisfied_required,
        "elective_results": elective_results,
        "mandates": mandates,
        "hard_block_flags": hard_block_flags,
        "approval_required_flags": approval_required_flags,
        "decision_status": decision_status,
        "compatible_courses": compatible_courses,
        "incompatible_courses": incompatible_courses,
        "unmapped_courses": unmapped_courses,
        "pathway": pathway,
        "remaining_after_horizon": remaining,
        "remaining_required_credits": remaining_credits,
        "remaining_after_horizon_credits": remaining_after_horizon_credits,
        "planned_credits_total": planned_credits_total,
        "total_transcript_credits": total_credits,
        "program_currency": program_currency,
    }


_load_baseline()
_load_planner_state()
_load_regex_corpus()
_load_live_catalog()
_load_live_catalog_history()


@app.get("/health")
def health() -> Dict[str, Any]:
    combined_course_key_count = len(_combined_course_key_index())
    return {
        "ok": True,
        "project_root": str(PROJECT_ROOT),
        "baseline_json_exists": SCHEDULES_JSON.exists(),
        "baseline_entries_indexed": len(_COURSE_INDEX),
        "known_course_keys": len(_COURSE_KEY_INDEX),
        "known_course_keys_with_live": combined_course_key_count,
        "sqlite_exists": DB_PATH.exists(),
        "planner_program_count": len(_PLANNER_PROGRAMS),
        "planner_transfer_rule_count": len(_PLANNER_TRANSFER_RULES.get("sbctc_mandates", [])),
        "planner_institution_rule_count": sum(
            len(v) for v in _PLANNER_TRANSFER_RULES.get("institution_mandates", {}).values()
        ),
        "planner_regex_corpus_records": len(_REGEX_CORPUS_RECORDS),
        "live_catalog_entries": len(_LIVE_COURSE_INDEX),
        "live_catalog_course_keys": len(_LIVE_COURSE_KEY_INDEX),
        "live_catalog_history_entries": len(_LIVE_HISTORY_COURSE_INDEX),
        "live_catalog_history_course_keys": len(_LIVE_HISTORY_COURSE_KEY_INDEX),
    }


@app.get("/baseline/list")
def baseline_list() -> Dict[str, Any]:
    files = []
    if BASELINE_DIR.exists():
        files = [p.name for p in BASELINE_DIR.glob("*.json")]
    return {"count": len(files), "files": sorted(files)}


@app.get("/baseline/{name}")
def baseline_get(name: str) -> Any:
    p = BASELINE_DIR / name
    if not p.exists():
        raise HTTPException(404, f"Not Found: baseline/{name}")
    return json.loads(p.read_text(encoding="utf-8"))


@app.get("/courses")
def courses(q: str = "", limit: int = 50) -> Dict[str, Any]:
    qn = (q or "").strip().lower()
    if not qn:
        return {"query": q, "count": 0, "results": []}

    def hit(row: Dict[str, Any]) -> bool:
        course = (row.get("course") or "").lower()
        title = (row.get("title") or "").lower()
        ckey = (row.get("course_key") or "").lower()
        ctx = " ".join(row.get("raw_context") or []).lower()
        return qn in course or qn in title or qn in ctx or qn in ckey

    matches = [r for r in _COURSE_INDEX if hit(r)]
    return {"query": q, "count": min(len(matches), limit), "results": matches[:limit]}


@app.get("/offerings")
def offerings(q: str = "", limit: int = 50) -> Dict[str, Any]:
    qn = (q or "").strip()
    if not qn:
        return {"query": q, "count": 0, "results": []}

    if _sqlite_has_offerings_table(DB_PATH):
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        like = f"%{qn}%"
        cur.execute(
            """
            SELECT term, course_code, title, credits, status, delivery, instructor, source_pdf
            FROM offerings
            WHERE course_code LIKE ? OR title LIKE ? OR raw_context LIKE ?
            LIMIT ?
            """,
            (like, like, like, limit),
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return {"query": q, "count": len(rows), "results": rows}

    qn_lower = qn.lower()
    results = []
    for row in _combined_course_rows():
        if (
            qn_lower in str(row.get("course") or "").lower()
            or qn_lower in str(row.get("title") or "").lower()
            or qn_lower in " ".join(row.get("raw_context") or []).lower()
        ):
            results.append(
                {
                    "term": row.get("term"),
                    "course_code": row.get("course"),
                    "title": row.get("title"),
                    "credits": row.get("credits"),
                    "status": row.get("status"),
                    "delivery": row.get("delivery"),
                    "instructor": row.get("instructor"),
                    "source_pdf": row.get("source_pdf"),
                }
            )
            if len(results) >= limit:
                break
    return {"query": q, "count": len(results), "results": results}


@app.get("/offerings/browse")
def offerings_browse(
    subject: str = "",
    term: str = "",
    delivery: str = "",
    open_only: bool = False,
    program_id: str = "",
    q: str = "",
    limit: int = 200,
) -> Dict[str, Any]:
    """
    Structured course catalog browser with subject, term, delivery, open-only, and program filters.
    Returns duplicate-annotated results with time-of-day fields when available.
    """
    subj_f = subject.strip().upper().rstrip("&")
    term_f = term.strip().upper()
    deliv_f = delivery.strip().lower()
    q_f = q.strip().lower()

    # Optional: resolve program required-course set
    prog_codes: Optional[set] = None
    if program_id.strip():
        prog = _find_program(program_id.strip(), None)
        if prog:
            prog_codes = set()
            for c in (prog.get("required_courses") or []):
                prog_codes.add(normalize_course_code(str(c.get("course_code") or "")))
            for eg in (prog.get("elective_groups") or []):
                for c in (eg.get("options") or []):
                    prog_codes.add(normalize_course_code(str(c.get("course_code") or "")))

    # Build source rows from live catalog + SQLite baseline
    source_rows: List[Dict[str, Any]] = []
    for row in _LIVE_COURSE_INDEX:
        source_rows.append({
            "term":         str(row.get("term") or row.get("TERM_DESCR") or ""),
            "course_code":  str(row.get("course_code") or row.get("SUBJECT") or ""),
            "title":        str(row.get("title") or row.get("COURSE_TITLE") or ""),
            "credits":      row.get("credits") or row.get("UNITS_MINIMUM"),
            "status":       str(row.get("status") or row.get("ENRL_STAT_DESCR") or ""),
            "delivery":     str(row.get("delivery") or row.get("INSTRUCTION_MODE_DESCR") or ""),
            "instructor":   str(row.get("instructor") or row.get("NAME") or ""),
            "start_time":   str(row.get("start_time") or row.get("MEETING_TIME_START") or ""),
            "end_time":     str(row.get("end_time") or row.get("MEETING_TIME_END") or ""),
            "days":         str(row.get("days") or row.get("MEETING_DAYS") or ""),
            "section":      str(row.get("section") or row.get("SECTION") or ""),
            "class_number": str(row.get("class_number") or row.get("CLASS_NBR") or ""),
            "source":       "live",
        })

    if _sqlite_has_offerings_table(DB_PATH):
        try:
            conn = sqlite3.connect(DB_PATH)
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute(
                "SELECT term, course_code, title, credits, status, delivery, instructor FROM offerings LIMIT 10000"
            )
            for r in cur.fetchall():
                source_rows.append({
                    **dict(r),
                    "start_time": "", "end_time": "", "days": "",
                    "section": "", "class_number": "", "source": "baseline",
                })
            conn.close()
        except Exception:
            pass

    # Tally for duplicate detection (same normalized code appearing multiple times)
    code_counts: Dict[str, int] = {}
    for row in source_rows:
        nk = normalize_course_code(str(row.get("course_code") or "").upper())
        code_counts[nk] = code_counts.get(nk, 0) + 1

    results: List[Dict[str, Any]] = []
    for row in source_rows:
        code = str(row.get("course_code") or "").strip().upper()
        term_val = str(row.get("term") or "").strip().upper()
        deliv_val = str(row.get("delivery") or "").strip().lower()
        status_val = str(row.get("status") or "").strip().lower()
        title_val = str(row.get("title") or "").strip()

        # Subject filter
        if subj_f:
            m = re.match(r"^([A-Z]{2,10})", code.replace("&", ""))
            if not m or m.group(1) != subj_f.replace("&", ""):
                continue

        # Term filter
        if term_f and term_f not in term_val:
            continue

        # Delivery filter
        if deliv_f and deliv_f not in deliv_val:
            continue

        # Open-only
        if open_only:
            if not ("open" in status_val or status_val == "o"):
                continue

        # Program filter
        if prog_codes is not None:
            if normalize_course_code(code) not in prog_codes:
                continue

        # Keyword search
        if q_f and q_f not in code.lower() and q_f not in title_val.lower():
            continue

        nk = normalize_course_code(code)
        row["has_duplicates"] = code_counts.get(nk, 1) > 1
        row["section_count"] = code_counts.get(nk, 1)
        results.append(row)

        if len(results) >= limit:
            break

    return {"count": len(results), "results": results}


@app.get("/planner/departments")
def planner_departments() -> Dict[str, Any]:
    """
    Return unique subject/department prefixes derived from loaded programs and live catalog.
    Each entry is a subject code like 'ENGL', 'MATH', 'CIS'.
    """
    seen: set = set()
    depts: List[str] = []
    _subj_re = re.compile(r"^([A-Z]{2,10})")

    def _add(code: str) -> None:
        c = code.strip().upper().replace("&", "")
        m = _subj_re.match(c)
        if m:
            s = m.group(1)
            if s not in seen:
                seen.add(s)
                depts.append(s)

    for p in _PLANNER_PROGRAMS:
        for c in (p.get("required_courses") or []):
            _add(str(c.get("course_code") or ""))
        for eg in (p.get("elective_groups") or []):
            for c in (eg.get("options") or []):
                _add(str(c.get("course_code") or ""))

    for row in _LIVE_COURSE_INDEX:
        _add(str(row.get("course_code") or row.get("SUBJECT") or ""))

    if _sqlite_has_offerings_table(DB_PATH):
        try:
            conn = sqlite3.connect(DB_PATH)
            cur = conn.cursor()
            cur.execute("SELECT DISTINCT course_code FROM offerings")
            for (code,) in cur.fetchall():
                _add(str(code or ""))
            conn.close()
        except Exception:
            pass

    depts.sort()
    return {"count": len(depts), "departments": depts}


# -----------------------------
# Transcript PDF parsing (student-friendly)
# -----------------------------
class TranscriptParseResult(BaseModel):
    ok: bool
    message: str
    courses: List[Dict[str, Any]]
    unique_course_count: int = 0
    item_number_count: int = 0
    transcript_path: Optional[str] = None
    ocr_used: bool = False
    extract_method: Optional[str] = None
    ocr_warnings: List[str] = Field(default_factory=list)


@app.post("/imports/transcript", response_model=TranscriptParseResult)
async def imports_transcript(file: UploadFile = File(...)) -> TranscriptParseResult:
    if not file.filename:
        raise HTTPException(400, "Please upload a transcript file.")
    suffix = Path(file.filename).suffix.lower()
    if suffix not in ALLOWED_TRANSCRIPT_SUFFIXES:
        allowed = ", ".join(sorted(ALLOWED_TRANSCRIPT_SUFFIXES))
        raise HTTPException(400, f"Unsupported transcript format: {suffix or 'unknown'}. Allowed: {allowed}")

    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", file.filename)
    out_path = IMPORTS_DIR / f"transcript_{safe_name}"
    with out_path.open("wb") as f:
        f.write(await file.read())

    try:
        found, meta = _extract_transcript_courses_from_file(out_path)
    except RuntimeError as e:
        raise HTTPException(500, str(e))

    if not found:
        return TranscriptParseResult(
            ok=True,
            message="No transcript courses could be extracted from the uploaded file.",
            courses=[],
            unique_course_count=0,
            item_number_count=0,
            transcript_path=str(out_path),
            ocr_used=bool(meta.get("ocr_used")),
            extract_method=meta.get("method"),
            ocr_warnings=list(meta.get("warnings") or []),
        )

    # Detect student name from file text
    _detected_name: Optional[str] = None
    try:
        _raw_text = out_path.read_text(encoding="utf-8", errors="ignore") if out_path.suffix.lower() != ".pdf" else None
        if _raw_text is None:
            from api.planner_core import extract_text_with_ocr_fallback as _etf
            _raw_text, _ = _etf(out_path)
        _detected_name = extract_student_name(_raw_text or "")
        if not _detected_name:
            _detected_name = Path(file.filename).stem.replace("_", " ").replace("-", " ").title()
    except Exception:
        pass

    _LAST_TRANSCRIPT["file_name"] = safe_name
    _LAST_TRANSCRIPT["student_name"] = _detected_name
    _LAST_TRANSCRIPT["student_slug"] = student_slug(_detected_name or "unknown")
    _LAST_TRANSCRIPT["courses"] = found
    _LAST_TRANSCRIPT["parsed_at"] = datetime.utcnow().isoformat() + "Z"
    _LAST_TRANSCRIPT["provision_summary"] = build_provision_summary(found)
    _persist_transcript_session(_LAST_TRANSCRIPT, meta)

    return TranscriptParseResult(
        ok=True,
        message=f"Extracted {len(found)} unique course item(s) from transcript file.",
        courses=found,
        unique_course_count=len(found),
        item_number_count=sum(1 for c in found if c.get("item_number")),
        transcript_path=str(out_path),
        ocr_used=bool(meta.get("ocr_used")),
        extract_method=meta.get("method"),
        ocr_warnings=list(meta.get("warnings") or []),
    )


# -----------------------------
# Planner endpoints
# -----------------------------
class ProgramImportJSONBody(BaseModel):
    programs: List[Dict[str, Any]]
    replace: bool = False


class TransferRulesImportBody(BaseModel):
    rules: Dict[str, Any]
    replace: bool = False


class ProgramSuggestRequest(BaseModel):
    transcript_courses: Optional[List[Dict[str, Any]]] = None
    limit: int = Field(default=5, ge=1, le=20)


class PlanRequest(BaseModel):
    institution: str = "Renton Technical College"
    begin_term: str = "SPRING 2026"
    pace_mode: Optional[str] = "full_time"
    target_program_id: Optional[str] = None
    target_program_name: Optional[str] = None
    transcript_courses: Optional[List[Dict[str, Any]]] = None
    max_credits_per_term: float = Field(default=15.0, ge=1.0, le=30.0)
    horizon_terms: int = Field(default=8, ge=1, le=24)
    tuition_per_credit: Optional[float] = Field(default=None, ge=0)
    fees_per_term: float = Field(default=0.0, ge=0)
    books_per_term: float = Field(default=0.0, ge=0)
    include_pace_scenarios: bool = True


class RegexSearchRequest(BaseModel):
    query: str
    limit: int = Field(default=25, ge=1, le=200)


class RegexCorpusReindexRequest(BaseModel):
    include_program_index: bool = True
    include_baseline_catalog: bool = True
    include_local_documents: bool = True
    document_globs: List[str] = Field(default_factory=list)


class LiveCatalogUpdateRequest(BaseModel):
    institution_code: str = "WA270"
    class_search_main_url: str = (
        "https://csprd.ctclink.us/psc/csprd/EMPLOYEE/SA/s/"
        "WEBLIB_HCX_CM.H_CLASS_SEARCH.FieldFormula.IScript_Main"
    )
    term_codes: Optional[List[str]] = None
    term_count: int = Field(default=3, ge=1, le=8)
    enrl_stat: str = "O"
    subject: str = ""
    acad_career: str = ""
    keyword: str = ""
    subject_like: str = ""
    catalog_nbr: str = ""
    instruction_mode: str = ""
    class_nbr: str = ""
    crse_attr: str = ""
    crse_attr_value: str = ""
    location: str = ""
    campus: str = ""
    session_code: str = ""
    search_params: Dict[str, Any] = Field(default_factory=dict)
    timeout_seconds: int = Field(default=45, ge=10, le=180)


class LiveCatalogSyncProfile(BaseModel):
    name: str = "default"
    institution_code: str = "WA270"
    class_search_main_url: str = (
        "https://csprd.ctclink.us/psc/csprd/EMPLOYEE/SA/s/"
        "WEBLIB_HCX_CM.H_CLASS_SEARCH.FieldFormula.IScript_Main"
    )
    term_codes: Optional[List[str]] = None
    term_count: int = Field(default=3, ge=1, le=8)
    enrl_stat: str = "O"
    subject: str = ""
    acad_career: str = ""
    search_params: Dict[str, Any] = Field(default_factory=dict)


class LiveCatalogSyncRequest(BaseModel):
    profiles: List[LiveCatalogSyncProfile]
    timeout_seconds: int = Field(default=60, ge=10, le=240)


class PathwayPredictRequest(BaseModel):
    institution: str = "Renton Technical College"
    begin_term: str = "SPRING 2026"
    pace_mode: str = "part_time"
    transcript_courses: Optional[List[Dict[str, Any]]] = None
    max_credits_per_term: float = Field(default=8.0, ge=1.0, le=30.0)
    horizon_terms: int = Field(default=12, ge=1, le=24)
    candidate_limit: int = Field(default=8, ge=1, le=30)
    tuition_per_credit: Optional[float] = Field(default=None, ge=0)
    fees_per_term: float = Field(default=0.0, ge=0)
    books_per_term: float = Field(default=0.0, ge=0)


class CourseLifecycleRequest(BaseModel):
    transcript_courses: Optional[List[Dict[str, Any]]] = None
    limit: int = Field(default=120, ge=1, le=500)


class PolicyQARequest(BaseModel):
    institution: Optional[str] = None
    include_all_institutions: bool = True
    include_regex_hints: bool = True
    regex_hint_limit: int = Field(default=30, ge=1, le=120)


@app.get("/planner/state")
def planner_state() -> Dict[str, Any]:
    combined_course_key_count = len(_combined_course_key_index())
    return {
        "ok": True,
        "program_count": len(_PLANNER_PROGRAMS),
        "transfer_equivalency_count": len(_PLANNER_TRANSFER_RULES.get("equivalencies", [])),
        "sbctc_mandate_count": len(_PLANNER_TRANSFER_RULES.get("sbctc_mandates", [])),
        "institution_mandates": {
            k: len(v) for k, v in _PLANNER_TRANSFER_RULES.get("institution_mandates", {}).items()
        },
        "known_course_count": combined_course_key_count,
        "regex_corpus_record_count": len(_REGEX_CORPUS_RECORDS),
        "regex_corpus_path": str(PLANNER_REGEX_CORPUS_FILE),
        "live_catalog_course_count": len(_LIVE_COURSE_INDEX),
        "live_catalog_course_key_count": len(_LIVE_COURSE_KEY_INDEX),
        "live_catalog_history_course_count": len(_LIVE_HISTORY_COURSE_INDEX),
        "live_catalog_history_course_key_count": len(_LIVE_HISTORY_COURSE_KEY_INDEX),
        "live_catalog_generated_at": _LIVE_CATALOG_META.get("generated_at"),
        "live_catalog_term_codes": _LIVE_CATALOG_META.get("term_codes") or [],
        "live_catalog_search_params": _LIVE_CATALOG_META.get("search_params") or {},
        "live_catalog_delta": _LIVE_CATALOG_META.get("delta") or {},
        "last_transcript": {
            "file_name": _LAST_TRANSCRIPT.get("file_name"),
            "student_name": _LAST_TRANSCRIPT.get("student_name"),
            "student_slug": _LAST_TRANSCRIPT.get("student_slug"),
            "course_count": len(_LAST_TRANSCRIPT.get("courses") or []),
            "parsed_at": _LAST_TRANSCRIPT.get("parsed_at"),
        },
    }


@app.get("/planner/regex-corpus/status")
def planner_regex_corpus_status() -> Dict[str, Any]:
    pattern_counts: Dict[str, int] = {}
    for rec in _REGEX_CORPUS_RECORDS:
        p = str(rec.get("pattern") or "unknown")
        pattern_counts[p] = pattern_counts.get(p, 0) + 1
    return {
        "ok": True,
        "record_count": len(_REGEX_CORPUS_RECORDS),
        "path": str(PLANNER_REGEX_CORPUS_FILE),
        "pattern_counts": pattern_counts,
    }


@app.post("/planner/regex-corpus/reindex")
def planner_regex_corpus_reindex(req: Optional[RegexCorpusReindexRequest] = None) -> Dict[str, Any]:
    global _REGEX_CORPUS_RECORDS
    cfg = req or RegexCorpusReindexRequest()
    records: List[Dict[str, Any]] = []
    source_counts: Dict[str, int] = {}
    if cfg.include_program_index or cfg.include_baseline_catalog:
        planner_records = build_regex_corpus_records(
            _PLANNER_PROGRAMS if cfg.include_program_index else [],
            _combined_course_rows() if cfg.include_baseline_catalog else [],
        )
        records.extend(planner_records)
        source_counts["planner_records"] = len(planner_records)
    live_field_records: List[Dict[str, Any]] = []
    for field in _LIVE_CATALOG_META.get("search_fields") or []:
        if not isinstance(field, dict):
            continue
        fname = str(field.get("field_name") or "").strip()
        label = str(field.get("label") or "").strip()
        if not fname:
            continue
        live_field_records.append(
            {
                "id": f"live-search-field:{fname}",
                "source_id": "live_catalog:search_fields",
                "source_title": "ctcLink Search Fields",
                "pattern": "live_search_field",
                "match": fname,
                "line_no": 0,
                "text": f"{fname} {label} required={field.get('required')} use={field.get('use')}",
            }
        )
    if _LIVE_CATALOG_META.get("search_params"):
        live_field_records.append(
            {
                "id": "live-search-filters:active",
                "source_id": "live_catalog:search_filters",
                "source_title": "ctcLink Active Filters",
                "pattern": "live_search_filter",
                "match": "",
                "line_no": 0,
                "text": json.dumps(_LIVE_CATALOG_META.get("search_params") or {}, ensure_ascii=False),
            }
        )
    if live_field_records:
        records.extend(live_field_records)
        source_counts["live_catalog_fields"] = len(live_field_records)
    doc_stats: Dict[str, Any] = {
        "documents_seen": 0,
        "documents_indexed": 0,
        "documents_failed": 0,
        "ocr_documents": 0,
        "warnings": [],
    }
    doc_globs_used: List[str] = []
    if cfg.include_local_documents:
        doc_globs_used = cfg.document_globs or DEFAULT_REGEX_DOCUMENT_GLOBS
        doc_paths = _collect_regex_source_paths(doc_globs_used)
        source_counts["document_files"] = len(doc_paths)
        doc_records, doc_stats = build_regex_corpus_from_documents(doc_paths)
        records.extend(doc_records)
        source_counts["document_records"] = len(doc_records)

    dedup: Dict[str, Dict[str, Any]] = {}
    for rec in records:
        rid = str(rec.get("id") or json.dumps(rec, sort_keys=True))
        dedup[rid] = rec
    final_records = list(dedup.values())
    _REGEX_CORPUS_RECORDS = final_records
    _persist_regex_corpus(final_records)
    pattern_counts: Dict[str, int] = {}
    for rec in final_records:
        p = str(rec.get("pattern") or "unknown")
        pattern_counts[p] = pattern_counts.get(p, 0) + 1
    return {
        "ok": True,
        "record_count": len(final_records),
        "pattern_counts": pattern_counts,
        "source_counts": source_counts,
        "document_globs_used": doc_globs_used,
        "document_stats": doc_stats,
        "path": str(PLANNER_REGEX_CORPUS_FILE),
        "source_note": "Built using Factbook-style JSONL indexing and regex extraction from programs + baseline schedules.",
    }


@app.post("/planner/regex-corpus/search")
def planner_regex_corpus_search(req: RegexSearchRequest) -> Dict[str, Any]:
    q = (req.query or "").strip()
    if not q:
        return {"ok": True, "query": q, "count": 0, "results": []}
    results = regex_search(_REGEX_CORPUS_RECORDS, q, req.limit)
    return {"ok": True, "query": q, "count": len(results), "results": results}


@app.get("/planner/live-catalog/status")
def planner_live_catalog_status() -> Dict[str, Any]:
    return {
        "ok": True,
        "row_count": len(_LIVE_COURSE_INDEX),
        "course_key_count": len(_LIVE_COURSE_KEY_INDEX),
        "history_row_count": len(_LIVE_HISTORY_COURSE_INDEX),
        "history_course_key_count": len(_LIVE_HISTORY_COURSE_KEY_INDEX),
        "generated_at": _LIVE_CATALOG_META.get("generated_at"),
        "institution_code": _LIVE_CATALOG_META.get("institution_code"),
        "term_codes": _LIVE_CATALOG_META.get("term_codes") or [],
        "term_summaries": _LIVE_CATALOG_META.get("term_summaries") or [],
        "class_search_api_url": _LIVE_CATALOG_META.get("class_search_api_url"),
        "search_params": _LIVE_CATALOG_META.get("search_params") or {},
        "search_fields": _LIVE_CATALOG_META.get("search_fields") or [],
        "delta": _LIVE_CATALOG_META.get("delta") or {},
        "sync_profiles": _LIVE_CATALOG_META.get("sync_profiles") or [],
        "history_count": len(list(PLANNER_LIVE_HISTORY_DIR.glob("live_catalog_*.json"))),
        "path": str(PLANNER_LIVE_CATALOG_FILE),
    }


@app.get("/planner/live-catalog/history")
def planner_live_catalog_history(limit: int = 20) -> Dict[str, Any]:
    files = sorted(PLANNER_LIVE_HISTORY_DIR.glob("live_catalog_*.json"), reverse=True)
    out: List[Dict[str, Any]] = []
    safe_limit = max(1, min(int(limit), 100))
    for p in files[:safe_limit]:
        generated_at = None
        row_count = None
        term_codes: List[str] = []
        try:
            payload = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                generated_at = payload.get("generated_at")
                row_count = payload.get("row_count")
                term_codes = payload.get("term_codes") if isinstance(payload.get("term_codes"), list) else []
        except Exception:
            pass
        out.append(
            {
                "file_name": p.name,
                "path": str(p),
                "generated_at": generated_at,
                "row_count": row_count,
                "term_codes": term_codes,
            }
        )
    return {"ok": True, "count": len(out), "history_dir": str(PLANNER_LIVE_HISTORY_DIR), "snapshots": out}


@app.post("/planner/live-catalog/update")
def planner_live_catalog_update(req: LiveCatalogUpdateRequest) -> Dict[str, Any]:
    global _LIVE_COURSE_INDEX, _LIVE_CATALOG_META, _LIVE_COURSE_KEY_INDEX
    previous_rows = list(_LIVE_COURSE_INDEX)
    search_params = dict(req.search_params or {})
    if req.keyword.strip():
        search_params.setdefault("KEYWORD", req.keyword.strip())
    if req.subject_like.strip():
        search_params.setdefault("SUBJECT_LIKE", req.subject_like.strip())
    if req.catalog_nbr.strip():
        search_params.setdefault("CATALOG_NBR", req.catalog_nbr.strip())
    if req.instruction_mode.strip():
        search_params.setdefault("INSTRUCTION_MODE", req.instruction_mode.strip())
    if req.class_nbr.strip():
        search_params.setdefault("CLASS_NBR", req.class_nbr.strip())
    if req.crse_attr.strip():
        search_params.setdefault("CRSE_ATTR", req.crse_attr.strip())
    if req.crse_attr_value.strip():
        search_params.setdefault("CRSE_ATTR_VALUE", req.crse_attr_value.strip())
    if req.location.strip():
        search_params.setdefault("LOCATION", req.location.strip())
    if req.campus.strip():
        search_params.setdefault("CAMPUS", req.campus.strip())
    if req.session_code.strip():
        search_params.setdefault("SESSION_CODE", req.session_code.strip())
    try:
        snapshot = build_live_offerings_snapshot(
            institution_code=req.institution_code,
            class_search_main_url=req.class_search_main_url,
            term_codes=req.term_codes,
            term_count=req.term_count,
            enrl_stat=req.enrl_stat,
            subject=req.subject,
            acad_career=req.acad_career,
            search_params=search_params,
            timeout_seconds=req.timeout_seconds,
        )
    except Exception as e:
        raise HTTPException(502, f"ctcLink live catalog update failed: {e}")
    rows = snapshot.get("rows") if isinstance(snapshot.get("rows"), list) else []
    _LIVE_COURSE_INDEX = [r for r in rows if isinstance(r, dict)]
    _LIVE_COURSE_KEY_INDEX = build_course_key_index(_LIVE_COURSE_INDEX)
    delta = _compute_live_catalog_delta(previous_rows, _LIVE_COURSE_INDEX)
    snapshot["delta"] = delta
    snapshot["sync_profiles"] = snapshot.get("sync_profiles") if isinstance(snapshot.get("sync_profiles"), list) else []
    _LIVE_CATALOG_META = {
        "generated_at": snapshot.get("generated_at"),
        "institution_code": snapshot.get("institution_code"),
        "term_codes": snapshot.get("term_codes") if isinstance(snapshot.get("term_codes"), list) else [],
        "term_summaries": snapshot.get("term_summaries") if isinstance(snapshot.get("term_summaries"), list) else [],
        "row_count": len(_LIVE_COURSE_INDEX),
        "class_search_api_url": snapshot.get("class_search_api_url"),
        "search_params": snapshot.get("search_params") if isinstance(snapshot.get("search_params"), dict) else {},
        "search_fields": snapshot.get("search_fields") if isinstance(snapshot.get("search_fields"), list) else [],
        "delta": delta,
        "sync_profiles": snapshot.get("sync_profiles") if isinstance(snapshot.get("sync_profiles"), list) else [],
    }
    _persist_live_catalog(snapshot)
    _load_live_catalog_history()
    return {
        "ok": True,
        "row_count": len(_LIVE_COURSE_INDEX),
        "course_key_count": len(_LIVE_COURSE_KEY_INDEX),
        "generated_at": _LIVE_CATALOG_META.get("generated_at"),
        "institution_code": _LIVE_CATALOG_META.get("institution_code"),
        "term_codes": _LIVE_CATALOG_META.get("term_codes") or [],
        "term_summaries": _LIVE_CATALOG_META.get("term_summaries") or [],
        "class_search_api_url": _LIVE_CATALOG_META.get("class_search_api_url"),
        "search_params": _LIVE_CATALOG_META.get("search_params") or {},
        "search_fields": _LIVE_CATALOG_META.get("search_fields") or [],
        "delta": _LIVE_CATALOG_META.get("delta") or {},
        "sync_profiles": _LIVE_CATALOG_META.get("sync_profiles") or [],
        "path": str(PLANNER_LIVE_CATALOG_FILE),
    }


@app.post("/planner/live-catalog/sync")
def planner_live_catalog_sync(req: LiveCatalogSyncRequest) -> Dict[str, Any]:
    global _LIVE_COURSE_INDEX, _LIVE_CATALOG_META, _LIVE_COURSE_KEY_INDEX
    if not req.profiles:
        raise HTTPException(400, "Provide at least one sync profile.")

    previous_rows = list(_LIVE_COURSE_INDEX)
    merged_rows: List[Dict[str, Any]] = []
    merged_by_key: Dict[str, Dict[str, Any]] = {}
    merged_term_codes: List[str] = []
    merged_term_seen: set[str] = set()
    merged_term_summaries: List[Dict[str, Any]] = []
    merged_search_fields: Dict[str, Dict[str, Any]] = {}
    profile_results: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []
    class_search_api_url = None
    class_search_main_url = None
    institution_codes: set[str] = set()

    for profile in req.profiles:
        try:
            snapshot = build_live_offerings_snapshot(
                institution_code=profile.institution_code,
                class_search_main_url=profile.class_search_main_url,
                term_codes=profile.term_codes,
                term_count=profile.term_count,
                enrl_stat=profile.enrl_stat,
                subject=profile.subject,
                acad_career=profile.acad_career,
                search_params=profile.search_params,
                timeout_seconds=req.timeout_seconds,
            )
        except Exception as e:
            errors.append({"profile": profile.name, "error": str(e)})
            continue

        if class_search_api_url is None:
            class_search_api_url = snapshot.get("class_search_api_url")
        if class_search_main_url is None:
            class_search_main_url = snapshot.get("class_search_main_url")

        institution_codes.add(str(snapshot.get("institution_code") or profile.institution_code))
        for term_code in snapshot.get("term_codes") or []:
            t = str(term_code)
            if t not in merged_term_seen:
                merged_term_seen.add(t)
                merged_term_codes.append(t)
        for ts in snapshot.get("term_summaries") or []:
            if isinstance(ts, dict):
                merged_term_summaries.append(ts)
        for sf in snapshot.get("search_fields") or []:
            if isinstance(sf, dict):
                fname = str(sf.get("field_name") or "")
                if fname and fname not in merged_search_fields:
                    merged_search_fields[fname] = sf

        local_added = 0
        for row in snapshot.get("rows") or []:
            if not isinstance(row, dict):
                continue
            key = _live_row_key(row)
            if key in merged_by_key:
                continue
            merged_by_key[key] = row
            merged_rows.append(row)
            local_added += 1

        profile_results.append(
            {
                "name": profile.name,
                "institution_code": profile.institution_code,
                "row_count": local_added,
                "term_codes": snapshot.get("term_codes") or [],
                "search_params": snapshot.get("search_params") or {},
                "generated_at": snapshot.get("generated_at"),
            }
        )

    if not merged_rows and errors:
        raise HTTPException(502, f"All live sync profiles failed: {errors[0].get('error')}")

    snapshot_out = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "institution_code": ",".join(sorted(institution_codes)) if institution_codes else None,
        "class_search_main_url": class_search_main_url,
        "class_search_api_url": class_search_api_url,
        "enrl_stat": "mixed",
        "subject_filter": "",
        "search_params": {},
        "search_fields": list(merged_search_fields.values()),
        "term_codes": merged_term_codes,
        "term_summaries": merged_term_summaries,
        "row_count": len(merged_rows),
        "rows": merged_rows,
        "sync_profiles": profile_results,
        "sync_errors": errors,
    }
    _LIVE_COURSE_INDEX = merged_rows
    _LIVE_COURSE_KEY_INDEX = build_course_key_index(_LIVE_COURSE_INDEX)
    delta = _compute_live_catalog_delta(previous_rows, _LIVE_COURSE_INDEX)
    snapshot_out["delta"] = delta
    _LIVE_CATALOG_META = {
        "generated_at": snapshot_out.get("generated_at"),
        "institution_code": snapshot_out.get("institution_code"),
        "term_codes": snapshot_out.get("term_codes") if isinstance(snapshot_out.get("term_codes"), list) else [],
        "term_summaries": snapshot_out.get("term_summaries") if isinstance(snapshot_out.get("term_summaries"), list) else [],
        "row_count": len(_LIVE_COURSE_INDEX),
        "class_search_api_url": snapshot_out.get("class_search_api_url"),
        "search_params": {},
        "search_fields": snapshot_out.get("search_fields") if isinstance(snapshot_out.get("search_fields"), list) else [],
        "delta": delta,
        "sync_profiles": profile_results,
    }
    _persist_live_catalog(snapshot_out)
    _load_live_catalog_history()
    return {
        "ok": True,
        "generated_at": _LIVE_CATALOG_META.get("generated_at"),
        "row_count": len(_LIVE_COURSE_INDEX),
        "course_key_count": len(_LIVE_COURSE_KEY_INDEX),
        "term_codes": _LIVE_CATALOG_META.get("term_codes") or [],
        "delta": delta,
        "sync_profiles": profile_results,
        "sync_errors": errors,
        "path": str(PLANNER_LIVE_CATALOG_FILE),
    }


@app.post("/planner/transcript/import", response_model=TranscriptParseResult)
async def planner_import_transcript(file: UploadFile = File(...)) -> TranscriptParseResult:
    if not file.filename:
        raise HTTPException(400, "Please upload a transcript file.")
    suffix = Path(file.filename).suffix.lower()
    if suffix not in ALLOWED_TRANSCRIPT_SUFFIXES:
        allowed = ", ".join(sorted(ALLOWED_TRANSCRIPT_SUFFIXES))
        raise HTTPException(400, f"Unsupported transcript format: {suffix or 'unknown'}. Allowed: {allowed}")
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", file.filename)
    out_path = PLANNER_TRANSCRIPTS_DIR / f"transcript_{safe_name}"
    with out_path.open("wb") as f:
        f.write(await file.read())
    try:
        found, meta = _extract_transcript_courses_from_file(out_path)
    except RuntimeError as e:
        raise HTTPException(500, str(e))
    if not found:
        return TranscriptParseResult(
            ok=True,
            message="No transcript courses could be extracted from the uploaded file.",
            courses=[],
            unique_course_count=0,
            item_number_count=0,
            transcript_path=str(out_path),
            ocr_used=bool(meta.get("ocr_used")),
            extract_method=meta.get("method"),
            ocr_warnings=list(meta.get("warnings") or []),
        )
    # Detect student name
    _det_name2: Optional[str] = None
    try:
        _raw2 = out_path.read_text(encoding="utf-8", errors="ignore") if out_path.suffix.lower() != ".pdf" else None
        if _raw2 is None:
            _raw2, _ = extract_text_with_ocr_fallback(out_path)
        _det_name2 = extract_student_name(_raw2 or "")
        if not _det_name2:
            _det_name2 = Path(file.filename).stem.replace("_", " ").replace("-", " ").title()
    except Exception:
        pass

    _LAST_TRANSCRIPT["file_name"] = safe_name
    _LAST_TRANSCRIPT["student_name"] = _det_name2
    _LAST_TRANSCRIPT["student_slug"] = student_slug(_det_name2 or "unknown")
    _LAST_TRANSCRIPT["courses"] = found
    _LAST_TRANSCRIPT["parsed_at"] = datetime.utcnow().isoformat() + "Z"
    _LAST_TRANSCRIPT["provision_summary"] = build_provision_summary(found)
    _persist_transcript_session(_LAST_TRANSCRIPT, meta)
    return TranscriptParseResult(
        ok=True,
        message=f"Transcript indexed. Found {len(found)} normalized courses.",
        courses=found,
        unique_course_count=len(found),
        item_number_count=sum(1 for c in found if c.get("item_number")),
        transcript_path=str(out_path),
        ocr_used=bool(meta.get("ocr_used")),
        extract_method=meta.get("method"),
        ocr_warnings=list(meta.get("warnings") or []),
    )


@app.get("/planner/transcript/session")
def planner_transcript_session() -> Dict[str, Any]:
    """Return the most recently parsed transcript session with full provision data."""
    if _LAST_TRANSCRIPT.get("courses"):
        return {
            "ok": True,
            "source": "memory",
            "file_name": _LAST_TRANSCRIPT.get("file_name"),
            "student_name": _LAST_TRANSCRIPT.get("student_name"),
            "student_slug": _LAST_TRANSCRIPT.get("student_slug"),
            "parsed_at": _LAST_TRANSCRIPT.get("parsed_at"),
            "courses": _LAST_TRANSCRIPT["courses"],
            "provision_summary": _LAST_TRANSCRIPT.get("provision_summary") or {},
            "unique_course_count": len(_LAST_TRANSCRIPT["courses"]),
        }
    session = _load_session_if_present()
    if session.get("courses"):
        _LAST_TRANSCRIPT["file_name"] = session.get("file_name")
        _LAST_TRANSCRIPT["student_name"] = session.get("student_name")
        _LAST_TRANSCRIPT["student_slug"] = session.get("student_slug")
        _LAST_TRANSCRIPT["courses"] = session["courses"]
        _LAST_TRANSCRIPT["parsed_at"] = session.get("parsed_at")
        _LAST_TRANSCRIPT["provision_summary"] = session.get("provision_summary") or {}
        return {
            "ok": True,
            "source": "disk",
            "file_name": session.get("file_name"),
            "student_name": session.get("student_name"),
            "student_slug": session.get("student_slug"),
            "parsed_at": session.get("parsed_at"),
            "courses": session["courses"],
            "provision_summary": session.get("provision_summary") or {},
            "unique_course_count": len(session["courses"]),
        }
    return {"ok": False, "courses": [], "unique_course_count": 0, "message": "No transcript session found."}


# ─── Student Sessions Repository ──────────────────────────────────────────────

@app.get("/planner/sessions")
def planner_list_sessions() -> Dict[str, Any]:
    """List all saved student transcript sessions."""
    sessions = _list_student_sessions()
    return {"ok": True, "count": len(sessions), "sessions": sessions}


@app.get("/planner/sessions/{slug}")
def planner_get_session(slug: str) -> Dict[str, Any]:
    """Return full data for a specific student session."""
    session_file = PLANNER_STUDENT_SESSIONS_DIR / slug / "session.json"
    if not session_file.exists():
        raise HTTPException(404, f"No session found for '{slug}'.")
    try:
        data = json.loads(session_file.read_text(encoding="utf-8"))
        data["ok"] = True
        return data
    except Exception as e:
        raise HTTPException(500, f"Could not read session: {e}")


@app.post("/planner/sessions/{slug}/load")
def planner_load_session(slug: str) -> Dict[str, Any]:
    """Load a student session into active memory (makes it the current session for chat/planner)."""
    session_file = PLANNER_STUDENT_SESSIONS_DIR / slug / "session.json"
    if not session_file.exists():
        raise HTTPException(404, f"No session found for '{slug}'.")
    try:
        data = json.loads(session_file.read_text(encoding="utf-8"))
    except Exception as e:
        raise HTTPException(500, f"Could not read session: {e}")
    _LAST_TRANSCRIPT["file_name"] = data.get("file_name")
    _LAST_TRANSCRIPT["student_name"] = data.get("student_name")
    _LAST_TRANSCRIPT["student_slug"] = data.get("student_slug") or slug
    _LAST_TRANSCRIPT["courses"] = data.get("courses") or []
    _LAST_TRANSCRIPT["parsed_at"] = data.get("parsed_at")
    _LAST_TRANSCRIPT["provision_summary"] = data.get("provision_summary") or {}
    # Also write to session_current so it survives a server restart
    try:
        PLANNER_SESSION_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception:
        pass
    return {
        "ok": True,
        "loaded": slug,
        "student_name": data.get("student_name"),
        "course_count": len(data.get("courses") or []),
    }


class SessionPinRequest(BaseModel):
    pinned: bool = True
    notes: str = ""


@app.post("/planner/sessions/{slug}/pin")
def planner_pin_session(slug: str, req: SessionPinRequest) -> Dict[str, Any]:
    """Pin or unpin a student session for demo/stakeholder use."""
    session_file = PLANNER_STUDENT_SESSIONS_DIR / slug / "session.json"
    if not session_file.exists():
        raise HTTPException(404, f"No session found for '{slug}'.")
    try:
        data = json.loads(session_file.read_text(encoding="utf-8"))
        data["pinned"] = req.pinned
        if req.notes:
            data["notes"] = req.notes
        session_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception as e:
        raise HTTPException(500, f"Could not update session: {e}")
    return {"ok": True, "slug": slug, "pinned": req.pinned}


class SessionRenameRequest(BaseModel):
    student_name: str


@app.post("/planner/sessions/{slug}/rename")
def planner_rename_session(slug: str, req: SessionRenameRequest) -> Dict[str, Any]:
    """Correct the detected student name on a session."""
    if not req.student_name.strip():
        raise HTTPException(400, "student_name must not be empty.")
    session_file = PLANNER_STUDENT_SESSIONS_DIR / slug / "session.json"
    if not session_file.exists():
        raise HTTPException(404, f"No session found for '{slug}'.")
    new_slug = student_slug(req.student_name)
    try:
        data = json.loads(session_file.read_text(encoding="utf-8"))
        data["student_name"] = req.student_name.strip()
        data["student_slug"] = new_slug
        # Move to new slug directory if name changed
        new_dir = PLANNER_STUDENT_SESSIONS_DIR / new_slug
        new_dir.mkdir(parents=True, exist_ok=True)
        new_file = new_dir / "session.json"
        new_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
        # Remove old dir only if slug changed and old is empty
        if new_slug != slug:
            try:
                session_file.unlink()
                old_dir = PLANNER_STUDENT_SESSIONS_DIR / slug
                if not any(old_dir.iterdir()):
                    old_dir.rmdir()
            except Exception:
                pass
    except Exception as e:
        raise HTTPException(500, f"Could not rename session: {e}")
    return {"ok": True, "old_slug": slug, "new_slug": new_slug, "student_name": req.student_name.strip()}


@app.delete("/planner/sessions/{slug}")
def planner_delete_session(slug: str) -> Dict[str, Any]:
    """Delete a student session permanently."""
    session_file = PLANNER_STUDENT_SESSIONS_DIR / slug / "session.json"
    if not session_file.exists():
        raise HTTPException(404, f"No session found for '{slug}'.")
    try:
        session_file.unlink()
        slug_dir = PLANNER_STUDENT_SESSIONS_DIR / slug
        if not any(slug_dir.iterdir()):
            slug_dir.rmdir()
    except Exception as e:
        raise HTTPException(500, f"Could not delete session: {e}")
    return {"ok": True, "deleted": slug}


@app.get("/planner/programs")
def planner_programs() -> Dict[str, Any]:
    summaries = []
    for p in _PLANNER_PROGRAMS:
        summaries.append(
            {
                "program_id": p.get("program_id"),
                "program_name": p.get("program_name"),
                "award": p.get("award"),
                "institution": p.get("institution"),
                "required_course_count": len(p.get("required_courses") or []),
                "elective_group_count": len(p.get("elective_groups") or []),
                "total_credits_required": p.get("total_credits_required"),
                "source": p.get("source"),
            }
        )
    return {"count": len(summaries), "programs": summaries}


@app.post("/planner/programs/import/json")
def planner_import_programs_json(payload: ProgramImportJSONBody) -> Dict[str, Any]:
    incoming = [normalize_program_doc(x) for x in payload.programs if isinstance(x, dict)]
    if not incoming:
        raise HTTPException(400, "No valid programs provided.")
    by_id = {p.get("program_id"): p for p in (_PLANNER_PROGRAMS if not payload.replace else [])}
    for p in incoming:
        by_id[p.get("program_id")] = p
    _PLANNER_PROGRAMS.clear()
    _PLANNER_PROGRAMS.extend(by_id.values())
    _persist_programs()
    return {"ok": True, "replace": payload.replace, "imported": len(incoming), "total_programs": len(_PLANNER_PROGRAMS)}


@app.post("/planner/programs/import/pdf")
async def planner_import_programs_pdf(files: List[UploadFile] = File(...)) -> Dict[str, Any]:
    if not files:
        raise HTTPException(400, "Please upload at least one PDF.")
    imported: List[Dict[str, Any]] = []
    by_id = {p.get("program_id"): p for p in _PLANNER_PROGRAMS}
    for file in files:
        if not file.filename or not file.filename.lower().endswith(".pdf"):
            continue
        safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", file.filename)
        out_path = PLANNER_PROGRAM_PDFS_DIR / safe_name
        with out_path.open("wb") as f:
            f.write(await file.read())
        try:
            text, _meta = extract_text_with_ocr_fallback(out_path)
        except RuntimeError:
            continue
        if not text.strip():
            continue
        doc = normalize_program_from_pdf(text, source_pdf=str(out_path), fallback_name=Path(file.filename).stem)
        by_id[doc["program_id"]] = doc
        imported.append(
            {
                "program_id": doc.get("program_id"),
                "program_name": doc.get("program_name"),
                "required_course_count": len(doc.get("required_courses") or []),
                "source": doc.get("source"),
            }
        )
    _PLANNER_PROGRAMS.clear()
    _PLANNER_PROGRAMS.extend(by_id.values())
    _persist_programs()
    return {"ok": True, "imported": len(imported), "total_programs": len(_PLANNER_PROGRAMS), "programs": imported}


@app.get("/planner/transfer-rules")
def planner_transfer_rules() -> Dict[str, Any]:
    return {
        "ok": True,
        "equivalencies": _PLANNER_TRANSFER_RULES.get("equivalencies", []),
        "sbctc_mandates": _PLANNER_TRANSFER_RULES.get("sbctc_mandates", []),
        "institution_mandates": _PLANNER_TRANSFER_RULES.get("institution_mandates", {}),
    }


@app.post("/planner/policy/qa")
def planner_policy_qa(req: Optional[PolicyQARequest] = None) -> Dict[str, Any]:
    cfg = req or PolicyQARequest()
    return _run_policy_qa(
        institution=cfg.institution,
        include_all_institutions=cfg.include_all_institutions,
        include_regex_hints=cfg.include_regex_hints,
        regex_hint_limit=cfg.regex_hint_limit,
    )


@app.post("/planner/transfer-rules/import/json")
def planner_import_transfer_rules(payload: TransferRulesImportBody) -> Dict[str, Any]:
    normalized = normalize_transfer_rules(payload.rules)
    if payload.replace:
        _PLANNER_TRANSFER_RULES.clear()
        _PLANNER_TRANSFER_RULES.update(normalized)
    else:
        _PLANNER_TRANSFER_RULES.setdefault("equivalencies", [])
        _PLANNER_TRANSFER_RULES.setdefault("sbctc_mandates", [])
        _PLANNER_TRANSFER_RULES.setdefault("institution_mandates", {})
        _PLANNER_TRANSFER_RULES["equivalencies"].extend(normalized.get("equivalencies", []))
        _PLANNER_TRANSFER_RULES["sbctc_mandates"].extend(normalized.get("sbctc_mandates", []))
        inst_out = _PLANNER_TRANSFER_RULES.get("institution_mandates", {})
        for inst, rules in normalized.get("institution_mandates", {}).items():
            inst_out.setdefault(inst, [])
            inst_out[inst].extend(rules)
        _PLANNER_TRANSFER_RULES["institution_mandates"] = inst_out

    eq_seen = {}
    for eq in _PLANNER_TRANSFER_RULES.get("equivalencies", []):
        key = eq.get("id") or f"{eq.get('from_key')}->{eq.get('to_key')}"
        eq_seen[key] = eq
    _PLANNER_TRANSFER_RULES["equivalencies"] = list(eq_seen.values())

    sbctc_seen = {}
    for rule in _PLANNER_TRANSFER_RULES.get("sbctc_mandates", []):
        key = rule.get("id") or json.dumps(rule, sort_keys=True)
        sbctc_seen[key] = rule
    _PLANNER_TRANSFER_RULES["sbctc_mandates"] = list(sbctc_seen.values())

    for inst, rules in list(_PLANNER_TRANSFER_RULES.get("institution_mandates", {}).items()):
        seen = {}
        for rule in rules:
            key = rule.get("id") or json.dumps(rule, sort_keys=True)
            seen[key] = rule
        _PLANNER_TRANSFER_RULES["institution_mandates"][inst] = list(seen.values())

    _persist_transfer_rules()
    return {
        "ok": True,
        "replace": payload.replace,
        "equivalencies": len(_PLANNER_TRANSFER_RULES.get("equivalencies", [])),
        "sbctc_mandates": len(_PLANNER_TRANSFER_RULES.get("sbctc_mandates", [])),
        "institution_mandates": {k: len(v) for k, v in _PLANNER_TRANSFER_RULES.get("institution_mandates", {}).items()},
    }


@app.post("/planner/suggest-programs")
def planner_suggest_programs(req: ProgramSuggestRequest) -> Dict[str, Any]:
    transcript_courses = req.transcript_courses if req.transcript_courses is not None else _LAST_TRANSCRIPT.get("courses", [])
    normalized_transcript = normalize_transcript_courses(transcript_courses)
    suggestions = suggest_programs(normalized_transcript, _PLANNER_PROGRAMS, _PLANNER_TRANSFER_RULES, req.limit)
    return {
        "ok": True,
        "transcript_course_count": len(normalized_transcript),
        "program_count": len(_PLANNER_PROGRAMS),
        "suggestions": suggestions,
    }


@app.post("/planner/course-lifecycle")
def planner_course_lifecycle(req: CourseLifecycleRequest) -> Dict[str, Any]:
    transcript_courses = req.transcript_courses if req.transcript_courses is not None else _LAST_TRANSCRIPT.get("courses", [])
    normalized_transcript = normalize_transcript_courses(transcript_courses)
    if not normalized_transcript:
        raise HTTPException(400, "No transcript courses available. Import transcript file first or provide transcript_courses.")
    catalog_by_key = _combined_course_key_index()
    lifecycle = _analyze_transcript_course_lifecycle(
        normalized_transcript=normalized_transcript,
        transfer_rules=_PLANNER_TRANSFER_RULES,
        catalog_by_key=catalog_by_key,
    )
    alerts = lifecycle.get("alerts") if isinstance(lifecycle.get("alerts"), list) else []
    total_alert_count = len(alerts)
    lifecycle["alerts"] = alerts[: req.limit]
    lifecycle["returned_alert_count"] = len(lifecycle["alerts"])
    lifecycle["total_alert_count"] = total_alert_count
    return {"ok": True, **lifecycle}


@app.post("/planner/predict-pathways")
def planner_predict_pathways(req: PathwayPredictRequest) -> Dict[str, Any]:
    transcript_courses = req.transcript_courses if req.transcript_courses is not None else _LAST_TRANSCRIPT.get("courses", [])
    normalized_transcript = normalize_transcript_courses(transcript_courses)
    if not normalized_transcript:
        raise HTTPException(400, "No transcript courses available. Import transcript file first or provide transcript_courses.")
    if not _PLANNER_PROGRAMS:
        raise HTTPException(400, "No programs indexed. Import program PDFs/JSON first.")

    suggestions = suggest_programs(
        normalized_transcript,
        _PLANNER_PROGRAMS,
        _PLANNER_TRANSFER_RULES,
        req.candidate_limit,
    )
    if not suggestions:
        return {
            "ok": True,
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "count": 0,
            "predictions": [],
        }

    catalog_by_key = _combined_course_key_index()
    predictions: List[Dict[str, Any]] = []
    pace_mode = str(req.pace_mode or "part_time").strip() or "part_time"

    for suggestion in suggestions:
        program = _find_program(str(suggestion.get("program_id") or ""), None)
        if not program:
            continue
        plan_data = _build_program_plan_data(
            program=program,
            institution=req.institution,
            begin_term=req.begin_term,
            max_credits_per_term=req.max_credits_per_term,
            horizon_terms=req.horizon_terms,
            normalized_transcript=normalized_transcript,
            transfer_rules=_PLANNER_TRANSFER_RULES,
            catalog_by_key=catalog_by_key,
        )

        remaining_credits = float(plan_data["remaining_required_credits"])
        pace_scenarios = estimate_pace_scenarios(
            remaining_credits=remaining_credits,
            tuition_per_credit=req.tuition_per_credit,
            fees_per_term=req.fees_per_term,
            books_per_term=req.books_per_term,
        )
        selected_scenario = pace_scenarios.get(pace_mode) or pace_scenarios.get("part_time") or {}
        estimated_terms = int(selected_scenario.get("estimated_terms") or 0)
        estimated_total_cost = selected_scenario.get("estimated_tuition_total")
        if estimated_total_cost is None:
            estimated_total_cost = selected_scenario.get("estimated_fees_books_total")

        mandate_alerts = [m for m in plan_data["mandates"] if not bool(m.get("ok"))]
        hard_blocks = [m for m in plan_data["mandates"] if bool(m.get("hard_block"))]
        approval_flags = [m for m in plan_data["mandates"] if bool(m.get("approval_required"))]
        completion_confidence = "high"
        if remaining_credits > 45 or mandate_alerts:
            completion_confidence = "medium"
        if remaining_credits > 80 or len(mandate_alerts) > 2:
            completion_confidence = "low"
        if plan_data["decision_status"] == "approval_required" and completion_confidence == "high":
            completion_confidence = "medium"
        if plan_data["decision_status"] == "blocked":
            completion_confidence = "low"

        predictions.append(
            {
                "program_id": program.get("program_id"),
                "program_name": program.get("program_name"),
                "award": program.get("award"),
                "match_ratio": suggestion.get("match_ratio"),
                "required_total": len(plan_data["required_courses"]),
                "required_satisfied": len(plan_data["satisfied_required"]),
                "required_remaining": len(plan_data["missing_required"]),
                "remaining_required_credits_estimate": remaining_credits,
                "estimated_terms_to_completion": estimated_terms,
                "estimated_total_cost": estimated_total_cost,
                "completion_confidence": completion_confidence,
                "mandate_alert_count": len(mandate_alerts),
                "hard_block_count": len(hard_blocks),
                "approval_required_count": len(approval_flags),
                "decision_status": plan_data["decision_status"],
                "program_currency_status": plan_data["program_currency"].get("status"),
                "program_current_coverage_ratio": plan_data["program_currency"].get("coverage_ratio"),
                "program_currency_note": plan_data["program_currency"].get("note"),
                "compatible_count": len(plan_data["compatible_courses"]),
                "incompatible_count": len(plan_data["incompatible_courses"]),
                "unmapped_count": len(plan_data["unmapped_courses"]),
                "missing_course_preview": [
                    str(x.get("course_code") or x.get("course_key") or "")
                    for x in plan_data["missing_required"][:8]
                ],
                "quarter_plan_preview": plan_data["pathway"][:4],
                "remaining_after_horizon_count": len(plan_data["remaining_after_horizon"]),
                "pace_scenarios": pace_scenarios,
            }
        )

    predictions.sort(
        key=lambda x: (
            int(x.get("estimated_terms_to_completion") or 9999),
            int(x.get("required_remaining") or 9999),
            -float(x.get("match_ratio") or 0.0),
            str(x.get("program_name") or ""),
        )
    )
    return {
        "ok": True,
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "institution": req.institution,
        "begin_term": req.begin_term,
        "pace_mode": pace_mode,
        "max_credits_per_term": req.max_credits_per_term,
        "count": len(predictions),
        "predictions": predictions,
    }


@app.post("/planner/plan")
def planner_plan(req: PlanRequest) -> Dict[str, Any]:
    program = _find_program(req.target_program_id, req.target_program_name)
    if not program:
        raise HTTPException(404, "Target program not found. Import programs first or provide a valid program_id.")
    transcript_courses = req.transcript_courses if req.transcript_courses is not None else _LAST_TRANSCRIPT.get("courses", [])
    normalized_transcript = normalize_transcript_courses(transcript_courses)
    if not normalized_transcript:
        raise HTTPException(400, "No transcript courses available. Import transcript file first or provide transcript_courses.")
    catalog_by_key = _combined_course_key_index()
    plan_data = _build_program_plan_data(
        program=program,
        institution=req.institution,
        begin_term=req.begin_term,
        max_credits_per_term=req.max_credits_per_term,
        horizon_terms=req.horizon_terms,
        normalized_transcript=normalized_transcript,
        transfer_rules=_PLANNER_TRANSFER_RULES,
        catalog_by_key=catalog_by_key,
    )

    missing_required = plan_data["missing_required"]
    required_courses = plan_data["required_courses"]
    satisfied_required = plan_data["satisfied_required"]
    elective_results = plan_data["elective_results"]
    mandates = plan_data["mandates"]
    hard_block_flags = plan_data["hard_block_flags"]
    approval_required_flags = plan_data["approval_required_flags"]
    pathway = plan_data["pathway"]
    remaining = plan_data["remaining_after_horizon"]
    remaining_credits = float(plan_data["remaining_required_credits"])

    pace_scenarios = (
        estimate_pace_scenarios(
            remaining_credits=remaining_credits,
            tuition_per_credit=req.tuition_per_credit,
            fees_per_term=req.fees_per_term,
            books_per_term=req.books_per_term,
        )
        if req.include_pace_scenarios
        else {}
    )
    regex_hint_query = " ".join(
        [str(req.institution)] + [str(x.get("course_code") or "") for x in missing_required[:6]]
    ).strip()
    regex_hints = regex_search(_REGEX_CORPUS_RECORDS, regex_hint_query, 20) if regex_hint_query else []
    course_lifecycle = _analyze_transcript_course_lifecycle(
        normalized_transcript=normalized_transcript,
        transfer_rules=_PLANNER_TRANSFER_RULES,
        catalog_by_key=catalog_by_key,
    )

    career_suggestions = suggest_programs(normalized_transcript, _PLANNER_PROGRAMS, _PLANNER_TRANSFER_RULES, 5)
    return {
        "ok": True,
        "program": {
            "program_id": program.get("program_id"),
            "program_name": program.get("program_name"),
            "award": program.get("award"),
            "institution": program.get("institution"),
            "total_credits_required": program.get("total_credits_required"),
        },
        "transcript_summary": {
            "course_count": len(normalized_transcript),
            "total_credits": plan_data["total_transcript_credits"],
            "item_number_count": sum(1 for x in normalized_transcript if x.get("item_number")),
        },
        "pace": {"mode": req.pace_mode, "max_credits_per_term": req.max_credits_per_term, "horizon_terms": req.horizon_terms},
        "cost_inputs": {
            "tuition_per_credit": req.tuition_per_credit,
            "fees_per_term": req.fees_per_term,
            "books_per_term": req.books_per_term,
        },
        "progress": {
            "required_total": len(required_courses),
            "required_satisfied": len(satisfied_required),
            "required_remaining": len(missing_required),
            "remaining_required_credits_estimate": remaining_credits,
            "remaining_after_horizon_credits_estimate": plan_data["remaining_after_horizon_credits"],
            "elective_groups": elective_results,
            "mandates": mandates,
            "hard_block_flags": hard_block_flags,
            "approval_required_flags": approval_required_flags,
            "program_currency": plan_data["program_currency"],
        },
        "decision": {
            "status": plan_data["decision_status"],
            "can_proceed_without_override": plan_data["decision_status"] == "ok",
            "requires_admin_approval": len(approval_required_flags) > 0,
            "hard_block_count": len(hard_block_flags),
            "approval_required_count": len(approval_required_flags),
            "legacy_course_alert_count": course_lifecycle["summary"].get("not_currently_offered_count", 0),
            "catalog_unknown_course_count": course_lifecycle["summary"].get("not_found_in_catalogs_count", 0),
        },
        "compatibility": {
            "compatible_count": len(plan_data["compatible_courses"]),
            "incompatible_count": len(plan_data["incompatible_courses"]),
            "unmapped_count": len(plan_data["unmapped_courses"]),
            "compatible_courses": plan_data["compatible_courses"][:80],
            "incompatible_courses": plan_data["incompatible_courses"][:80],
            "unmapped_courses": plan_data["unmapped_courses"][:80],
        },
        "pathway": pathway,
        "remaining_after_horizon": remaining,
        "pace_scenarios": pace_scenarios,
        "regex_hints": regex_hints,
        "career_path_suggestions": career_suggestions,
        "course_lifecycle": course_lifecycle,
        "course_matching_notes": {
            "normalization": "Matches use normalized course keys and transfer equivalency map.",
            "ampersand_support": "Courses like ENGL&101, ENGL 101, and ENGL& 101 normalize to the same key for matching.",
            "item_number_support": "Transcript class/item numbers are captured when present and included in mandate checks.",
        },
    }


# -----------------------------
# Ollama chat proxy
# -----------------------------
class ChatRequest(BaseModel):
    prompt: Optional[str] = None
    message: Optional[str] = None
    model: Optional[str] = None
    use_regex_context: bool = True
    regex_context_limit: int = Field(default=8, ge=0, le=40)


class ChatReply(BaseModel):
    ok: bool
    reply: str
    error: Optional[str] = None
    model: Optional[str] = None


OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
OLLAMA_MODEL_DEFAULT = os.environ.get("OLLAMA_MODEL", "qwen2.5:7b-instruct")


@app.get("/ollama/health")
def ollama_health() -> Dict[str, Any]:
    try:
        r = requests.get(f"{OLLAMA_HOST}/api/tags", timeout=5)
        r.raise_for_status()
        return {"ok": True, "host": OLLAMA_HOST, "tags": r.json()}
    except Exception as e:
        return {"ok": False, "host": OLLAMA_HOST, "error": str(e)}


@app.get("/ollama/models")
def ollama_models() -> Dict[str, Any]:
    """Return clean list of available Ollama model names, sorted by size (largest first)."""
    try:
        r = requests.get(f"{OLLAMA_HOST}/api/tags", timeout=5)
        r.raise_for_status()
        raw = r.json().get("models") or []
        models = sorted(
            [{"name": m["name"], "size": m.get("size", 0)} for m in raw if m.get("name")],
            key=lambda x: x["size"],
            reverse=True,
        )
        return {"ok": True, "models": [m["name"] for m in models], "count": len(models)}
    except Exception as e:
        return {"ok": False, "models": [OLLAMA_MODEL_DEFAULT], "count": 1, "error": str(e)}


_RTC_ADVISOR_SYSTEM_PROMPT = """You are an RTC (Renton Technical College) academic advisor assistant embedded in the student advising portal.

RTC Transfer & Advising Policy Summary:
- Washington state community/technical college courses with the & designation (e.g., ENGL&101) are part of the Common Course Numbering system and transfer between WA state schools automatically.
- Students must earn a C or better (2.0 GPA) for a course to count toward degree requirements.
- Running Start credits taken at an accredited WA CTC count the same as regular credits.
- Developmental/pre-college courses (numbered below 100) do not count toward degree credit hours.
- Transfer credits from out-of-state or international institutions require an official transcript evaluation by the RTC Registrar.
- Courses taken more than 10 years ago in technical fields may need advisor review for currency.
- All credit evaluations are PROVISIONAL until an official degree audit is completed by a credentialed advisor.
- Students should schedule a degree audit appointment at: schedule.rtc.edu
- For questions about specific course equivalencies, contact: advising@rtc.edu

When answering questions:
1. Reference RTC programs, transfer policies, and credit rules specifically.
2. Always remind students that your assessment is provisional and they should confirm with an official advisor.
3. If a student's transcript data is provided, refer to it specifically when answering eligibility questions.
4. Recommend the student's next concrete action step (schedule audit, bring documents, contact registrar, etc.).
"""


@app.post("/chat", response_model=ChatReply)
def chat(req: ChatRequest) -> ChatReply:
    prompt = (req.prompt or req.message or "").strip()
    if not prompt:
        raise HTTPException(400, "Prompt is required.")

    model = (req.model or "").strip() or OLLAMA_MODEL_DEFAULT

    # ── Build context layers ───────────────────────────────────────────────
    context_blocks: List[str] = [_RTC_ADVISOR_SYSTEM_PROMPT]

    # Transcript context — auto-inject if a session exists
    transcript_courses = _LAST_TRANSCRIPT.get("courses") or []
    if not transcript_courses:
        session = _load_session_if_present()
        transcript_courses = session.get("courses") or []
    if transcript_courses:
        context_blocks.append(build_transcript_llm_context(transcript_courses))

    # Regex corpus hints
    if req.use_regex_context and _REGEX_CORPUS_RECORDS:
        hits = regex_search(_REGEX_CORPUS_RECORDS, prompt, req.regex_context_limit)
        if hits:
            hint_lines = []
            for hit in hits:
                source = str(hit.get("source_title") or hit.get("source_id") or "source")
                pattern = str(hit.get("pattern") or "hint")
                snippet = str(hit.get("text") or hit.get("match") or "").replace("\n", " ").strip()
                if len(snippet) > 220:
                    snippet = snippet[:220].rstrip() + "..."
                hint_lines.append(f"- [{pattern}] {source}: {snippet}")
            context_blocks.append(
                "[RTC Document Corpus Hints]\n" + "\n".join(hint_lines[: req.regex_context_limit])
            )

    full_prompt = "\n\n".join(context_blocks) + "\n\n[Student Question]\n" + prompt

    try:
        r = requests.post(
            f"{OLLAMA_HOST}/api/generate",
            json={"model": model, "prompt": full_prompt, "stream": False},
            timeout=120,
        )
        r.raise_for_status()
        data = r.json()
        return ChatReply(ok=True, reply=data.get("response", ""), model=model)
    except requests.RequestException as e:
        return ChatReply(ok=False, reply="", error=f"Ollama call failed: {e}", model=model)


_UI_ROUTE_BLOCKLIST = {"health", "baseline", "courses", "offerings", "imports", "planner", "ollama", "chat"}

if ADVISOR_UI_DIST_DIR.exists():
    assets_dir = ADVISOR_UI_DIST_DIR / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="advisor_ui_assets")

    @app.get("/", include_in_schema=False)
    def ui_index() -> FileResponse:
        return FileResponse(ADVISOR_UI_DIST_DIR / "index.html")

    @app.get("/{full_path:path}", include_in_schema=False)
    def ui_spa(full_path: str) -> FileResponse:
        first = full_path.split("/", 1)[0].strip().lower()
        if first in _UI_ROUTE_BLOCKLIST:
            raise HTTPException(status_code=404, detail="Not found")

        candidate = ADVISOR_UI_DIST_DIR / full_path
        if candidate.exists() and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(ADVISOR_UI_DIST_DIR / "index.html")
