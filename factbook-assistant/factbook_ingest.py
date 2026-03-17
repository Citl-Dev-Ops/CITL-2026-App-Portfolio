from __future__ import annotations

import argparse
import time
from pathlib import Path
from typing import Dict

import factbook_db as db
from parsers import parse_factbook_text


HERE = Path(__file__).resolve().parent
DEFAULT_SOURCE = HERE / "factbook.txt"


def _source_fingerprint(path: Path) -> Dict[str, str]:
    st = path.stat()
    return {
        "source_path": str(path.resolve()),
        "source_mtime": str(int(st.st_mtime)),
        "source_size": str(int(st.st_size)),
    }


def needs_reingest(conn, source_path: Path, source_year: int) -> bool:
    fp = _source_fingerprint(source_path)
    for k, v in fp.items():
        if db.get_meta(conn, k, "") != v:
            return True
    if db.get_meta(conn, "source_year", "") != str(int(source_year)):
        return True
    row = conn.execute("SELECT COUNT(*) AS n FROM countries").fetchone()
    count = int(row["n"] if row else 0)
    return count == 0


def ingest_factbook(
    source_path: str | Path = DEFAULT_SOURCE,
    db_path: str | Path = db.DEFAULT_DB_PATH,
    source_year: int = 2023,
    force: bool = False,
) -> Dict[str, int]:
    src = Path(source_path).expanduser().resolve()
    if not src.exists():
        raise FileNotFoundError(f"Factbook source missing: {src}")

    conn = db.connect(db_path)
    try:
        if not force and not needs_reingest(conn, src, source_year):
            row = conn.execute("SELECT COUNT(*) AS n FROM countries").fetchone()
            existing = int(row["n"] if row else 0)
            return {"countries": existing, "sections": 0, "reingested": 0}

        raw = src.read_text(encoding="utf-8", errors="ignore")
        records = parse_factbook_text(raw)

        db.clear_factbook_tables(conn)

        section_count = 0
        for rec in records:
            payload = {
                "canonical_fields": rec.canonical_fields,
                "section_fields": rec.section_fields,
            }
            db.upsert_country(
                conn,
                country_name=rec.country_name,
                aliases=rec.aliases,
                data=payload,
                source_year=source_year,
            )
            for section_name, section_raw in rec.sections.items():
                db.upsert_section(conn, rec.country_name, section_name, section_raw)
                section_count += 1

        db.commit(conn)
        db.rebuild_sections_fts(conn)

        fp = _source_fingerprint(src)
        for k, v in fp.items():
            db.set_meta(conn, k, v)
        db.set_meta(conn, "source_year", str(int(source_year)))
        db.set_meta(conn, "last_ingest_epoch", str(int(time.time())))

        return {"countries": len(records), "sections": section_count, "reingested": 1}
    finally:
        conn.close()


def main() -> None:
    ap = argparse.ArgumentParser(description="Build entity-locked SQLite/FTS index from Factbook text.")
    ap.add_argument("--src", default=str(DEFAULT_SOURCE), help="Path to factbook text file")
    ap.add_argument("--db", default=str(db.DEFAULT_DB_PATH), help="Output SQLite DB path")
    ap.add_argument("--source-year", type=int, default=2023, help="Source year metadata")
    ap.add_argument("--force", action="store_true", help="Force re-ingestion even if source is unchanged")
    args = ap.parse_args()

    stats = ingest_factbook(
        source_path=args.src,
        db_path=args.db,
        source_year=int(args.source_year),
        force=bool(args.force),
    )
    print(
        f"[factbook_ingest] countries={stats['countries']} "
        f"sections={stats['sections']} reingested={stats['reingested']} db={args.db}"
    )


if __name__ == "__main__":
    main()
