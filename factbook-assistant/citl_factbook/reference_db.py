from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List, Optional


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = ROOT / "data" / "reference_corpora.sqlite"


def connect(db_path: str | Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    p = Path(db_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p))
    conn.row_factory = sqlite3.Row
    init_schema(conn)
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        PRAGMA foreign_keys = ON;

        CREATE TABLE IF NOT EXISTS corpora (
            corpus_name TEXT PRIMARY KEY,
            source_path TEXT NOT NULL,
            source_mtime REAL NOT NULL,
            source_size INTEGER NOT NULL,
            source_year INTEGER NOT NULL,
            mode TEXT NOT NULL,
            config_json TEXT NOT NULL,
            updated_at REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS entities (
            corpus_name TEXT NOT NULL,
            entity_name TEXT NOT NULL,
            aliases_json TEXT NOT NULL,
            data_json TEXT NOT NULL,
            PRIMARY KEY (corpus_name, entity_name),
            FOREIGN KEY (corpus_name) REFERENCES corpora(corpus_name) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS sections (
            corpus_name TEXT NOT NULL,
            entity_name TEXT NOT NULL,
            section_name TEXT NOT NULL,
            raw TEXT NOT NULL,
            PRIMARY KEY (corpus_name, entity_name, section_name),
            FOREIGN KEY (corpus_name, entity_name)
                REFERENCES entities(corpus_name, entity_name) ON DELETE CASCADE
        );
        """
    )
    try:
        conn.execute(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS sections_fts
            USING fts5(corpus_name, entity_name, section_name, raw, tokenize='unicode61 remove_diacritics 2');
            """
        )
    except sqlite3.OperationalError:
        # FTS unavailable; query layer will fall back to LIKE.
        pass
    conn.commit()


def corpus_meta(conn: sqlite3.Connection, corpus_name: str) -> Optional[Dict[str, Any]]:
    row = conn.execute("SELECT * FROM corpora WHERE corpus_name = ?", (corpus_name,)).fetchone()
    if not row:
        return None
    out = dict(row)
    try:
        out["config"] = json.loads(str(out.get("config_json") or "{}"))
    except Exception:
        out["config"] = {}
    return out


def upsert_corpus(
    conn: sqlite3.Connection,
    corpus_name: str,
    source_path: str,
    source_mtime: float,
    source_size: int,
    source_year: int,
    mode: str,
    config: Dict[str, Any],
) -> None:
    conn.execute(
        """
        INSERT INTO corpora(
            corpus_name, source_path, source_mtime, source_size, source_year, mode, config_json, updated_at
        )
        VALUES(?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(corpus_name) DO UPDATE SET
            source_path=excluded.source_path,
            source_mtime=excluded.source_mtime,
            source_size=excluded.source_size,
            source_year=excluded.source_year,
            mode=excluded.mode,
            config_json=excluded.config_json,
            updated_at=excluded.updated_at
        """,
        (
            corpus_name,
            source_path,
            float(source_mtime),
            int(source_size),
            int(source_year),
            mode,
            json.dumps(config, ensure_ascii=False),
            float(time.time()),
        ),
    )


def clear_corpus(conn: sqlite3.Connection, corpus_name: str) -> None:
    conn.execute("DELETE FROM sections WHERE corpus_name = ?", (corpus_name,))
    conn.execute("DELETE FROM entities WHERE corpus_name = ?", (corpus_name,))
    try:
        conn.execute("DELETE FROM sections_fts WHERE corpus_name = ?", (corpus_name,))
    except sqlite3.OperationalError:
        pass
    conn.commit()


def upsert_entity(
    conn: sqlite3.Connection,
    corpus_name: str,
    entity_name: str,
    aliases: List[str],
    data: Dict[str, Any],
) -> None:
    uniq_aliases = sorted({a.strip() for a in aliases if a and a.strip()})
    conn.execute(
        """
        INSERT INTO entities(corpus_name, entity_name, aliases_json, data_json)
        VALUES(?, ?, ?, ?)
        ON CONFLICT(corpus_name, entity_name) DO UPDATE SET
            aliases_json=excluded.aliases_json,
            data_json=excluded.data_json
        """,
        (
            corpus_name,
            entity_name,
            json.dumps(uniq_aliases, ensure_ascii=False),
            json.dumps(data, ensure_ascii=False),
        ),
    )


def upsert_section(
    conn: sqlite3.Connection,
    corpus_name: str,
    entity_name: str,
    section_name: str,
    raw: str,
) -> None:
    conn.execute(
        """
        INSERT INTO sections(corpus_name, entity_name, section_name, raw)
        VALUES(?, ?, ?, ?)
        ON CONFLICT(corpus_name, entity_name, section_name) DO UPDATE SET raw=excluded.raw
        """,
        (corpus_name, entity_name, section_name, raw),
    )


def rebuild_fts_for_corpus(conn: sqlite3.Connection, corpus_name: str) -> None:
    try:
        conn.execute("DELETE FROM sections_fts WHERE corpus_name = ?", (corpus_name,))
        conn.execute(
            """
            INSERT INTO sections_fts(corpus_name, entity_name, section_name, raw)
            SELECT corpus_name, entity_name, section_name, raw
            FROM sections
            WHERE corpus_name = ?
            """,
            (corpus_name,),
        )
    except sqlite3.OperationalError:
        # FTS not available.
        pass
    conn.commit()


def commit(conn: sqlite3.Connection) -> None:
    conn.commit()


def list_corpora(conn: sqlite3.Connection) -> List[str]:
    rows = conn.execute("SELECT corpus_name FROM corpora ORDER BY corpus_name").fetchall()
    return [str(r["corpus_name"]) for r in rows]


def alias_map(conn: sqlite3.Connection, corpus_name: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
    rows = conn.execute(
        "SELECT entity_name, aliases_json FROM entities WHERE corpus_name = ?",
        (corpus_name,),
    ).fetchall()
    for row in rows:
        entity = str(row["entity_name"])
        out.setdefault(entity, entity)
        aliases = []
        try:
            parsed = json.loads(str(row["aliases_json"] or "[]"))
            if isinstance(parsed, list):
                aliases = [str(x) for x in parsed]
        except Exception:
            aliases = []
        for alias in aliases:
            if alias and alias not in out:
                out[alias] = entity
    return out


def get_entity(conn: sqlite3.Connection, corpus_name: str, entity_name: str) -> Optional[Dict[str, Any]]:
    row = conn.execute(
        """
        SELECT entity_name, data_json
        FROM entities
        WHERE corpus_name = ? AND lower(entity_name) = lower(?)
        """,
        (corpus_name, entity_name),
    ).fetchone()
    if not row:
        return None
    try:
        data = json.loads(str(row["data_json"] or "{}"))
        if not isinstance(data, dict):
            data = {}
    except Exception:
        data = {}
    return {"entity_name": str(row["entity_name"]), "data": data}


def get_canonical_field(
    conn: sqlite3.Connection,
    corpus_name: str,
    entity_name: str,
    canonical_field: str,
) -> Optional[Dict[str, Any]]:
    ent = get_entity(conn, corpus_name, entity_name)
    if not ent:
        return None
    cf = ent["data"].get("canonical_fields")
    if not isinstance(cf, dict):
        return None
    item = cf.get(canonical_field)
    if not isinstance(item, dict):
        return None
    val = str(item.get("value") or "").strip()
    if not val:
        return None
    out = dict(item)
    out["value"] = val
    out["entity_name"] = ent["entity_name"]
    return out


def get_section_raw(conn: sqlite3.Connection, corpus_name: str, entity_name: str, section_name: str) -> str:
    row = conn.execute(
        """
        SELECT raw FROM sections
        WHERE corpus_name = ? AND lower(entity_name)=lower(?) AND lower(section_name)=lower(?)
        """,
        (corpus_name, entity_name, section_name),
    ).fetchone()
    if not row:
        return ""
    return str(row["raw"] or "")


def _fts_query(question: str) -> str:
    toks = [t for t in question.lower().split() if t.strip()]
    uniq: List[str] = []
    seen = set()
    for t in toks:
        if t in seen:
            continue
        seen.add(t)
        uniq.append(t)
    return " OR ".join(uniq[:12])


def search_sections(
    conn: sqlite3.Connection,
    corpus_name: str,
    entity_name: str,
    question: str,
    section_hint: Optional[str] = None,
    limit: int = 3,
) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    q = _fts_query(question)
    if not q:
        return out

    section_clause = ""
    params: List[Any] = [q, corpus_name, entity_name]
    if section_hint:
        section_clause = " AND lower(section_name)=lower(?)"
        params.append(section_hint)
    params.append(int(max(1, limit)))

    try:
        rows = conn.execute(
            (
                "SELECT corpus_name, entity_name, section_name, raw, "
                "snippet(sections_fts, 3, '[', ']', ' ... ', 28) AS snip "
                "FROM sections_fts "
                "WHERE sections_fts MATCH ? AND corpus_name = ? AND lower(entity_name)=lower(?)"
                + section_clause
                + " LIMIT ?"
            ),
            tuple(params),
        ).fetchall()
        for row in rows:
            out.append(
                {
                    "corpus_name": str(row["corpus_name"]),
                    "entity_name": str(row["entity_name"]),
                    "section_name": str(row["section_name"]),
                    "raw": str(row["raw"]),
                    "snippet": str(row["snip"] or ""),
                }
            )
        if out:
            return out
    except sqlite3.OperationalError:
        pass

    # LIKE fallback if FTS unavailable.
    like_term = "%"
    parts = [p for p in question.lower().split() if len(p) > 2]
    if parts:
        like_term = f"%{parts[0]}%"
    sql = (
        "SELECT corpus_name, entity_name, section_name, raw "
        "FROM sections WHERE corpus_name = ? AND lower(entity_name)=lower(?)"
    )
    params2: List[Any] = [corpus_name, entity_name]
    if section_hint:
        sql += " AND lower(section_name)=lower(?)"
        params2.append(section_hint)
    sql += " AND lower(raw) LIKE lower(?) LIMIT ?"
    params2.extend([like_term, int(max(1, limit))])
    rows = conn.execute(sql, tuple(params2)).fetchall()
    for row in rows:
        raw = str(row["raw"] or "")
        out.append(
            {
                "corpus_name": str(row["corpus_name"]),
                "entity_name": str(row["entity_name"]),
                "section_name": str(row["section_name"]),
                "raw": raw,
                "snippet": raw[:300],
            }
        )
    return out
