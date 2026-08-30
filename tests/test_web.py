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


def test_actors_list_and_profile(client):
    r = client.get("/actors")
    assert r.status_code == 200 and "APT41" in r.text and "UNC9999" in r.text
    r = client.get("/actors/1")
    assert r.status_code == 200
    assert "APT41 spearphishing" in r.text and "T1566.001" in r.text and "semiconductor" in r.text
    assert client.get("/actors/999").status_code == 404


def test_incidents_filters_and_search(client):
    assert client.get("/incidents").status_code == 200
    r = client.get("/incidents?direction=to_cn")
    assert "Shanghai research institute" in r.text and "APT41 spearphishing" not in r.text
    r = client.get("/incidents?actor=1")
    assert "APT41 spearphishing" in r.text and "Shanghai research institute" not in r.text
    r = client.get("/incidents?q=guam")  # FTS over article text
    assert "APT41 spearphishing" in r.text and "2 incidents" in r.text
    r = client.get("/incidents?q=nomatchxyz")
    assert "No incidents match" in r.text


def test_incident_and_article_pages(client):
    r = client.get("/incidents/1")
    assert r.status_code == 200 and "T1059.001" in r.text and "/articles/1" in r.text
    r = client.get("/articles/1")
    assert r.status_code == 200 and "living off the land" in r.text and "Volt Typhoon report" in r.text
    assert "APT41 spearphishing" in r.text  # incidents extracted from this article
    assert client.get("/articles/99").status_code == 404


def test_trends_page_embeds_chart_data(client):
    r = client.get("/trends")
    assert r.status_code == 200 and "/static/vendor/chart.umd.js" in r.text
    assert '"direction"' in r.text and '"from_cn"' in r.text and "2026-08" in r.text
    assert client.get("/static/vendor/chart.umd.js").status_code == 200


def test_enum_labels_translate_when_catalog_present(client):
    # Before catalogs exist, labels fall back to English msgids.
    r = client.get("/incidents?lang=zh_TW")
    assert "From China" in r.text or "來自中國" in r.text
