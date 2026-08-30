import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from cti import db, extract
from cti.web.app import create_app

FIX = Path(__file__).parent / "fixtures"


@pytest.fixture
def client(tmp_path):
    dbfile = tmp_path / "cti.db"
    c = db.connect(dbfile)
    db.init_schema(c)
    db.get_or_create_actor(c, "APT41", aliases=["Brass Typhoon", "Winnti"], mitre_id="G0096", description="APT41 desc")
    sid = db.upsert_source(c, "Test Source", "https://ex.com/feed", "en", "news")
    aid = db.insert_article(c, source_id=sid, url="https://ex.com/1", title="Volt Typhoon report",
                            published_at="2026-08-30T00:00:00+00:00", lang="en", text="living off the land in Guam",
                            relevance="candidate")
    extract.write_extraction(c, aid, json.loads((FIX / "claude_ok.json").read_text()), "2026-08-30T00:00:00+00:00")
    c.close()
    return TestClient(create_app(dbfile))


def test_index_renders_english_by_default(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "<html lang=\"en\"" in r.text
    assert "New incidents today" in r.text
    assert "APT41 spearphishing" in r.text  # incident created 'today' in fixture


def test_lang_query_sets_cookie_and_is_remembered(client):
    r = client.get("/?lang=zh_TW")
    assert r.status_code == 200
    assert r.headers["content-language"] == "zh"
    assert "lang=zh_TW" in r.headers.get("set-cookie", "")
    r2 = client.get("/")  # cookie jar persists in TestClient
    assert "<html lang=\"zh\"" in r2.text


def test_accept_language_negotiation(client):
    for header, expected in [("zh-TW,zh;q=0.9", "zh_TW"), ("zh-CN", "zh_CN"), ("en-US,en;q=0.8", "en"), ("ja", "en")]:
        r = client.get("/", headers={"Accept-Language": header})
        assert r.status_code == 200
        assert f'<option value="{expected}" selected>' in r.text, (header, expected)


def test_switcher_offers_native_names(client):
    r = client.get("/")
    assert "中文 (简体)" in r.text and "中文 (繁體)" in r.text and ">English<" in r.text
