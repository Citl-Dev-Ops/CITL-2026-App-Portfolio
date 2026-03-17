from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from parsers import CANONICAL_FIELD_SPECS, canonical_field_from_question


@dataclass
class QueryPlan:
    question: str
    entities: List[str]
    intent: str
    canonical_field: Optional[str]
    section_hint: Optional[str]


def _norm_key(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (text or "").lower())


# Common English words that can spuriously match short country aliases.
_STOPWORDS = frozenset({
    "a", "an", "and", "are", "as", "at", "be", "by", "do", "for",
    "from", "go", "has", "have", "he", "her", "him", "his", "how",
    "if", "in", "is", "it", "its", "me", "my", "no", "not", "of",
    "on", "or", "our", "out", "so", "the", "to", "up", "us", "was",
    "we", "what", "when", "who", "why", "will", "with",
})


def detect_entities(question: str, alias_to_country: Dict[str, str]) -> List[str]:
    q = (question or "").strip()
    ql = q.lower()
    found: List[str] = []
    seen = set()

    aliases: List[Tuple[str, str]] = sorted(
        [(a, c) for a, c in alias_to_country.items() if a and c],
        key=lambda p: len(p[0]),
        reverse=True,
    )

    for alias, country in aliases:
        a = alias.strip()
        if not a:
            continue
        # Skip aliases that are common English words to prevent false matches
        # (e.g. the word "is" in a question matching a 2-letter country code).
        if a.lower() in _STOPWORDS:
            continue
        pat = rf"(?<![A-Za-z0-9]){re.escape(a.lower())}(?![A-Za-z0-9])"
        if re.search(pat, ql):
            if country not in seen:
                seen.add(country)
                found.append(country)

    if found:
        return found

    # Fallback for punctuation-normalized aliases.
    qn = _norm_key(q)
    for alias, country in aliases:
        an = _norm_key(alias)
        if len(an) < 4:
            continue
        if an in qn and country not in seen:
            seen.add(country)
            found.append(country)
    return found


def detect_intent(question: str, entities: List[str], canonical_field: Optional[str]) -> str:
    q = (question or "").lower()
    if len(entities) >= 2 or re.search(r"\b(compare|vs\.?|versus|higher|lower|difference)\b", q):
        return "COMPARISON"
    if canonical_field and re.search(r"\b(list|which countries|what countries|what are)\b", q):
        return "LIST"
    if canonical_field:
        return "FACT_LOOKUP"
    if entities:
        return "EXPLANATION"
    return "UNKNOWN"


def route_question(question: str, alias_to_country: Dict[str, str]) -> QueryPlan:
    entities = detect_entities(question, alias_to_country)
    canonical_field = canonical_field_from_question(question)
    intent = detect_intent(question, entities, canonical_field)
    section_hint = None
    if canonical_field:
        spec = CANONICAL_FIELD_SPECS.get(canonical_field) or {}
        section_hint = str(spec.get("section") or "").title() or None
    return QueryPlan(
        question=(question or "").strip(),
        entities=entities,
        intent=intent,
        canonical_field=canonical_field,
        section_hint=section_hint,
    )
