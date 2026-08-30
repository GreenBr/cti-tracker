"""Static export of the public web UI (for Vercel / any static host).

Renders every page in every supported locale through the real app (TestClient), rewrites internal links
to live under /<locale>/, strips nothing else - the public mode of the app itself decides what is shown.
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path

from fastapi.testclient import TestClient

from cti import db
from cti.web import i18n
from cti.web.app import STATIC_DIR, create_app

_HREF = re.compile(r'(href=")/(?!static/)')


def _rewrite(html: str, locale: str) -> str:
    return _HREF.sub(rf"\g<1>/{locale}/", html)


def _routes(conn) -> list[str]:
    routes = ["/", "/incidents", "/actors", "/trends"]
    routes += [f"/actors/{r[0]}" for r in conn.execute("SELECT id FROM actors ORDER BY id")]
    routes += [f"/incidents/{r[0]}" for r in conn.execute("SELECT id FROM incidents ORDER BY id")]
    routes += [f"/articles/{r[0]}" for r in conn.execute(
        "SELECT id FROM articles WHERE relevance='candidate' ORDER BY id")]
    return routes


ROOT_REDIRECT = """<!DOCTYPE html><html><head><meta charset="utf-8"><title>CTI Tracker</title>
<script>
var l = (navigator.language || "en").toLowerCase();
var t = l.indexOf("zh") === 0 ? (/tw|hk|mo|hant/.test(l) ? "zh_TW" : "zh_CN") : "en";
location.replace("/" + t + "/");
</script>
<meta http-equiv="refresh" content="0; url=/en/">
</head><body><a href="/en/">English</a> · <a href="/zh_CN/">简体中文</a> · <a href="/zh_TW/">繁體中文</a></body></html>
"""


def export_site(db_path: Path, out_dir: Path, log=print) -> dict:
    conn = db.connect(db_path)
    db.init_schema(conn)
    client = TestClient(create_app(db_path, public=True))
    routes = _routes(conn)
    out_dir = Path(out_dir)
    if out_dir.exists():
        shutil.rmtree(out_dir)
    (out_dir / "static").parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(STATIC_DIR, out_dir / "static")
    pages = 0
    for locale in i18n.SUPPORTED:
        for route in routes:
            resp = client.get(route, params={"lang": locale})
            if resp.status_code != 200:
                raise RuntimeError(f"export failed: {route} lang={locale} -> {resp.status_code}")
            dest = out_dir / locale / route.lstrip("/") / "index.html"
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(_rewrite(resp.text, locale), encoding="utf-8")
            pages += 1
        log(f"[export] {locale}: {len(routes)} pages")
    (out_dir / "index.html").write_text(ROOT_REDIRECT, encoding="utf-8")
    return {"pages": pages, "locales": len(i18n.SUPPORTED), "routes": len(routes)}
