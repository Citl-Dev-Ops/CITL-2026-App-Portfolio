from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

import factbook_db as db
from factbook_ingest import ingest_factbook
from parsers import CANONICAL_FIELD_SPECS, citation_snippet
from query_router import QueryPlan, route_question


HERE = Path(__file__).resolve().parent
DEFAULT_SOURCE = HERE / "factbook.txt"


def _title_field(field: str) -> str:
    return (field or "").strip().title()


def _section_title(field: str) -> str:
    spec = CANONICAL_FIELD_SPECS.get(field) or {}
    return str(spec.get("section") or "Unknown").title()


def _cannot_answer(plan: QueryPlan, reason: str, country_locked: bool) -> Dict[str, Any]:
    return {
        "handled": True,
        "reliable": False,
        "country_locked": country_locked,
        "detected_entities": plan.entities,
        "resolved_field": plan.canonical_field,
        "section": plan.section_hint,
        "answer": "Cannot answer reliably from the offline Factbook 2023 corpus.",
        "reason": reason,
        "citations": [],
        "confidence": 0.0,
        "mode": "deterministic-fallback",
        "source": "Factbook 2023",
    }


def _fetch_section_raw(conn, country_name: str, section_name: str) -> str:
    row = conn.execute(
        "SELECT raw FROM sections WHERE lower(country_name)=lower(?) AND lower(section)=lower(?)",
        (country_name, section_name),
    ).fetchone()
    if not row:
        return ""
    return str(row["raw"] or "")


def _structured_single(conn, plan: QueryPlan, country_name: str) -> Optional[Dict[str, Any]]:
    if not plan.canonical_field:
        return None
    item = db.get_canonical_field(conn, country_name, plan.canonical_field)
    if not item:
        return None
    section = str(item.get("section") or plan.section_hint or "")
    label = str(item.get("label") or plan.canonical_field)
    value = str(item.get("value") or "")
    raw_value = str(item.get("raw_value") or value)
    section_raw = _fetch_section_raw(conn, country_name, section) if section else ""
    snip = citation_snippet(section_raw, label) if section_raw else f"{label}: {raw_value}"
    field_title = _title_field(plan.canonical_field)
    answer_line = f"{country_name}: {field_title}: {value}"
    if plan.canonical_field == "border countries":
        answer_line = f"{country_name} border countries: {value}"
    return {
        "handled": True,
        "reliable": True,
        "country_locked": True,
        "detected_entities": [country_name],
        "resolved_field": plan.canonical_field,
        "section": section,
        "answer": answer_line,
        "citations": [{"country": country_name, "section": section, "snippet": snip}],
        "confidence": 0.98,
        "mode": "deterministic-structured",
        "source": "Factbook 2023",
    }


def _comparison(conn, plan: QueryPlan) -> Dict[str, Any]:
    assert plan.canonical_field
    entities = plan.entities[:2]
    entries: List[Dict[str, Any]] = []
    missing: List[str] = []
    for country in entities:
        item = db.get_canonical_field(conn, country, plan.canonical_field)
        if not item:
            missing.append(country)
            continue
        section = str(item.get("section") or plan.section_hint or "")
        label = str(item.get("label") or plan.canonical_field)
        raw_value = str(item.get("raw_value") or item.get("value") or "")
        section_raw = _fetch_section_raw(conn, country, section) if section else ""
        snip = citation_snippet(section_raw, label) if section_raw else f"{label}: {raw_value}"
        entries.append(
            {
                "country": country,
                "value": str(item.get("value") or ""),
                "section": section,
                "snippet": snip,
            }
        )

    if missing:
        return _cannot_answer(plan, f"missing structured values for: {', '.join(missing)}", country_locked=True)

    field_title = _title_field(plan.canonical_field)
    lines = [f"{e['country']}: {field_title}: {e['value']}" for e in entries]
    cits = [{"country": e["country"], "section": e["section"], "snippet": e["snippet"]} for e in entries]
    return {
        "handled": True,
        "reliable": True,
        "country_locked": True,
        "detected_entities": entities,
        "resolved_field": plan.canonical_field,
        "section": _section_title(plan.canonical_field),
        "answer": "Comparison:\n" + "\n".join(f"- {line}" for line in lines),
        "citations": cits,
        "confidence": 0.95,
        "mode": "deterministic-structured",
        "source": "Factbook 2023",
    }


def _country_scoped_fts(conn, plan: QueryPlan, country_name: str) -> Optional[Dict[str, Any]]:
    hits = db.search_sections(
        conn,
        country_name=country_name,
        question=plan.question,
        section=plan.section_hint,
        limit=2,
    )
    if not hits:
        return None
    hit = hits[0]
    section = str(hit.get("section") or plan.section_hint or "")
    snippet = str(hit.get("snippet") or hit.get("raw") or "").strip()
    if not snippet:
        return None
    field_title = _title_field(plan.canonical_field or "lookup")
    return {
        "handled": True,
        "reliable": True,
        "country_locked": True,
        "detected_entities": [country_name],
        "resolved_field": plan.canonical_field,
        "section": section,
        "answer": f"{country_name}: {field_title}: {snippet}",
        "citations": [{"country": country_name, "section": section, "snippet": snippet}],
        "confidence": 0.72,
        "mode": "entity-locked-fts",
        "source": "Factbook 2023",
    }


def answer_offline(
    question: str,
    db_path: str | Path = db.DEFAULT_DB_PATH,
    source_path: str | Path = DEFAULT_SOURCE,
    source_year: int = 2023,
) -> Dict[str, Any]:
    # Keep DB updated automatically with local source text.
    ingest_factbook(source_path=source_path, db_path=db_path, source_year=source_year, force=False)

    conn = db.connect(db_path)
    try:
        alias_map = db.country_alias_strings(conn)
        plan = route_question(question, alias_map)

        if not plan.entities:
            return {
                "handled": False,
                "reliable": False,
                "country_locked": False,
                "detected_entities": [],
                "resolved_field": plan.canonical_field,
                "section": plan.section_hint,
                "answer": "",
                "reason": "no-country-entity-detected",
                "citations": [],
                "confidence": 0.0,
                "mode": "none",
                "source": "Factbook 2023",
            }

        if not plan.canonical_field:
            return _cannot_answer(plan, "country detected but no canonical field resolved", country_locked=True)

        if plan.intent == "COMPARISON" and len(plan.entities) >= 2:
            return _comparison(conn, plan)

        country = plan.entities[0]
        structured = _structured_single(conn, plan, country)
        if structured:
            return structured

        fallback = _country_scoped_fts(conn, plan, country)
        if fallback:
            return fallback

        return _cannot_answer(plan, "no structured or country-locked FTS match", country_locked=True)
    finally:
        conn.close()


def render_answer(result: Dict[str, Any]) -> str:
    entities = result.get("detected_entities") or []
    entity_line = ", ".join(str(e) for e in entities) if entities else "None"
    field = str(result.get("resolved_field") or "Unknown")
    section = str(result.get("section") or "Unknown")
    confidence = float(result.get("confidence") or 0.0)
    mode = str(result.get("mode") or "unknown")
    locked = "true" if bool(result.get("country_locked")) else "false"
    source = str(result.get("source") or "Factbook 2023")
    reliable = bool(result.get("reliable"))

    lines = [
        f"Detected country/entities: {entity_line}",
        f"Resolved field: {section} -> {field}",
        f"Source: {source}",
        f"Mode: {mode}",
        f"Country locked: {locked}",
        f"Confidence: {confidence:.2f}",
    ]

    cits = result.get("citations") or []
    if cits:
        lines.append("Citations:")
        for c in cits:
            cc = str(c.get("country") or "?")
            ss = str(c.get("section") or "?")
            sn = str(c.get("snippet") or "").strip()
            lines.append(f"- [{cc} | {ss}] {sn}")
    else:
        lines.append("Citations: (none)")

    if reliable:
        lines.append("Answer:")
        lines.append(str(result.get("answer") or "").strip())
    else:
        lines.append("Cannot answer reliably from the offline Factbook 2023 corpus.")
    return "\n".join(lines).strip()


def try_answer_text(
    question: str,
    db_path: str | Path = db.DEFAULT_DB_PATH,
    source_path: str | Path = DEFAULT_SOURCE,
    source_year: int = 2023,
) -> Optional[str]:
    res = answer_offline(question, db_path=db_path, source_path=source_path, source_year=source_year)
    if not res.get("handled"):
        return None
    return render_answer(res)
