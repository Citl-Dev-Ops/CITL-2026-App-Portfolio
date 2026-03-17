from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import reference_db as db
from .reference_config import load_reference_config


def _norm_space(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def _norm_label(text: str) -> str:
    return _norm_space(text).rstrip(":").lower()


def _aliases_for_entity(name: str) -> List[str]:
    n = _norm_space(name)
    if not n:
        return []
    out = {n, n.title(), n.upper()}
    if n.lower().startswith("the "):
        out.add(n[4:].strip())
    else:
        out.add(f"The {n}")
    m = re.match(r"^(.*?),\s*THE$", n, re.IGNORECASE)
    if m:
        stem = _norm_space(m.group(1))
        if stem:
            out.add(stem)
            out.add(f"The {stem}")
    words = [w for w in re.findall(r"[A-Za-z]+", n.title()) if w.lower() not in {"and", "of", "the"}]
    if 2 <= len(words) <= 5:
        acronym = "".join(w[0] for w in words).upper()
        if len(acronym) >= 2:
            out.add(acronym)
    return sorted(out, key=lambda s: (len(s), s.lower()))


@dataclass
class ParsedEntity:
    entity_name: str
    aliases: List[str]
    sections: Dict[str, str]
    section_fields: Dict[str, Dict[str, str]]
    canonical_fields: Dict[str, Dict[str, str]]


def _iter_entity_starts(text: str, cfg: Dict[str, Any]) -> List[Tuple[int, str]]:
    regex = str(cfg.get("entity_heading_regex") or r"(?m)^\s*([A-Z][A-Z0-9 ,.'()/&-]{2,})\s*$")
    rx = re.compile(regex, re.MULTILINE)
    max_chars = int(cfg.get("entity_max_heading_chars") or 72)
    probe_chars = int(cfg.get("entity_probe_chars") or 2400)
    required_markers = [str(x) for x in (cfg.get("entity_required_markers") or [])]
    known_sections = {str(x).upper().strip() for x in (cfg.get("known_sections") or []) if str(x).strip()}

    starts: List[Tuple[int, str]] = []
    n = len(text)
    for m in rx.finditer(text):
        heading = _norm_space(m.group(1) if m.groups() else m.group(0))
        if not heading:
            continue
        if len(heading) > max_chars:
            continue
        if heading.upper() in known_sections:
            continue
        if required_markers:
            probe = text[m.start() : min(n, m.start() + probe_chars)]
            up = probe.upper()
            if not all(marker.upper() in up for marker in required_markers):
                continue
        starts.append((m.start(), heading))
    return starts


def _split_sections(entity_name: str, block: str, cfg: Dict[str, Any]) -> Dict[str, str]:
    regex = str(cfg.get("section_heading_regex") or r"(?m)^\s*([A-Z][A-Z0-9 /&(),.'-]{2,})\s*$")
    rx = re.compile(regex, re.MULTILINE)
    known_sections = {str(s).upper() for s in (cfg.get("known_sections") or [])}

    matches: List[Tuple[int, str]] = []
    for m in rx.finditer(block):
        name = _norm_space(m.group(1) if m.groups() else m.group(0))
        if not name:
            continue
        if ":" in name:
            continue
        if len(name) > 90:
            continue
        if name.upper() == entity_name.upper():
            continue
        if known_sections and name.upper() not in known_sections:
            continue
        matches.append((m.start(), name.title()))

    if not matches:
        return {"Fulltext": block.strip()}

    sections: Dict[str, str] = {}
    for i, (start, sec_name) in enumerate(matches):
        end = matches[i + 1][0] if i + 1 < len(matches) else len(block)
        raw = block[start:end].strip()
        if raw:
            sections[sec_name] = raw
    return sections or {"Fulltext": block.strip()}


def _parse_section_fields(section_text: str, cfg: Dict[str, Any]) -> Dict[str, str]:
    regex = str(cfg.get("field_line_regex") or r"^([A-Za-z][A-Za-z0-9 /()'%,.-]{1,72}):\s*(.*)$")
    line_rx = re.compile(regex)

    fields: Dict[str, str] = {}
    label = ""
    parts: List[str] = []

    def flush() -> None:
        nonlocal label, parts
        if not label:
            return
        value = _norm_space(" ".join(parts))
        if value:
            fields[label] = value
        label = ""
        parts = []

    for raw in (section_text or "").splitlines():
        line = _norm_space(raw)
        if not line:
            continue
        m = line_rx.match(line)
        if m:
            cand = _norm_label(m.group(1))
            if cand:
                flush()
                label = cand
                parts = [m.group(2).strip()]
                continue
        if label:
            parts.append(line)
    flush()
    return fields


def _extract_label_value(section_text: str, label: str) -> Optional[str]:
    pat = (
        rf"(?is)\b{re.escape(label)}\s*(?:\(\s*\d+\s*\))?\s*:\s*(.+?)"
        rf"(?=\s+[A-Z][A-Za-z][A-Za-z0-9 /()'%,.-]{{1,42}}:\s|\n\s*\n|$)"
    )
    m = re.search(pat, section_text or "")
    if not m:
        return None
    return _norm_space(m.group(1))


def _parse_border_like(value: str) -> str:
    text = _norm_space(value)
    if not text:
        return ""
    text = re.sub(r"(?i)\bnote\s*:\s*.*$", "", text).strip()
    parts = re.split(r"\s*;\s*|\s*,\s*(?=[A-Z])", text)
    out: List[str] = []
    for p in parts:
        name = re.sub(r"\([^)]*\)", "", p)
        name = re.sub(r"\s+\d[\d,]*(?:\.\d+)?\s*(?:km|miles?)\b.*$", "", name, flags=re.IGNORECASE)
        name = _norm_space(name)
        if name:
            out.append(name)
    dedup: List[str] = []
    seen = set()
    for n in out:
        k = n.lower()
        if k in seen:
            continue
        seen.add(k)
        dedup.append(n)
    return ", ".join(dedup)


def _infer_canonical_fields(
    sections: Dict[str, str],
    section_fields: Dict[str, Dict[str, str]],
    cfg: Dict[str, Any],
) -> Dict[str, Dict[str, str]]:
    canonical_cfg = cfg.get("canonical_fields")
    if not isinstance(canonical_cfg, dict):
        return {}

    out: Dict[str, Dict[str, str]] = {}
    for canonical, spec_any in canonical_cfg.items():
        if not isinstance(spec_any, dict):
            continue
        spec = spec_any
        labels = [_norm_label(str(x)) for x in (spec.get("labels") or [canonical])]
        target_section = str(spec.get("section") or "").title()

        sec_candidates: List[str] = []
        if target_section and target_section in sections:
            sec_candidates.append(target_section)
        sec_candidates.extend([s for s in sections.keys() if s not in sec_candidates])

        for sec in sec_candidates:
            raw = sections.get(sec, "")
            parsed = section_fields.get(sec, {})
            value = ""
            label = ""
            for lab in labels:
                if lab in parsed:
                    value = parsed[lab]
                    label = lab
                    break
            if not value:
                for lab in labels:
                    found = _extract_label_value(raw, lab)
                    if found:
                        value = found
                        label = lab
                        break
            if not value:
                continue

            display_value = value
            if canonical.lower() == "border countries":
                parsed_border = _parse_border_like(value)
                if parsed_border:
                    display_value = parsed_border

            out[str(canonical)] = {
                "value": display_value,
                "raw_value": value,
                "section": sec,
                "label": label or str(canonical),
            }
            break
    return out


def parse_reference_text(text: str, corpus_name: str, cfg: Dict[str, Any]) -> List[ParsedEntity]:
    starts = _iter_entity_starts(text, cfg)
    if not starts:
        block = (text or "").strip()
        sections = _split_sections(corpus_name, block, cfg)
        fields = {s: _parse_section_fields(raw, cfg) for s, raw in sections.items()}
        canonical = _infer_canonical_fields(sections, fields, cfg)
        return [
            ParsedEntity(
                entity_name=corpus_name,
                aliases=_aliases_for_entity(corpus_name),
                sections=sections,
                section_fields=fields,
                canonical_fields=canonical,
            )
        ]

    entities: List[ParsedEntity] = []
    n = len(text)
    for i, (start, heading) in enumerate(starts):
        end = starts[i + 1][0] if i + 1 < len(starts) else n
        block = (text[start:end] or "").strip()
        if not block:
            continue
        sections = _split_sections(heading, block, cfg)
        fields = {s: _parse_section_fields(raw, cfg) for s, raw in sections.items()}
        canonical = _infer_canonical_fields(sections, fields, cfg)
        entities.append(
            ParsedEntity(
                entity_name=heading.title(),
                aliases=_aliases_for_entity(heading),
                sections=sections,
                section_fields=fields,
                canonical_fields=canonical,
            )
        )
    return entities


def ingest_corpus(
    source_path: str | Path,
    corpus_name: str,
    db_path: str | Path = db.DEFAULT_DB_PATH,
    config_path: str | Path | None = None,
    source_year: int = 0,
    force: bool = False,
) -> Dict[str, int]:
    cfg = load_reference_config(config_path)
    src = Path(source_path).expanduser().resolve()
    if not src.exists():
        raise FileNotFoundError(f"Source missing: {src}")
    st = src.stat()

    conn = db.connect(db_path)
    try:
        meta = db.corpus_meta(conn, corpus_name)
        if meta and not force:
            same = (
                str(meta.get("source_path") or "") == str(src)
                and int(float(meta.get("source_mtime") or 0)) == int(st.st_mtime)
                and int(meta.get("source_size") or 0) == int(st.st_size)
                and int(meta.get("source_year") or 0) == int(source_year)
            )
            if same:
                row = conn.execute("SELECT COUNT(*) AS n FROM entities WHERE corpus_name = ?", (corpus_name,)).fetchone()
                count = int(row["n"] if row else 0)
                return {"entities": count, "sections": 0, "reingested": 0}

        raw = src.read_text(encoding="utf-8", errors="ignore")
        parsed = parse_reference_text(raw, corpus_name=corpus_name, cfg=cfg)

        db.upsert_corpus(
            conn,
            corpus_name=corpus_name,
            source_path=str(src),
            source_mtime=float(st.st_mtime),
            source_size=int(st.st_size),
            source_year=int(source_year),
            mode=str(cfg.get("mode") or "reference"),
            config=cfg,
        )
        db.clear_corpus(conn, corpus_name)

        section_count = 0
        for ent in parsed:
            payload = {
                "canonical_fields": ent.canonical_fields,
                "section_fields": ent.section_fields,
            }
            db.upsert_entity(conn, corpus_name, ent.entity_name, ent.aliases, payload)
            for sec_name, sec_raw in ent.sections.items():
                db.upsert_section(conn, corpus_name, ent.entity_name, sec_name, sec_raw)
                section_count += 1

        db.commit(conn)
        db.rebuild_fts_for_corpus(conn, corpus_name)
        return {"entities": len(parsed), "sections": section_count, "reingested": 1}
    finally:
        conn.close()


def main() -> None:
    ap = argparse.ArgumentParser(description="Ingest a reference corpus into the generic entity-locked DB.")
    ap.add_argument("--src", required=True, help="Path to source text file")
    ap.add_argument("--corpus", required=True, help="Corpus name key")
    ap.add_argument("--db", default=str(db.DEFAULT_DB_PATH), help="SQLite DB path")
    ap.add_argument("--config", default="", help="Optional JSON/YAML config path")
    ap.add_argument("--source-year", type=int, default=0, help="Source year metadata")
    ap.add_argument("--force", action="store_true", help="Force re-ingest")
    args = ap.parse_args()

    stats = ingest_corpus(
        source_path=args.src,
        corpus_name=args.corpus,
        db_path=args.db,
        config_path=(args.config or None),
        source_year=int(args.source_year),
        force=bool(args.force),
    )
    print(
        f"[reference_ingest] corpus={args.corpus} entities={stats['entities']} "
        f"sections={stats['sections']} reingested={stats['reingested']} db={args.db}"
    )


if __name__ == "__main__":
    main()
