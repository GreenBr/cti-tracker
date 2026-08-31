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


def latest_update(conn) -> dict:
    """The most recent update batch (never empty once data exists), not calendar-today."""
    incident_date = conn.execute("SELECT date(max(created_at)) FROM incidents").fetchone()[0]
    fetch_date = conn.execute(
        "SELECT date(max(fetched_at)) FROM articles WHERE relevance='candidate'").fetchone()[0]
    incidents = _rows(conn, """
        SELECT i.id, i.title, i.direction, i.created_at, i.article_id, a.canonical_name AS actor
        FROM incidents i LEFT JOIN actors a ON a.id = i.actor_id
        WHERE date(i.created_at) = ? ORDER BY i.created_at DESC""", (incident_date,))
    articles = _rows(conn, """
        SELECT ar.id, ar.title, ar.fetched_at, ar.extract_status, s.name AS source
        FROM articles ar JOIN sources s ON s.id = ar.source_id
        WHERE date(ar.fetched_at) = ? AND ar.relevance = 'candidate' ORDER BY ar.fetched_at DESC""", (fetch_date,))
    return {"incidents": incidents, "articles": articles, "incident_date": incident_date, "fetch_date": fetch_date}


def actors(conn) -> list[dict]:
    rows = _rows(conn, """
        SELECT a.id, a.canonical_name, a.aliases, a.mitre_id, a.attributed_country,
               (SELECT count(*) FROM incidents i WHERE i.actor_id = a.id) AS incident_count,
               (SELECT max(i.reported_at) FROM incidents i WHERE i.actor_id = a.id) AS last_reported
        FROM actors a ORDER BY incident_count DESC, a.canonical_name""")
    for r in rows:
        r["aliases"] = json.loads(r["aliases"] or "[]")
    return rows


def actor(conn, actor_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM actors WHERE id=?", (actor_id,)).fetchone()
    if not row:
        return None
    d = dict(row)
    d["aliases"] = json.loads(d["aliases"] or "[]")
    return d


def actor_incidents(conn, actor_id: int) -> list[dict]:
    return _rows(conn, """
        SELECT i.*, ar.title AS article_title FROM incidents i JOIN articles ar ON ar.id = i.article_id
        WHERE i.actor_id = ? ORDER BY i.reported_at DESC, i.id DESC""", (actor_id,))


def actor_ttps(conn, actor_id: int) -> list[dict]:
    return _rows(conn, """
        SELECT t.technique_id, t.technique_name, count(*) AS n
        FROM incident_ttps t JOIN incidents i ON i.id = t.incident_id
        WHERE i.actor_id = ? GROUP BY t.technique_id, t.technique_name ORDER BY n DESC, t.technique_id""", (actor_id,))


def actor_sectors(conn, actor_id: int) -> list[dict]:
    return _rows(conn, """
        SELECT coalesce(victim_sector, '') AS sector, count(*) AS n FROM incidents
        WHERE actor_id = ? GROUP BY sector ORDER BY n DESC, sector""", (actor_id,))


def filter_options(conn) -> dict:
    return {
        "countries": [r["victim_country"] for r in conn.execute(
            "SELECT DISTINCT victim_country FROM incidents WHERE victim_country IS NOT NULL ORDER BY 1")],
        "sectors": [r["victim_sector"] for r in conn.execute(
            "SELECT DISTINCT victim_sector FROM incidents WHERE victim_sector IS NOT NULL ORDER BY 1")],
        "actors": _rows(conn, "SELECT id, canonical_name FROM actors WHERE id IN (SELECT actor_id FROM incidents) ORDER BY 2"),
    }


def incidents(conn, *, direction=None, country=None, sector=None, actor_id=None, q=None, page=1,
              per_page=50) -> tuple[list[dict], int]:
    where, params = [], []
    if direction:
        where.append("i.direction = ?"); params.append(direction)
    if country:
        where.append("i.victim_country = ?"); params.append(country)
    if sector:
        where.append("i.victim_sector = ?"); params.append(sector)
    if actor_id:
        where.append("i.actor_id = ?"); params.append(actor_id)
    if q:
        where.append("(i.article_id IN (SELECT rowid FROM articles_fts WHERE articles_fts MATCH ?) "
                     "OR i.title LIKE ? OR i.summary LIKE ?)")
        params += [q, f"%{q}%", f"%{q}%"]
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    total = conn.execute(f"SELECT count(*) FROM incidents i {clause}", params).fetchone()[0]
    rows = _rows(conn, f"""
        SELECT i.*, a.canonical_name AS actor, ar.title AS article_title
        FROM incidents i LEFT JOIN actors a ON a.id = i.actor_id JOIN articles ar ON ar.id = i.article_id
        {clause} ORDER BY i.reported_at DESC, i.id DESC LIMIT ? OFFSET ?""",
        [*params, per_page, (page - 1) * per_page])
    return rows, total


def incident(conn, incident_id: int) -> dict | None:
    row = conn.execute("""
        SELECT i.*, a.canonical_name AS actor, ar.title AS article_title, ar.url AS article_url
        FROM incidents i LEFT JOIN actors a ON a.id = i.actor_id JOIN articles ar ON ar.id = i.article_id
        WHERE i.id = ?""", (incident_id,)).fetchone()
    if not row:
        return None
    d = dict(row)
    d["ttps"] = _rows(conn, "SELECT technique_id, technique_name FROM incident_ttps WHERE incident_id=? ORDER BY 1",
                      (incident_id,))
    return d


def article(conn, article_id: int) -> dict | None:
    row = conn.execute("""
        SELECT ar.*, s.name AS source_name, s.type AS source_type FROM articles ar JOIN sources s ON s.id = ar.source_id
        WHERE ar.id = ?""", (article_id,)).fetchone()
    return dict(row) if row else None


def article_incidents(conn, article_id: int) -> list[dict]:
    return _rows(conn, """
        SELECT i.*, a.canonical_name AS actor FROM incidents i LEFT JOIN actors a ON a.id = i.actor_id
        WHERE i.article_id = ? ORDER BY i.id""", (article_id,))


def article_actors(conn, article_id: int) -> list[dict]:
    return _rows(conn, """
        SELECT a.id, a.canonical_name FROM article_actors x JOIN actors a ON a.id = x.actor_id
        WHERE x.article_id = ? ORDER BY 2""", (article_id,))


def trend_per_month(conn) -> list[dict]:
    return _rows(conn, """
        SELECT substr(coalesce(occurred_at, reported_at), 1, 7) AS month, count(*) AS n
        FROM incidents WHERE coalesce(occurred_at, reported_at) IS NOT NULL GROUP BY month ORDER BY month""")


def trend_direction(conn) -> list[dict]:
    counts = {r["direction"]: r["n"] for r in conn.execute("SELECT direction, count(*) AS n FROM incidents GROUP BY 1")}
    return [{"direction": d, "n": counts.get(d, 0)} for d in ("from_cn", "to_cn", "unclear")]


def trend_sectors(conn, limit: int = 10) -> list[dict]:
    return _rows(conn, """
        SELECT victim_sector AS sector, count(*) AS n FROM incidents WHERE victim_sector IS NOT NULL
        GROUP BY 1 ORDER BY n DESC, 1 LIMIT ?""", (limit,))


def trend_ttps(conn, limit: int = 10) -> list[dict]:
    return _rows(conn, """
        SELECT technique_id, technique_name, count(*) AS n FROM incident_ttps
        GROUP BY 1, 2 ORDER BY n DESC, 1 LIMIT ?""", (limit,))


def data_status(conn) -> dict:
    row = conn.execute("""
        SELECT (SELECT max(fetched_at) FROM articles) AS last_fetch,
               (SELECT max(extracted_at) FROM articles WHERE extract_status='done') AS last_extract,
               (SELECT max(created_at) FROM incidents) AS last_incident""").fetchone()
    return dict(row)
