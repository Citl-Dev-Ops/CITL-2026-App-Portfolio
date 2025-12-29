import os
import json
from pathlib import Path
from typing import List, Dict
INDEX_PATH = Path(os.environ.get("CITL_FACTBOOK_INDEX", "data/factbook_index.jsonl"))
def load_index() -> List[Dict]:
    if not INDEX_PATH.exists():
        return []
    out = []
    with INDEX_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out
def retrieve(query: str, k: int = 6) -> List[Dict]:
    # basic keyword scoring so you have something working now
    q = set(query.lower().split())
    docs = load_index()
    scored = []
    for d in docs:
        text = (d.get("title","") + " " + d.get("text","")).lower()
        score = sum(1 for w in q if w in text)
        if score:
            scored.append((score, d))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [d for _, d in scored[:k]]
