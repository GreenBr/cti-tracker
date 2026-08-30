"""FastAPI web UI for cti-tracker."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from urllib.parse import urlencode

import jinja2
from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette_babel.contrib.jinja import configure_jinja_env

from cti import db
from cti.web import i18n, queries

HERE = Path(__file__).resolve().parent
TEMPLATES_DIR = HERE / "templates"
STATIC_DIR = HERE / "static"


def _templates(public: bool) -> Jinja2Templates:
    env = jinja2.Environment(loader=jinja2.FileSystemLoader(str(TEMPLATES_DIR)), autoescape=True)
    configure_jinja_env(env)
    env.globals.update({"enum_label": i18n.enum_label, "locale_choices": i18n.locale_choices,
                        "current_locale_code": i18n.current_locale_code, "public_mode": public})
    env.filters["replace_param"] = _replace_param
    return Jinja2Templates(env=env)


def _replace_param(params, key: str, value) -> str:
    """Query string with one parameter replaced (for pagination links)."""
    items = [(k, v) for k, v in params.multi_items() if k != key] + [(key, str(value))]
    return urlencode(items)


def create_app(db_path: Path, public: bool = False) -> FastAPI:
    """public=True: shareable mode - no article bodies, attribution footer, client-side filtering (used by export)."""
    i18n.load_catalogs()
    app = FastAPI(title="CTI Tracker")
    i18n.add_locale_middleware(app)
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    templates = _templates(public)

    def conn() -> sqlite3.Connection:
        c = db.connect(db_path)
        db.init_schema(c)
        return c

    def render(request: Request, name: str, **ctx):
        return templates.TemplateResponse(request, name, ctx)

    @app.middleware("http")
    async def remember_language(request: Request, call_next):
        response = await call_next(request)
        chosen = request.query_params.get("lang")
        if chosen in i18n.SUPPORTED:
            response.set_cookie(i18n.COOKIE, chosen, max_age=i18n.COOKIE_MAX_AGE, samesite="lax")
        return response

    @app.get("/")
    def index(request: Request):
        c = conn()
        return render(request, "index.html", stats=queries.stats(c), today=queries.new_today(c))

    @app.get("/actors")
    def actors(request: Request):
        return render(request, "actors.html", actors=queries.actors(conn()))

    @app.get("/actors/{actor_id}")
    def actor(request: Request, actor_id: int):
        c = conn()
        a = queries.actor(c, actor_id)
        if not a:
            raise HTTPException(404)
        return render(request, "actor.html", actor=a, incidents=queries.actor_incidents(c, actor_id),
                      ttps=queries.actor_ttps(c, actor_id), sectors=queries.actor_sectors(c, actor_id))

    @app.get("/incidents")
    def incidents(request: Request, direction: str | None = None, country: str | None = None,
                  sector: str | None = None, actor: int | None = None, q: str | None = None, page: int = 1):
        c = conn()
        per_page = 100000 if public else 50
        rows, total = queries.incidents(c, direction=direction or None, country=country or None,
                                        sector=sector or None, actor_id=actor or None, q=(q or "").strip() or None,
                                        page=max(page, 1), per_page=per_page)
        return render(request, "incidents.html", incidents=rows, total=total, page=max(page, 1), per_page=per_page,
                      options=queries.filter_options(c),
                      filters={"direction": direction or "", "country": country or "", "sector": sector or "",
                               "actor": actor or "", "q": q or ""})

    @app.get("/incidents/{incident_id}")
    def incident(request: Request, incident_id: int):
        i = queries.incident(conn(), incident_id)
        if not i:
            raise HTTPException(404)
        return render(request, "incident.html", incident=i)

    @app.get("/articles/{article_id}")
    def article(request: Request, article_id: int):
        c = conn()
        a = queries.article(c, article_id)
        if not a:
            raise HTTPException(404)
        if public:
            a["text"] = None
        return render(request, "article.html", article=a, incidents=queries.article_incidents(c, article_id),
                      actors=queries.article_actors(c, article_id))

    @app.get("/trends")
    def trends(request: Request):
        c = conn()
        direction = queries.trend_direction(c)
        charts = {
            "per_month": queries.trend_per_month(c),
            "direction": [{**d, "label": i18n.enum_label("direction", d["direction"])} for d in direction],
            "sectors": queries.trend_sectors(c),
            "ttps": queries.trend_ttps(c),
        }
        return render(request, "trends.html", charts=charts, charts_json=json.dumps(charts, ensure_ascii=False))

    return app
