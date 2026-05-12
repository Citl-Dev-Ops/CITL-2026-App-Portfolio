import json
from __future__ import annotations
import json
from pathlib import Path
from fastapi import APIRouter, HTTPException

def _safe_json_loads(s, label="json input"):
    """
    Fail-usefully wrapper around _safe_json_loads() that catches the common
    "Expecting value: line 1 column 1" case (empty/blank input).
    """
    if s is None:
        raise ValueError(f"{label} is None; cannot parse JSON.")
    if not str(s).strip():
        raise ValueError(f"{label} is empty/blank; cannot parse JSON.")
    try:
        return _safe_json_loads(s)
    except json.JSONDecodeError as e:
        head = str(s)[:300]
        raise ValueError(f"{label} is not valid JSON. First 300 chars: {head!r}") from e

router = APIRouter(tags=["baseline"])
BASELINE_DIR = Path(__file__).resolve().parents[1] / "data" / "baseline"
@router.get("/baseline/{name}")
def get_baseline(name: str):
    p = (BASELINE_DIR / name).with_suffix(".json")
    if not p.exists():
        raise HTTPException(404, f"Missing baseline file: {p}")
    return _safe_json_loads(p.read_text(encoding="utf-8"))

