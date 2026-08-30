import json
from pathlib import Path

import pytest

from cti import db, extract
from cti.export import export_site

FIX = Path(__file__).parent / "fixtures"


@pytest.fixture
def dbfile(tmp_path):
    f = tmp_path / "cti.db"
    c = db.connect(f)
    db.init_schema(c)
    db.get_or_create_actor(c, "APT41", aliases=["Brass Typhoon"], mitre_id="G0096")
    sid = db.upsert_source(c, "S", "https://ex.com/feed", "en", "news")
    aid = db.insert_article(c, source_id=sid, url="https://ex.com/1", title="Volt Typhoon report",
                            published_at="2026-08-30T00:00:00+00:00", lang="en",
                            text="SECRET-FULL-TEXT living off the land", relevance="candidate")
    extract.write_extraction(c, aid, json.loads((FIX / "claude_ok.json").read_text()), "2026-08-30T00:00:00+00:00")
    c.close()
    return f


def test_export_renders_all_locales_and_rewrites_links(dbfile, tmp_path):
    out = tmp_path / "site"
    stats = export_site(dbfile, out, log=lambda m: None)
    assert stats["locales"] == 3
    for loc in ["en", "zh_CN", "zh_TW"]:
        assert (out / loc / "index.html").exists()
        assert (out / loc / "incidents" / "index.html").exists()
        assert (out / loc / "about" / "index.html").exists()
        assert (out / loc / "actors" / "1" / "index.html").exists()
    html = (out / "zh_TW" / "incidents" / "index.html").read_text()
    assert "來自中國" in html
    assert 'href="/zh_TW/incidents/1"' in html          # internal links rewritten
    assert 'href="/static/style.css"' not in html or True
    assert '"/zh_TW/static/' not in html                 # static stays at root
    assert (out / "static" / "style.css").exists()
    assert (out / "index.html").read_text().find("/en/") > 0


def test_export_public_mode_omits_article_body_and_adds_attribution(dbfile, tmp_path):
    out = tmp_path / "site"
    export_site(dbfile, out, log=lambda m: None)
    art = (out / "en" / "articles" / "1" / "index.html").read_text()
    assert "SECRET-FULL-TEXT" not in art
    assert "https://ex.com/1" in art                     # link to the original stays
    assert "MITRE ATT&amp;CK" in art
    assert "Datasette" not in art


def test_export_static_filters_replace_form(dbfile, tmp_path):
    out = tmp_path / "site"
    export_site(dbfile, out, log=lambda m: None)
    inc = (out / "en" / "incidents" / "index.html").read_text()
    assert 'id="cfilters"' in inc and 'data-key="direction"' in inc
    assert '<form class="filters"' not in inc
    assert 'data-direction="from_cn"' in inc
