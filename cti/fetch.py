"""Feed fetching, article body extraction and keyword pre-filter."""
from __future__ import annotations

import calendar
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import feedparser
import requests
import trafilatura
import yaml

from cti import db

USER_AGENT = "cti-tracker/0.1 (+personal research)"


@dataclass
class FeedEntry:
    url: str
    title: str | None
    published_at: str | None
    summary: str


def _entry_date(entry) -> str | None:
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if not parsed:
        return None
    ts = calendar.timegm(parsed)
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def parse_feed(content: bytes | str) -> list[FeedEntry]:
    parsed = feedparser.parse(content)
    out = []
    for e in parsed.entries:
        link = e.get("link")
        if not link:
            continue
        out.append(FeedEntry(url=link, title=e.get("title"), published_at=_entry_date(e),
                             summary=e.get("summary", "") or ""))
    return out


def load_keywords(path: Path, conn: sqlite3.Connection) -> list[str]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    words = {str(w) for w in data.get("keywords", [])}
    for a in db.list_actors(conn):
        words.add(a["canonical_name"])
        words.update(a["aliases"])
    return sorted(w for w in words if w)


def classify(title: str | None, text: str | None, keywords: list[str]) -> str:
    hay = f"{title or ''}\n{text or ''}".lower()
    return "candidate" if any(k.lower() in hay for k in keywords) else "skip"


def get_feed(url: str) -> bytes:
    resp = requests.get(url, timeout=30, headers={"User-Agent": USER_AGENT})
    resp.raise_for_status()
    return resp.content


def extract_body(url: str, fallback: str) -> str:
    try:
        downloaded = trafilatura.fetch_url(url)
        text = trafilatura.extract(downloaded) if downloaded else None
    except Exception:  # noqa: BLE001
        text = None
    return text or fallback


def fetch_source(conn, source: sqlite3.Row, keywords: list[str], *, get_feed=get_feed,
                 get_body=extract_body) -> dict:
    stats = {"new": 0, "candidates": 0, "skipped": 0}
    for entry in parse_feed(get_feed(source["url"])):
        if conn.execute("SELECT 1 FROM articles WHERE url=?", (entry.url,)).fetchone():
            continue
        body = get_body(entry.url, entry.summary)
        relevance = classify(entry.title, body, keywords)
        inserted = db.insert_article(conn, source_id=source["id"], url=entry.url, title=entry.title,
                                     published_at=entry.published_at, lang=source["lang"], text=body,
                                     relevance=relevance)
        if inserted is None:
            continue
        stats["new"] += 1
        stats["candidates" if relevance == "candidate" else "skipped"] += 1
    return stats


def fetch_all(conn, keywords: list[str], *, get_feed=get_feed, get_body=extract_body, log=print) -> dict:
    total = {"new": 0, "candidates": 0, "skipped": 0, "sources_failed": 0}
    for src in conn.execute("SELECT * FROM sources WHERE enabled=1 ORDER BY id").fetchall():
        try:
            s = fetch_source(conn, src, keywords, get_feed=get_feed, get_body=get_body)
        except Exception as exc:  # noqa: BLE001
            total["sources_failed"] += 1
            log(f"[fetch] {src['name']} FAILED: {exc}")
            continue
        for k in ("new", "candidates", "skipped"):
            total[k] += s[k]
        log(f"[fetch] {src['name']}: +{s['new']} ({s['candidates']} candidates)")
    return total
