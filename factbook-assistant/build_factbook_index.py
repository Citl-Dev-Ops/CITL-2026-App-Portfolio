import json
from pathlib import Path
RAW = Path("data/factbook_raw")
OUT = Path("data/factbook_index.jsonl")
OUT.parent.mkdir(parents=True, exist_ok=True)
def chunk(text: str, max_chars: int = 2500):
    text = text.replace("\r\n", "\n")
    parts = [p.strip() for p in text.split("\n\n") if p.strip()]
    buf, n = [], 0
    for p in parts:
        if n + len(p) > max_chars and buf:
            yield "\n\n".join(buf)
            buf, n = [], 0
        buf.append(p); n += len(p)
    if buf:
        yield "\n\n".join(buf)
def main():
    if not RAW.exists():
        raise SystemExit("Missing data/factbook_raw")
    with OUT.open("w", encoding="utf-8") as w:
        for fp in sorted(RAW.glob("*.txt")):
            title = fp.stem
            text = fp.read_text(encoding="utf-8", errors="ignore")
            for i, c in enumerate(chunk(text), 1):
                w.write(json.dumps({"id": f"{title}:{i}", "title": title, "text": c}, ensure_ascii=False) + "\n")
    print(f"Wrote {OUT}")
if __name__ == "__main__":
    main()
