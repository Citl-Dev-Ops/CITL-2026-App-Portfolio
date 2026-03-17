from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional


HERE = Path(__file__).resolve().parent
DEFAULT_DB_PATH = HERE / "data" / "factbook_2023.sqlite"


def _norm_key(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (text or "").lower())


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

        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS countries (
            country_name TEXT PRIMARY KEY,
            iso2 TEXT,
            aliases TEXT NOT NULL,
            data TEXT NOT NULL,
            source_year INTEGER NOT NULL DEFAULT 2023
        );

        CREATE TABLE IF NOT EXISTS sections (
            country_name TEXT NOT NULL,
            section TEXT NOT NULL,
            raw TEXT NOT NULL,
            PRIMARY KEY (country_name, section),
            FOREIGN KEY (country_name) REFERENCES countries(country_name) ON DELETE CASCADE
        );
        """
    )

    try:
        conn.execute(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS sections_fts
            USING fts5(country_name, section, raw, tokenize='unicode61 remove_diacritics 2');
            """
        )
        conn.execute("INSERT INTO meta(key, value) VALUES('fts5_enabled', '1') ON CONFLICT(key) DO UPDATE SET value='1'")
    except sqlite3.OperationalError:
        conn.execute("INSERT INTO meta(key, value) VALUES('fts5_enabled', '0') ON CONFLICT(key) DO UPDATE SET value='0'")
    conn.commit()


def get_meta(conn: sqlite3.Connection, key: str, default: str = "") -> str:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    if not row:
        return default
    return str(row["value"])


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO meta(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, str(value)),
    )
    conn.commit()


def clear_factbook_tables(conn: sqlite3.Connection) -> None:
    conn.execute("DELETE FROM sections")
    conn.execute("DELETE FROM countries")
    if get_meta(conn, "fts5_enabled", "0") == "1":
        conn.execute("DELETE FROM sections_fts")
    conn.commit()


def upsert_country(
    conn: sqlite3.Connection,
    country_name: str,
    aliases: List[str],
    data: Dict[str, Any],
    source_year: int = 2023,
    iso2: str = "",
) -> None:
    conn.execute(
        """
        INSERT INTO countries(country_name, iso2, aliases, data, source_year)
        VALUES(?, ?, ?, ?, ?)
        ON CONFLICT(country_name) DO UPDATE SET
            iso2=excluded.iso2,
            aliases=excluded.aliases,
            data=excluded.data,
            source_year=excluded.source_year
        """,
        (
            country_name,
            iso2,
            json.dumps(sorted({a.strip() for a in aliases if a and a.strip()}), ensure_ascii=False),
            json.dumps(data, ensure_ascii=False),
            int(source_year),
        ),
    )


def upsert_section(conn: sqlite3.Connection, country_name: str, section: str, raw: str) -> None:
    conn.execute(
        """
        INSERT INTO sections(country_name, section, raw)
        VALUES(?, ?, ?)
        ON CONFLICT(country_name, section) DO UPDATE SET raw=excluded.raw
        """,
        (country_name, section, raw),
    )


def rebuild_sections_fts(conn: sqlite3.Connection) -> None:
    if get_meta(conn, "fts5_enabled", "0") != "1":
        return
    conn.execute("DELETE FROM sections_fts")
    conn.execute(
        """
        INSERT INTO sections_fts(country_name, section, raw)
        SELECT country_name, section, raw FROM sections
        """
    )
    conn.commit()


def commit(conn: sqlite3.Connection) -> None:
    conn.commit()


def country_alias_map(conn: sqlite3.Connection) -> Dict[str, str]:
    out: Dict[str, str] = {}
    rows = conn.execute("SELECT country_name, aliases FROM countries").fetchall()
    for row in rows:
        name = str(row["country_name"])
        aliases: List[str] = []
        try:
            raw = json.loads(str(row["aliases"] or "[]"))
            if isinstance(raw, list):
                aliases = [str(x) for x in raw]
        except Exception:
            aliases = []
        aliases.append(name)
        for alias in aliases:
            nk = _norm_key(alias)
            if nk and nk not in out:
                out[nk] = name
    return out


def country_alias_strings(conn: sqlite3.Connection) -> Dict[str, str]:
    out: Dict[str, str] = {}
    rows = conn.execute("SELECT country_name, aliases FROM countries").fetchall()
    for row in rows:
        name = str(row["country_name"])
        out.setdefault(name, name)
        aliases: List[str] = []
        try:
            raw = json.loads(str(row["aliases"] or "[]"))
            if isinstance(raw, list):
                aliases = [str(x) for x in raw]
        except Exception:
            aliases = []
        for alias in aliases:
            a = alias.strip()
            if a and a not in out:
                out[a] = name
    return out


def resolve_country(conn: sqlite3.Connection, text: str) -> Optional[str]:
    nk = _norm_key(text)
    if not nk:
        return None
    amap = country_alias_map(conn)
    return amap.get(nk)


def get_country(conn: sqlite3.Connection, country_name: str) -> Optional[Dict[str, Any]]:
    row = conn.execute(
        "SELECT country_name, aliases, data, source_year FROM countries WHERE lower(country_name)=lower(?)",
        (country_name,),
    ).fetchone()
    if not row:
        return None
    try:
        aliases = json.loads(str(row["aliases"] or "[]"))
        if not isinstance(aliases, list):
            aliases = []
    except Exception:
        aliases = []
    try:
        data = json.loads(str(row["data"] or "{}"))
        if not isinstance(data, dict):
            data = {}
    except Exception:
        data = {}
    return {
        "country_name": str(row["country_name"]),
        "aliases": [str(x) for x in aliases],
        "data": data,
        "source_year": int(row["source_year"] or 0),
    }


def get_canonical_field(conn: sqlite3.Connection, country_name: str, canonical_field: str) -> Optional[Dict[str, Any]]:
    row = get_country(conn, country_name)
    if not row:
        return None
    data = row.get("data") or {}
    cf = data.get("canonical_fields") if isinstance(data, dict) else None
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
    out["country_name"] = row["country_name"]
    out["source_year"] = row["source_year"]
    return out


def _fts_query_from_question(question: str) -> str:
    toks = re.findall(r"[a-zA-Z0-9]+", (question or "").lower())
    if not toks:
        return ""
    uniq: List[str] = []
    seen = set()
    for t in toks:
        if t in seen:
            continue
        seen.add(t)
        uniq.append(t)
    # OR query is tolerant to noisy student phrasing.
    return " OR ".join(uniq[:10])


def search_sections(
    conn: sqlite3.Connection,
    country_name: str,
    question: str,
    section: Optional[str] = None,
    limit: int = 3,
) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    query = _fts_query_from_question(question)
    if not query:
        return out

    section_clause = ""
    params: List[Any] = [query, country_name]
    if section:
        section_clause = " AND lower(section) = lower(?)"
        params.append(section)
    params.append(int(max(1, limit)))

    if get_meta(conn, "fts5_enabled", "0") == "1":
        sql = (
            "SELECT country_name, section, raw, snippet(sections_fts, 2, '[', ']', ' ... ', 28) AS snip "
            "FROM sections_fts WHERE sections_fts MATCH ? AND lower(country_name)=lower(?)"
            + section_clause
            + " LIMIT ?"
        )
        try:
            rows = conn.execute(sql, tuple(params)).fetchall()
            for row in rows:
                out.append(
                    {
                        "country_name": str(row["country_name"]),
                        "section": str(row["section"]),
                        "raw": str(row["raw"]),
                        "snippet": str(row["snip"] or ""),
                    }
                )
            return out
        except sqlite3.OperationalError:
            # Fall back to LIKE below.
            pass

    like_term = "%"
    toks = [t for t in re.findall(r"[a-zA-Z0-9]+", (question or "").lower()) if len(t) > 2]
    if toks:
        like_term = f"%{toks[0]}%"

    sql = (
        "SELECT country_name, section, raw FROM sections "
        "WHERE lower(country_name)=lower(?)"
    )
    params2: List[Any] = [country_name]
    if section:
        sql += " AND lower(section)=lower(?)"
        params2.append(section)
    sql += " AND lower(raw) LIKE lower(?) LIMIT ?"
    params2.extend([like_term, int(max(1, limit))])
    rows = conn.execute(sql, tuple(params2)).fetchall()
    for row in rows:
        raw = str(row["raw"])
        out.append(
            {
                "country_name": str(row["country_name"]),
                "section": str(row["section"]),
                "raw": raw,
                "snippet": raw[:280],
            }
        )
    return out
