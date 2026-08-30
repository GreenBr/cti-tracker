import pytest

from cti import db


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "t.db")
    db.init_schema(c)
    return c


def test_init_schema_creates_tables_and_is_idempotent(conn):
    db.init_schema(conn)  # second call must not raise
    names = {r["name"] for r in conn.execute("select name from sqlite_master where type in ('table','view')")}
    for t in ["sources", "articles", "actors", "incidents", "incident_ttps", "article_actors", "articles_fts"]:
        assert t in names


def test_upsert_source_is_idempotent(conn):
    a = db.upsert_source(conn, "X", "https://x/feed", "en", "news")
    b = db.upsert_source(conn, "X renamed", "https://x/feed", "en", "news")
    assert a == b
    row = conn.execute("select name from sources where id=?", (a,)).fetchone()
    assert row["name"] == "X renamed"


def test_insert_article_dedupes_on_url(conn):
    sid = db.upsert_source(conn, "X", "https://x/feed", "en", "news")
    first = db.insert_article(conn, source_id=sid, url="https://x/a", title="t", published_at="2026-08-30T00:00:00",
                              lang="en", text="body", relevance="candidate")
    second = db.insert_article(conn, source_id=sid, url="https://x/a", title="t", published_at="2026-08-30T00:00:00",
                               lang="en", text="body", relevance="candidate")
    assert first is not None and second is None
    row = conn.execute("select extract_status from articles where id=?", (first,)).fetchone()
    assert row["extract_status"] == "pending"


def test_fts_indexes_article_text(conn):
    sid = db.upsert_source(conn, "X", "https://x/feed", "en", "news")
    db.insert_article(conn, source_id=sid, url="https://x/a", title="Volt Typhoon hits utility",
                      published_at=None, lang="en", text="living off the land", relevance="candidate")
    hits = conn.execute("select rowid from articles_fts where articles_fts match 'typhoon'").fetchall()
    assert len(hits) == 1


def test_resolve_actor_matches_canonical_and_alias_case_insensitive(conn):
    aid, created = db.get_or_create_actor(conn, "APT41", aliases=["Winnti", "Brass Typhoon"], mitre_id="G0096")
    assert created is True
    assert db.resolve_actor(conn, "apt41") == aid
    assert db.resolve_actor(conn, "brass typhoon") == aid
    assert db.resolve_actor(conn, "Nobody") is None


def test_get_or_create_actor_returns_existing_on_alias(conn):
    aid, _ = db.get_or_create_actor(conn, "APT41", aliases=["Winnti"])
    same, created = db.get_or_create_actor(conn, "winnti")
    assert same == aid and created is False
    assert conn.execute("select count(*) from actors").fetchone()[0] == 1


def test_list_actors_returns_alias_lists(conn):
    db.get_or_create_actor(conn, "APT41", aliases=["Winnti"])
    rows = db.list_actors(conn)
    assert rows[0]["canonical_name"] == "APT41"
    assert rows[0]["aliases"] == ["Winnti"]
