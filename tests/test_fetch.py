from pathlib import Path

import pytest

from cti import db, fetch

FIX = Path(__file__).parent / "fixtures"


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "t.db")
    db.init_schema(c)
    db.get_or_create_actor(c, "APT41", aliases=["Brass Typhoon"])
    return c


def test_parse_feed_returns_entries_with_iso_dates():
    entries = fetch.parse_feed((FIX / "feed.xml").read_bytes())
    assert len(entries) == 3
    assert entries[0].url == "https://ex.com/a"
    assert entries[0].published_at == "2026-08-30T08:00:00+00:00"
    assert "Living off the land" in entries[0].summary


def test_load_keywords_merges_yaml_and_actor_aliases(tmp_path, conn):
    kw = tmp_path / "k.yaml"
    kw.write_text("keywords:\n  - China\n  - 境外\n")
    words = fetch.load_keywords(kw, conn)
    assert {"China", "境外", "APT41", "Brass Typhoon"} <= set(words)


def test_classify_is_case_insensitive_and_matches_chinese():
    kws = ["China", "境外黑客"]
    assert fetch.classify("CHINA-linked group", "", kws) == "candidate"
    assert fetch.classify("某单位", "遭境外黑客攻击", kws) == "candidate"
    assert fetch.classify("Ransomware hits hospital", "no link", kws) == "skip"


def test_fetch_source_inserts_dedupes_and_classifies(conn):
    sid = db.upsert_source(conn, "T", "https://ex.com/feed", "en", "news")
    src = conn.execute("select * from sources where id=?", (sid,)).fetchone()
    kws = ["Typhoon", "境外黑客"]
    get_feed = lambda url: (FIX / "feed.xml").read_bytes()
    get_body = lambda url, fallback: f"BODY:{fallback}"
    stats = fetch.fetch_source(conn, src, kws, get_feed=get_feed, get_body=get_body)
    assert stats == {"new": 3, "candidates": 2, "skipped": 1}
    row = conn.execute("select text, relevance from articles where url='https://ex.com/a'").fetchone()
    assert row["text"].startswith("BODY:") and row["relevance"] == "candidate"
    # second run: nothing new, body fetch not called for known urls
    calls = []
    stats = fetch.fetch_source(conn, src, kws, get_feed=get_feed, get_body=lambda u, f: calls.append(u) or "x")
    assert stats == {"new": 0, "candidates": 0, "skipped": 0}
    assert calls == []


def test_fetch_all_skips_disabled_and_survives_source_errors(conn):
    db.upsert_source(conn, "ok", "https://ex.com/feed", "en", "news")
    db.upsert_source(conn, "broken", "https://ex.com/broken", "en", "news")
    db.upsert_source(conn, "off", "https://ex.com/off", "en", "news", enabled=False)

    def get_feed(url):
        if "broken" in url:
            raise RuntimeError("boom")
        return (FIX / "feed.xml").read_bytes()

    logs = []
    stats = fetch.fetch_all(conn, ["Typhoon"], get_feed=get_feed, get_body=lambda u, f: f, log=logs.append)
    assert stats["new"] == 3 and stats["sources_failed"] == 1
    assert any("broken" in m for m in logs)
    assert conn.execute("select count(*) from articles").fetchone()[0] == 3
