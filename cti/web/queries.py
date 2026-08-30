"""Read-only SQL for the web UI."""
from __future__ import annotations

import json
import sqlite3


def _rows(conn: sqlite3.Connection, sql: str, params=()) -> list[dict]:
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def stats(conn) -> dict:
    return {
        "articles": conn.execute("SELECT count(*) FROM articles").fetchone()[0],
        "candidates": conn.execute("SELECT count(*) FROM articles WHERE relevance='candidate'").fetchone()[0],
        "incidents": conn.execute("SELECT count(*) FROM incidents").fetchone()[0],
        "actors": conn.execute("SELECT count(*) FROM actors").fetchone()[0],
    }


def new_today(conn) -> dict:
    incidents = _rows(conn, """
        SELECT i.id, i.title, i.direction, i.created_at, i.article_id, a.canonical_name AS actor
        FROM incidents i LEFT JOIN actors a ON a.id = i.actor_id
        WHERE date(i.created_at) = date('now') ORDER BY i.created_at DESC""")
    articles = _rows(conn, """
        SELECT ar.id, ar.title, ar.fetched_at, ar.extract_status, s.name AS source
        FROM articles ar JOIN sources s ON s.id = ar.source_id
        WHERE date(ar.fetched_at) = date('now') AND ar.relevance = 'candidate' ORDER BY ar.fetched_at DESC""")
    return {"incidents": incidents, "articles": articles}
