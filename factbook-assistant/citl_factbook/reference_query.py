from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import reference_db as db
from .reference_config import load_reference_config
from .reference_ingest import ingest_corpus


def _norm_key(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (text or "").lower())


@dataclass
class QueryPlan:
    question: str
    entities: List[str]
    intent: str
    canonical_field: Optional[str]
    section_hint: Optional[str]


def _canonical_field_from_question(question: str, cfg: Dict[str, Any]) -> Optional[str]:
    q = (question or "").lower()
    cfields = cfg.get("canonical_fields")
    if not isinstance(cfields, dict):
        return None

    pairs: List[Tuple[str, str]] = []
    for canonical, spec_any in cfields.items():
        spec = spec_any if isinstance(spec_any, dict) else {}
        aliases = [str(canonical)]
        aliases.extend(str(x) for x in (spec.get("aliases") or []))
        aliases.extend(str(x) for x in (spec.get("labels") or []))
        for a in aliases:
            al = a.strip().lower()
            if al:
                pairs.append((al, str(canonical)))
    pairs.sort(key=lambda p: len(p[0]), reverse=True)
    for alias, canonical in pairs:
        if alias in q:
            return canonical
    return None


def _section_hint_for_field(field: Optional[str], cfg: Dict[str, Any]) -> Optional[str]:
    if not field:
        return None
    cfields = cfg.get("canonical_fields")
    if not isinstance(cfields, dict):
        return None
    spec_any = cfields.get(field)
    if not isinstance(spec_any, dict):
        return None
    sec = str(spec_any.get("section") or "").title().strip()
    return sec or None


def _detect_entities(question: str, alias_map: Dict[str, str]) -> List[str]:
    q = (question or "").strip()
    ql = q.lower()
    found: List[str] = []
    seen = set()

    items = sorted([(a, e) for a, e in alias_map.items() if a and e], key=lambda p: len(p[0]), reverse=True)
    for alias, entity in items:
        pat = rf"(?<![A-Za-z0-9]){re.escape(alias.lower())}(?![A-Za-z0-9])"
        if re.search(pat, ql):
            if entity not in seen:
                seen.add(entity)
                found.append(entity)
    if found:
        return found

    qn = _norm_key(q)
    for alias, entity in items:
        an = _norm_key(alias)
        if len(an) < 4:
            continue
        if an in qn and entity not in seen:
            seen.add(entity)
            found.append(entity)
    return found


def _intent(question: str, entities: List[str], canonical_field: Optional[str]) -> str:
    q = (question or "").lower()
    if len(entities) >= 2 or re.search(r"\b(compare|vs\.?|versus|higher|lower|difference)\b", q):
        return "COMPARISON"
    if canonical_field:
        return "FACT_LOOKUP"
    if entities:
        return "EXPLANATION"
    return "UNKNOWN"


def _plan(question: str, alias_map: Dict[str, str], cfg: Dict[str, Any]) -> QueryPlan:
    entities = _detect_entities(question, alias_map)
    canonical_field = _canonical_field_from_question(question, cfg)
    return QueryPlan(
        question=(question or "").strip(),
        entities=entities,
        intent=_intent(question, entities, canonical_field),
        canonical_field=canonical_field,
        section_hint=_section_hint_for_field(canonical_field, cfg),
    )


def _snippet(text: str, label: str, limit: int = 320) -> str:
    t = re.sub(r"\s+", " ", (text or "").strip())
    if not t:
        return ""
    hint = str(label or "").lower().strip()
    if not hint:
        return t[:limit]
    i = t.lower().find(hint)
    if i < 0:
        return t[:limit]
    lo = max(0, i - 40)
    hi = min(len(t), i + limit)
    return t[lo:hi]


def _cannot(plan: QueryPlan, corpus_name: str, reason: str, locked: bool) -> Dict[str, Any]:
    return {
        "handled": True,
        "reliable": False,
        "corpus_name": corpus_name,
        "country_locked": locked,
        "detected_entities": plan.entities,
        "resolved_field": plan.canonical_field,
        "section": plan.section_hint,
        "answer": "Cannot answer reliably from the offline corpus.",
        "reason": reason,
        "citations": [],
        "confidence": 0.0,
        "mode": "deterministic-fallback",
    }


def answer_reference_question(
    question: str,
    corpus_name: str,
    db_path: str | Path = db.DEFAULT_DB_PATH,
    source_path: str | Path | None = None,
    config_path: str | Path | None = None,
    source_year: int = 0,
    auto_ingest: bool = True,
) -> Dict[str, Any]:
    if source_path and auto_ingest:
        ingest_corpus(
            source_path=source_path,
            corpus_name=corpus_name,
            db_path=db_path,
            config_path=config_path,
            source_year=source_year,
            force=False,
        )

    cfg = load_reference_config(config_path)
    conn = db.connect(db_path)
    try:
        meta = db.corpus_meta(conn, corpus_name)
        if meta and isinstance(meta.get("config"), dict):
            cfg = dict(cfg)
            cfg.update(meta.get("config") or {})

        aliases = db.alias_map(conn, corpus_name)
        if not aliases:
            return {
                "handled": False,
                "reliable": False,
                "corpus_name": corpus_name,
                "answer": "",
                "reason": "corpus-not-ingested",
            }

        plan = _plan(question, aliases, cfg)
        if not plan.entities:
            return {
                "handled": False,
                "reliable": False,
                "corpus_name": corpus_name,
                "answer": "",
                "reason": "no-entity-detected",
            }
        if not plan.canonical_field:
            return _cannot(plan, corpus_name, "entity detected but no canonical field resolved", locked=True)

        if plan.intent == "COMPARISON" and len(plan.entities) >= 2:
            ent = plan.entities[:2]
            lines: List[str] = []
            cits: List[Dict[str, str]] = []
            missing: List[str] = []
            for e in ent:
                item = db.get_canonical_field(conn, corpus_name, e, plan.canonical_field)
                if not item:
                    missing.append(e)
                    continue
                sec = str(item.get("section") or plan.section_hint or "")
                label = str(item.get("label") or plan.canonical_field)
                value = str(item.get("value") or "")
                raw = db.get_section_raw(conn, corpus_name, e, sec) if sec else ""
                lines.append(f"{e}: {plan.canonical_field}: {value}")
                cits.append({"entity": e, "section": sec, "snippet": _snippet(raw, label) if raw else f"{label}: {value}"})
            if missing:
                return _cannot(plan, corpus_name, f"missing structured values for: {', '.join(missing)}", locked=True)
            return {
                "handled": True,
                "reliable": True,
                "corpus_name": corpus_name,
                "country_locked": True,
                "detected_entities": ent,
                "resolved_field": plan.canonical_field,
                "section": plan.section_hint,
                "answer": "Comparison:\n" + "\n".join(f"- {x}" for x in lines),
                "citations": cits,
                "confidence": 0.95,
                "mode": "deterministic-structured",
            }

        entity = plan.entities[0]
        item = db.get_canonical_field(conn, corpus_name, entity, plan.canonical_field)
        if item:
            sec = str(item.get("section") or plan.section_hint or "")
            label = str(item.get("label") or plan.canonical_field)
            value = str(item.get("value") or "")
            raw = db.get_section_raw(conn, corpus_name, entity, sec) if sec else ""
            return {
                "handled": True,
                "reliable": True,
                "corpus_name": corpus_name,
                "country_locked": True,
                "detected_entities": [entity],
                "resolved_field": plan.canonical_field,
                "section": sec,
                "answer": f"{entity}: {plan.canonical_field}: {value}",
                "citations": [{"entity": entity, "section": sec, "snippet": _snippet(raw, label) if raw else f"{label}: {value}"}],
                "confidence": 0.98,
                "mode": "deterministic-structured",
            }

        hits = db.search_sections(conn, corpus_name, entity, question, section_hint=plan.section_hint, limit=2)
        if hits:
            h = hits[0]
            return {
                "handled": True,
                "reliable": True,
                "corpus_name": corpus_name,
                "country_locked": True,
                "detected_entities": [entity],
                "resolved_field": plan.canonical_field,
                "section": str(h.get("section_name") or plan.section_hint or ""),
                "answer": f"{entity}: {plan.canonical_field}: {str(h.get('snippet') or '').strip()}",
                "citations": [
                    {
                        "entity": entity,
                        "section": str(h.get("section_name") or ""),
                        "snippet": str(h.get("snippet") or ""),
                    }
                ],
                "confidence": 0.72,
                "mode": "entity-locked-fts",
            }

        return _cannot(plan, corpus_name, "no structured or entity-locked FTS match", locked=True)
    finally:
        conn.close()


def render_reference_result(result: Dict[str, Any]) -> str:
    corpus = str(result.get("corpus_name") or "unknown")
    entities = result.get("detected_entities") or []
    entity_line = ", ".join(str(e) for e in entities) if entities else "None"
    field = str(result.get("resolved_field") or "Unknown")
    section = str(result.get("section") or "Unknown")
    locked = "true" if bool(result.get("country_locked")) else "false"
    conf = float(result.get("confidence") or 0.0)
    mode = str(result.get("mode") or "unknown")
    reliable = bool(result.get("reliable"))

    lines = [
        f"Corpus: {corpus}",
        f"Detected entity/entities: {entity_line}",
        f"Resolved field: {section} -> {field}",
        f"Mode: {mode}",
        f"Entity locked: {locked}",
        f"Confidence: {conf:.2f}",
    ]
    cits = result.get("citations") or []
    if cits:
        lines.append("Citations:")
        for c in cits:
            e = str(c.get("entity") or "?")
            s = str(c.get("section") or "?")
            sn = str(c.get("snippet") or "").strip()
            lines.append(f"- [{e} | {s}] {sn}")
    else:
        lines.append("Citations: (none)")

    if reliable:
        lines.append("Answer:")
        lines.append(str(result.get("answer") or "").strip())
    else:
        lines.append("Cannot answer reliably from the offline corpus.")
    return "\n".join(lines).strip()
