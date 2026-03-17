from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict


DEFAULT_REFERENCE_CONFIG: Dict[str, Any] = {
    "mode": "reference",
    "entity_heading_regex": r"(?m)^\s*([A-Z][A-Z0-9 ,.'()/&-]{2,})\s*$",
    "entity_max_heading_chars": 72,
    "entity_probe_chars": 2600,
    "entity_required_markers": ["INTRODUCTION", "Background:"],
    "section_heading_regex": r"(?m)^\s*([A-Z][A-Z0-9 /&(),.'-]{2,})\s*$",
    "known_sections": [
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
    ],
    "field_line_regex": r"^([A-Za-z][A-Za-z0-9 /()'%,.-]{1,72}):\s*(.*)$",
    "canonical_fields": {
        "capital": {
            "section": "GOVERNMENT",
            "labels": ["capital", "name"],
            "aliases": [
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
            "aliases": ["border countries", "what countries border", "neighbors", "neighbours", "bordering countries"],
        },
        "population": {
            "section": "PEOPLE AND SOCIETY",
            "labels": ["population"],
            "aliases": ["population", "how many people"],
        },
        "languages": {
            "section": "PEOPLE AND SOCIETY",
            "labels": ["languages"],
            "aliases": ["languages", "spoken languages", "language"],
        },
        "religions": {
            "section": "PEOPLE AND SOCIETY",
            "labels": ["religions", "religion"],
            "aliases": ["religions", "religion", "faiths", "main religions"],
        },
        "ethnic groups": {
            "section": "PEOPLE AND SOCIETY",
            "labels": ["ethnic groups", "ethnicity"],
            "aliases": ["ethnic groups", "ethnicity", "ethnic makeup"],
        },
        "literacy": {
            "section": "PEOPLE AND SOCIETY",
            "labels": ["literacy"],
            "aliases": ["literacy", "literacy rate"],
        },
        "median age": {
            "section": "PEOPLE AND SOCIETY",
            "labels": ["median age"],
            "aliases": ["median age"],
        },
        "urbanization": {
            "section": "PEOPLE AND SOCIETY",
            "labels": ["urbanization"],
            "aliases": ["urbanization", "urbanized", "urbanised"],
        },
        "coastline": {
            "section": "GEOGRAPHY",
            "labels": ["coastline"],
            "aliases": ["coastline", "has a coastline"],
        },
        "climate": {
            "section": "GEOGRAPHY",
            "labels": ["climate"],
            "aliases": ["climate"],
        },
        "area": {
            "section": "GEOGRAPHY",
            "labels": ["area"],
            "aliases": ["area", "total area", "size"],
        },
    },
}


def load_reference_config(path: str | Path | None = None) -> Dict[str, Any]:
    cfg = dict(DEFAULT_REFERENCE_CONFIG)
    if path is None:
        return cfg
    p = Path(path).expanduser()
    if not p.exists():
        return cfg

    data: Dict[str, Any] = {}
    raw = p.read_text(encoding="utf-8")
    if p.suffix.lower() in (".yaml", ".yml"):
        try:
            import yaml  # type: ignore
        except Exception as e:  # pragma: no cover - optional dependency
            raise RuntimeError("YAML config requested but PyYAML is not installed.") from e
        parsed = yaml.safe_load(raw)
        if isinstance(parsed, dict):
            data = parsed
    else:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            data = parsed

    # Shallow merge with explicit nested merge for canonical_fields.
    merged = dict(cfg)
    merged.update(data)
    if isinstance(data.get("canonical_fields"), dict):
        cf = dict(cfg.get("canonical_fields", {}))
        cf.update(data.get("canonical_fields", {}))
        merged["canonical_fields"] = cf
    return merged
