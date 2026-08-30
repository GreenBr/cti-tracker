"""SQLite schema and write helpers for cti-tracker."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    url TEXT NOT NULL UNIQUE,
    lang TEXT NOT NULL,
    type TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS articles (
    id INTEGER PRIMARY KEY,
    source_id INTEGER NOT NULL REFERENCES sources(id),
    url TEXT NOT NULL UNIQUE,
    title TEXT,
    published_at TEXT,
    fetched_at TEXT NOT NULL,
    lang TEXT,
    text TEXT,
    relevance TEXT NOT NULL DEFAULT 'pending',
    extract_status TEXT NOT NULL DEFAULT 'pending',
    extract_error TEXT,
    extracted_at TEXT
);
CREATE TABLE IF NOT EXISTS actors (
    id INTEGER PRIMARY KEY,
    canonical_name TEXT NOT NULL UNIQUE,
    aliases TEXT NOT NULL DEFAULT '[]',
    attributed_country TEXT,
    mitre_id TEXT,
    description TEXT
);
CREATE TABLE IF NOT EXISTS incidents (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    summary TEXT,
    occurred_at TEXT,
    reported_at TEXT,
    direction TEXT NOT NULL CHECK (direction IN ('from_cn','to_cn','unclear')),
    actor_id INTEGER REFERENCES actors(id),
    victim_country TEXT,
    victim_sector TEXT,
    confidence TEXT CHECK (confidence IN ('high','medium','low')),
    article_id INTEGER NOT NULL REFERENCES articles(id),
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS incident_ttps (
    incident_id INTEGER NOT NULL REFERENCES incidents(id),
    technique_id TEXT NOT NULL,
    technique_name TEXT,
    PRIMARY KEY (incident_id, technique_id)
);
CREATE TABLE IF NOT EXISTS article_actors (
    article_id INTEGER NOT NULL REFERENCES articles(id),
    actor_id INTEGER NOT NULL REFERENCES actors(id),
    PRIMARY KEY (article_id, actor_id)
);
CREATE VIRTUAL TABLE IF NOT EXISTS articles_fts USING fts5(
    title, text, content='articles', content_rowid='id'
);
CREATE TRIGGER IF NOT EXISTS articles_ai AFTER INSERT ON articles BEGIN
    INSERT INTO articles_fts(rowid, title, text) VALUES (new.id, new.title, new.text);
END;
CREATE TRIGGER IF NOT EXISTS articles_ad AFTER DELETE ON articles BEGIN
    INSERT INTO articles_fts(articles_fts, rowid, title, text) VALUES ('delete', old.id, old.title, old.text);
END;
CREATE TRIGGER IF NOT EXISTS articles_au AFTER UPDATE OF title, text ON articles BEGIN
    INSERT INTO articles_fts(articles_fts, rowid, title, text) VALUES ('delete', old.id, old.title, old.text);
    INSERT INTO articles_fts(rowid, title, text) VALUES (new.id, new.title, new.text);
END;
CREATE INDEX IF NOT EXISTS idx_articles_status ON articles(relevance, extract_status);
CREATE INDEX IF NOT EXISTS idx_incidents_reported ON incidents(reported_at);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def connect(path: str | Path) -> sqlite3.Connection:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


def upsert_source(conn, name: str, url: str, lang: str, type: str, enabled: bool = True) -> int:
    conn.execute(
        """INSERT INTO sources(name, url, lang, type, enabled) VALUES (?,?,?,?,?)
           ON CONFLICT(url) DO UPDATE SET name=excluded.name, lang=excluded.lang,
                                          type=excluded.type, enabled=excluded.enabled""",
        (name, url, lang, type, 1 if enabled else 0),
    )
    conn.commit()
    return conn.execute("SELECT id FROM sources WHERE url=?", (url,)).fetchone()["id"]


def disable_sources_not_in(conn, urls: list[str]) -> int:
    """Disable sources whose url is no longer listed (e.g. URL changed in sources.yaml)."""
    placeholders = ",".join("?" * len(urls)) or "''"
    cur = conn.execute(f"UPDATE sources SET enabled=0 WHERE enabled=1 AND url NOT IN ({placeholders})", urls)
    conn.commit()
    return cur.rowcount


def insert_article(conn, *, source_id: int, url: str, title: str | None, published_at: str | None,
                   lang: str | None, text: str | None, relevance: str) -> int | None:
    cur = conn.execute(
        """INSERT OR IGNORE INTO articles(source_id, url, title, published_at, fetched_at, lang, text, relevance)
           VALUES (?,?,?,?,?,?,?,?)""",
        (source_id, url, title, published_at, now_iso(), lang, text, relevance),
    )
    conn.commit()
    return cur.lastrowid if cur.rowcount == 1 else None


def list_actors(conn) -> list[dict]:
    rows = conn.execute("SELECT id, canonical_name, aliases FROM actors ORDER BY canonical_name").fetchall()
    return [{"id": r["id"], "canonical_name": r["canonical_name"], "aliases": json.loads(r["aliases"])} for r in rows]


def resolve_actor(conn, name: str) -> int | None:
    needle = name.strip().lower()
    if not needle:
        return None
    for a in list_actors(conn):
        if a["canonical_name"].lower() == needle:
            return a["id"]
        if any(al.lower() == needle for al in a["aliases"]):
            return a["id"]
    return None


def get_or_create_actor(conn, name: str, aliases=(), attributed_country=None, mitre_id=None,
                        description=None) -> tuple[int, bool]:
    existing = resolve_actor(conn, name)
    if existing is not None:
        return existing, False
    cur = conn.execute(
        "INSERT INTO actors(canonical_name, aliases, attributed_country, mitre_id, description) VALUES (?,?,?,?,?)",
        (name.strip(), json.dumps(sorted(set(aliases))), attributed_country, mitre_id, description),
    )
    conn.commit()
    return cur.lastrowid, True
