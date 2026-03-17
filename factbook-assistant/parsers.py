from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple


@dataclass
class CountryRecord:
    country_name: str
    aliases: List[str]
    sections: Dict[str, str]
    section_fields: Dict[str, Dict[str, str]]
    canonical_fields: Dict[str, Dict[str, str]]


KNOWN_SECTIONS = {
    "INTRODUCTION",
    "GEOGRAPHY",
    "PEOPLE AND SOCIETY",
    "ENVIRONMENT",
    "GOVERNMENT",
    "ECONOMY",
    "ENERGY",
    "COMMUNICATIONS",
    "TRANSPORTATION",
    "MILITARY AND SECURITY",
    "TERRORISM",
    "TRANSNATIONAL ISSUES",
}


CANONICAL_FIELD_SPECS: Dict[str, Dict[str, object]] = {
    "capital": {
        "section": "GOVERNMENT",
        "labels": ["capital", "name"],
        "query_aliases": [
            "capital",
            "capital city",
            "what is the capital",
            "what's the capital",
            "capital of",
        ],
    },
    "border countries": {
        "section": "GEOGRAPHY",
        "labels": ["border countries"],
        "query_aliases": [
            "border countries",
            "countries border",
            "what countries border",
            "neighbors",
            "neighbours",
            "bordering countries",
            "land boundaries",
        ],
    },
    "population": {
        "section": "PEOPLE AND SOCIETY",
        "labels": ["population"],
        "query_aliases": ["population", "how many people"],
    },
    "languages": {
        "section": "PEOPLE AND SOCIETY",
        "labels": ["languages"],
        "query_aliases": ["languages", "language", "spoken languages", "speak"],
    },
    "religions": {
        "section": "PEOPLE AND SOCIETY",
        "labels": ["religions", "religion"],
        "query_aliases": ["religions", "religion", "faiths", "main religions"],
    },
    "ethnic groups": {
        "section": "PEOPLE AND SOCIETY",
        "labels": ["ethnic groups", "ethnicity"],
        "query_aliases": ["ethnic groups", "ethnicity", "ethnic makeup"],
    },
    "literacy": {
        "section": "PEOPLE AND SOCIETY",
        "labels": ["literacy"],
        "query_aliases": ["literacy", "literacy rate"],
    },
    "median age": {
        "section": "PEOPLE AND SOCIETY",
        "labels": ["median age"],
        "query_aliases": ["median age"],
    },
    "urbanization": {
        "section": "PEOPLE AND SOCIETY",
        "labels": ["urbanization"],
        "query_aliases": ["urbanization", "urbanised", "urbanized"],
    },
    "coastline": {
        "section": "GEOGRAPHY",
        "labels": ["coastline"],
        "query_aliases": ["coastline", "coast line", "has a coastline"],
    },
    "climate": {
        "section": "GEOGRAPHY",
        "labels": ["climate"],
        "query_aliases": ["climate", "weather pattern"],
    },
    "area": {
        "section": "GEOGRAPHY",
        "labels": ["area"],
        "query_aliases": ["area", "total area", "size"],
    },
}


def normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def normalize_label(text: str) -> str:
    return normalize_space(text).rstrip(":").lower()


def country_aliases(country_heading: str) -> List[str]:
    h = normalize_space(country_heading)
    if not h:
        return []

    out = {h, h.title(), h.upper()}

    m = re.match(r"^(.*?),\s*THE$", h, re.IGNORECASE)
    if m:
        stem = normalize_space(m.group(1))
        if stem:
            out.add(stem)
            out.add(f"The {stem}")

    if h.lower().startswith("the "):
        out.add(h[4:].strip())
    else:
        out.add(f"The {h}")

    words = [w for w in re.findall(r"[A-Za-z]+", h.title()) if w.lower() not in {"and", "of", "the"}]
    if 2 <= len(words) <= 4:
        acronym = "".join(w[0] for w in words).upper()
        if len(acronym) >= 2:
            out.add(acronym)

    # Keep aliases deterministic and readable.
    aliases = [a for a in sorted(out, key=lambda s: (len(s), s.lower())) if a]
    return aliases


def _country_block_starts(text: str) -> List[Tuple[int, str]]:
    starts: List[Tuple[int, str]] = []
    heading_re = re.compile(r"(?m)^\s*([A-Z][A-Z0-9 ,.'()/&-]{2,})\s*$")
    n = len(text)
    for m in heading_re.finditer(text):
        heading = normalize_space(m.group(1))
        if not heading or len(heading) > 60:
            continue
        if heading in KNOWN_SECTIONS:
            continue
        probe = text[m.start(): min(n, m.start() + 2600)]
        up = probe.upper()
        if "INTRODUCTION" not in up:
            continue
        if "BACKGROUND:" not in up:
            continue
        starts.append((m.start(), heading))
    return starts


def _looks_like_section_heading(name: str, country_heading: str) -> bool:
    if not name:
        return False
    if name == country_heading:
        return False
    if ":" in name:
        return False
    if len(name) > 72:
        return False
    if name in KNOWN_SECTIONS:
        return True
    # Support unknown all-caps sections from other corpora.
    return bool(re.fullmatch(r"[A-Z][A-Z0-9 /&(),.'-]{2,}", name))


def split_sections(country_heading: str, country_block: str) -> Dict[str, str]:
    # Keep section names in natural title case for display.
    matches: List[Tuple[int, str]] = []
    section_re = re.compile(r"(?m)^\s*([A-Z][A-Z0-9 /&(),.'-]{2,})\s*$")
    for m in section_re.finditer(country_block):
        name = normalize_space(m.group(1))
        if not _looks_like_section_heading(name, country_heading):
            continue
        matches.append((m.start(), name))

    if not matches:
        return {"Fulltext": country_block.strip()}

    sections: Dict[str, str] = {}
    for i, (start, name) in enumerate(matches):
        end = matches[i + 1][0] if i + 1 < len(matches) else len(country_block)
        raw = country_block[start:end].strip()
        if not raw:
            continue
        sections[name.title()] = raw
    return sections


def parse_section_fields(section_text: str) -> Dict[str, str]:
    fields: Dict[str, str] = {}
    current_label = ""
    current_parts: List[str] = []

    def flush() -> None:
        nonlocal current_label, current_parts
        if not current_label:
            return
        value = normalize_space(" ".join(current_parts))
        if value:
            fields[current_label] = value
        current_label = ""
        current_parts = []

    for raw_line in (section_text or "").splitlines():
        line = normalize_space(raw_line)
        if not line:
            continue

        # Ignore obvious section headers.
        if re.fullmatch(r"[A-Z][A-Z0-9 /&(),.'-]{2,}", line):
            flush()
            continue

        m = re.match(r"^([A-Za-z][A-Za-z0-9 /()'%,.-]{1,72}):\s*(.*)$", line)
        if m:
            label = normalize_label(m.group(1))
            if 1 <= len(label) <= 80:
                flush()
                current_label = label
                current_parts = [m.group(2).strip()]
                continue

        if current_label:
            current_parts.append(line)

    flush()
    return fields


def _extract_label_value(section_text: str, label: str) -> Optional[str]:
    # Stops at next "Label:" shape, blank line, or section end.
    pat = (
        rf"(?is)\b{re.escape(label)}\s*(?:\(\s*\d+\s*\))?\s*:\s*(.+?)"
        rf"(?=\s+[A-Z][A-Za-z][A-Za-z0-9 /()'%,.-]{{1,42}}:\s|\n\s*\n|$)"
    )
    m = re.search(pat, section_text or "")
    if not m:
        return None
    return normalize_space(m.group(1))


def parse_border_countries(raw_value: str) -> List[str]:
    text = normalize_space(raw_value)
    if not text:
        return []
    text = re.sub(r"(?i)\bnote\s*:\s*.*$", "", text).strip()
    parts = re.split(r"\s*;\s*|\s*,\s*(?=[A-Z])", text)
    out: List[str] = []
    for p in parts:
        if not p:
            continue
        name = re.sub(r"\([^)]*\)", "", p)
        name = re.sub(r"\s+\d[\d,]*(?:\.\d+)?\s*km\b.*$", "", name, flags=re.IGNORECASE)
        name = re.sub(r"\s+\d[\d,]*(?:\.\d+)?\s*miles?\b.*$", "", name, flags=re.IGNORECASE)
        name = normalize_space(name)
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
    return dedup


def _field_value_for_section(
    canonical_field: str,
    section_text: str,
    section_fields: Dict[str, str],
) -> Optional[Tuple[str, str]]:
    spec = CANONICAL_FIELD_SPECS.get(canonical_field) or {}
    labels = [normalize_label(str(x)) for x in (spec.get("labels") or [])]

    for lab in labels:
        if lab in section_fields:
            return section_fields[lab], lab

    for lab in labels:
        found = _extract_label_value(section_text, lab)
        if found:
            return found, lab
    return None


def infer_canonical_fields(
    sections: Dict[str, str],
    section_fields: Dict[str, Dict[str, str]],
) -> Dict[str, Dict[str, str]]:
    out: Dict[str, Dict[str, str]] = {}
    for field_name, spec in CANONICAL_FIELD_SPECS.items():
        target_section = str(spec.get("section") or "").title()
        candidate_sections: List[str] = []
        if target_section and target_section in sections:
            candidate_sections.append(target_section)
        candidate_sections.extend([s for s in sections.keys() if s not in candidate_sections])

        for sec_name in candidate_sections:
            raw = sections.get(sec_name) or ""
            fields = section_fields.get(sec_name) or {}
            match = _field_value_for_section(field_name, raw, fields)
            if not match:
                continue
            value, label = match
            display_value = value
            if field_name == "capital":
                m_cap = re.search(
                    r"(?i)\bname:\s*([^;,\n]+?)(?=\s+geographic coordinates|\s+time difference|\s+daylight|$)",
                    value,
                )
                if m_cap:
                    display_value = normalize_space(m_cap.group(1))
            if field_name == "border countries":
                borders = parse_border_countries(value)
                if borders:
                    display_value = ", ".join(borders)
            out[field_name] = {
                "value": display_value,
                "raw_value": value,
                "section": sec_name,
                "label": label,
            }
            break
    return out


def parse_factbook_text(text: str) -> List[CountryRecord]:
    records: List[CountryRecord] = []
    starts = _country_block_starts(text or "")
    if not starts:
        return records

    n = len(text)
    for i, (start, heading) in enumerate(starts):
        end = starts[i + 1][0] if i + 1 < len(starts) else n
        block = (text[start:end] or "").strip()
        if not block:
            continue
        sections = split_sections(heading, block)
        per_section_fields = {name: parse_section_fields(raw) for name, raw in sections.items()}
        canonical = infer_canonical_fields(sections, per_section_fields)
        records.append(
            CountryRecord(
                country_name=heading.title(),
                aliases=country_aliases(heading),
                sections=sections,
                section_fields=per_section_fields,
                canonical_fields=canonical,
            )
        )
    return records


def canonical_field_from_question(question: str) -> Optional[str]:
    q_raw = (question or "").lower()
    if not q_raw:
        return None

    q = normalize_space(re.sub(r"[^a-z0-9]+", " ", q_raw))
    q_compact = re.sub(r"[^a-z0-9]+", "", q_raw)

    # Longest-first prevents "language" from winning before "spoken languages".
    pairs: List[Tuple[str, str]] = []
    for canonical, spec in CANONICAL_FIELD_SPECS.items():
        for alias in spec.get("query_aliases", []):
            pairs.append((str(alias).lower(), canonical))
    pairs.sort(key=lambda p: len(p[0]), reverse=True)

    for alias, canonical in pairs:
        a = alias.strip()
        if not a:
            continue
        if a in q:
            return canonical
        a_compact = re.sub(r"[^a-z0-9]+", "", a)
        if a_compact and a_compact in q_compact:
            return canonical

    # Border-country questions are high-frequency and come in many phrasings.
    if re.search(r"\b(neighbors?|neighbours?|neighboring|neighbouring)\b", q):
        return "border countries"
    if re.search(r"\bland boundaries?\b", q):
        return "border countries"
    if re.search(r"\bborder(?:s|ed|ing)?\b", q):
        if re.search(r"\b(countries?|states?|nations?)\b", q):
            return "border countries"
        if re.search(r"\bwho\b", q):
            return "border countries"

    return None


def citation_snippet(section_text: str, label_hint: str, max_chars: int = 320) -> str:
    text = normalize_space(section_text)
    if not text:
        return ""
    hint = normalize_label(label_hint).split(":")[0]
    idx = text.lower().find(hint.lower()) if hint else -1
    if idx < 0:
        return text[:max_chars]
    lo = max(0, idx - 40)
    hi = min(len(text), idx + max_chars)
    return text[lo:hi]
