"""FastAPI web UI for cti-tracker."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import jinja2
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette_babel.contrib.jinja import configure_jinja_env

from cti import db
from cti.web import i18n, queries

HERE = Path(__file__).resolve().parent
TEMPLATES_DIR = HERE / "templates"
STATIC_DIR = HERE / "static"


def _templates() -> Jinja2Templates:
    env = jinja2.Environment(loader=jinja2.FileSystemLoader(str(TEMPLATES_DIR)), autoescape=True)
    configure_jinja_env(env)
    env.globals.update({"enum_label": i18n.enum_label, "locale_choices": i18n.locale_choices,
                        "current_locale_code": i18n.current_locale_code})
    return Jinja2Templates(env=env)


def create_app(db_path: Path) -> FastAPI:
    i18n.load_catalogs()
    app = FastAPI(title="CTI Tracker")
    i18n.add_locale_middleware(app)
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    templates = _templates()

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

    return app
