"""cti command-line entry point."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import click
import yaml

from cti import db, extract, fetch, mitre

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "data" / "cti.db"
DEFAULT_SOURCES = ROOT / "sources.yaml"
DEFAULT_ACTORS_OUT = ROOT / "data" / "mitre_china_actors.json"
DEFAULT_MITRE_CACHE = ROOT / "data" / "enterprise-attack.json"
DEFAULT_KEYWORDS = ROOT / "keywords.yaml"
DEFAULT_PROMPT = ROOT / "prompts" / "extract.md"
DEFAULT_SCHEMA = ROOT / "schema" / "extract.json"
DEFAULT_METADATA = ROOT / "metadata.yaml"


def load_sources(path: Path) -> list[dict]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    return list(data.get("sources", []))


@click.group()
@click.option("--db", "db_path", type=click.Path(path_type=Path), default=DEFAULT_DB, show_default=True)
@click.pass_context
def main(ctx, db_path):
    ctx.ensure_object(dict)
    ctx.obj["db_path"] = db_path


@main.command()
@click.option("--mitre-file", type=click.Path(path_type=Path), default=None,
              help="Local ATT&CK STIX bundle; downloads if omitted.")
@click.option("--sources", "sources_path", type=click.Path(path_type=Path), default=DEFAULT_SOURCES, show_default=True)
@click.option("--actors-out", type=click.Path(path_type=Path), default=DEFAULT_ACTORS_OUT, show_default=True)
@click.pass_context
def init(ctx, mitre_file, sources_path, actors_out):
    """Create schema, seed China-attributed actors from ATT&CK, sync sources.yaml."""
    conn = db.connect(ctx.obj["db_path"])
    db.init_schema(conn)
    try:
        bundle = mitre.load_bundle(mitre_file) if mitre_file else mitre.download_bundle(DEFAULT_MITRE_CACHE)
    except Exception as exc:  # noqa: BLE001
        raise click.ClickException(
            f"Failed to load ATT&CK bundle: {exc}. Use --mitre-file with a local copy of {mitre.ATTACK_URL}") from exc
    groups = mitre.china_intrusion_sets(bundle)
    actors_out.parent.mkdir(parents=True, exist_ok=True)
    actors_out.write_text(json.dumps(groups, ensure_ascii=False, indent=2), encoding="utf-8")
    created = 0
    for g in groups:
        _, was_new = db.get_or_create_actor(conn, g["name"], aliases=g["aliases"], attributed_country="CN",
                                            mitre_id=g["mitre_id"], description=g["description"])
        created += int(was_new)
    n_sources = 0
    urls = []
    for s in load_sources(sources_path):
        db.upsert_source(conn, s["name"], s["url"], s["lang"], s["type"], s.get("enabled", True))
        urls.append(s["url"])
        n_sources += 1
    stale = db.disable_sources_not_in(conn, urls)
    click.echo(f"actors: {len(groups)} china-attributed ({created} new); sources synced: {n_sources}"
               + (f"; stale disabled: {stale}" if stale else ""))


@main.command("fetch")
@click.option("--keywords", "keywords_path", type=click.Path(path_type=Path), default=DEFAULT_KEYWORDS, show_default=True)
@click.pass_context
def fetch_cmd(ctx, keywords_path):
    """Pull enabled feeds, extract bodies, pre-filter by keywords."""
    conn = db.connect(ctx.obj["db_path"])
    db.init_schema(conn)
    kws = fetch.load_keywords(keywords_path, conn)
    stats = fetch.fetch_all(conn, kws, log=click.echo)
    click.echo(f"new: {stats['new']}  candidates: {stats['candidates']}  skipped: {stats['skipped']}  "
               f"sources failed: {stats['sources_failed']}")


@main.command("extract")
@click.option("--batch", default=5, show_default=True, help="Articles selected per round.")
@click.option("--limit", default=20, show_default=True, help="Max articles this run.")
@click.option("--retry-failed", is_flag=True, help="Re-run articles whose last extraction failed.")
@click.option("--model", default="sonnet", show_default=True)
@click.option("--prompt", "prompt_path", type=click.Path(path_type=Path), default=DEFAULT_PROMPT, show_default=True)
@click.option("--schema", "schema_path", type=click.Path(path_type=Path), default=DEFAULT_SCHEMA, show_default=True)
@click.pass_context
def extract_cmd(ctx, batch, limit, retry_failed, model, prompt_path, schema_path):
    """Send candidate articles to `claude -p` (subscription) and store actors/incidents/TTPs."""
    conn = db.connect(ctx.obj["db_path"])
    db.init_schema(conn)
    template = Path(prompt_path).read_text(encoding="utf-8")
    stats = extract.extract_pending(conn, template=template, schema_path=schema_path, batch=batch, limit=limit,
                                    retry_failed=retry_failed, model=model, log=click.echo)
    click.echo(f"processed: {stats['processed']}  done: {stats['done']}  failed: {stats['failed']}  "
               f"incidents: +{stats['incidents']}  actors: +{stats['new_actors']}")


@main.command()
@click.option("--port", default=8001, show_default=True)
@click.option("--host", default="127.0.0.1", show_default=True)
@click.pass_context
def serve(ctx, port, host):
    """Run the web UI (FastAPI + Uvicorn)."""
    import uvicorn

    from cti.web.app import create_app

    click.echo(f"Open http://{host}:{port}/")
    uvicorn.run(create_app(ctx.obj["db_path"]), host=host, port=port, log_level="warning")


@main.command()
@click.option("--port", default=8002, show_default=True)
@click.option("--metadata", "metadata_path", type=click.Path(path_type=Path), default=DEFAULT_METADATA, show_default=True)
@click.pass_context
def datasette(ctx, port, metadata_path):
    """Run Datasette on the CTI database (raw-data browsing fallback)."""
    db_path = ctx.obj["db_path"]
    conn = db.connect(db_path)
    db.init_schema(conn)
    conn.close()
    cmd = ["datasette", str(db_path), "-m", str(metadata_path), "--port", str(port),
           "--setting", "default_page_size", "50"]
    click.echo("Open http://127.0.0.1:%d/  (dashboard: /-/dashboards/trends)" % port)
    subprocess.run(cmd, check=False)


@main.command()
@click.option("--out", "out_dir", type=click.Path(path_type=Path), default=ROOT / "site", show_default=True)
@click.pass_context
def export(ctx, out_dir):
    """Export the public site (no article bodies) as static HTML for Vercel/any static host."""
    from cti.export import export_site

    stats = export_site(ctx.obj["db_path"], out_dir, log=click.echo)
    click.echo(f"exported {stats['pages']} pages ({stats['routes']} routes x {stats['locales']} locales) to {out_dir}")


TRANSLATIONS = ROOT / "cti" / "translations"
POT = TRANSLATIONS / "messages.pot"


@main.group()
def i18n():
    """Translation catalog workflow (Babel + OpenCC)."""


def _pybabel(*args: str) -> None:
    subprocess.run(["pybabel", *args], check=True, cwd=ROOT)


@i18n.command("extract")
def i18n_extract():
    """Extract translatable strings into cti/translations/messages.pot."""
    TRANSLATIONS.mkdir(parents=True, exist_ok=True)
    _pybabel("extract", "-F", "babel.cfg", "-k", "gettext_lazy", "-k", "_", "--project", "cti-tracker",
             "--no-location", "--sort-by-file", "-o", str(POT), ".")


@i18n.command("init")
@click.argument("locale")
def i18n_init(locale):
    """Create a new locale catalog from the .pot (e.g. zh_CN)."""
    _pybabel("init", "-i", str(POT), "-d", str(TRANSLATIONS), "-l", locale)


@i18n.command("update")
def i18n_update():
    """Merge new strings from the .pot into every existing catalog."""
    _pybabel("update", "-i", str(POT), "-d", str(TRANSLATIONS))


@i18n.command("compile")
def i18n_compile():
    """Compile .po -> .mo for all locales."""
    _pybabel("compile", "-d", str(TRANSLATIONS), "--statistics")


@i18n.command("gen-hant")
def i18n_gen_hant():
    """Generate zh_TW catalog from zh_CN with OpenCC (s2twp); review afterwards."""
    from cti.i18n_tools import generate_zh_tw

    src = TRANSLATIONS / "zh_CN" / "LC_MESSAGES" / "messages.po"
    dst = TRANSLATIONS / "zh_TW" / "LC_MESSAGES" / "messages.po"
    n = generate_zh_tw(src, dst)
    click.echo(f"zh_TW: {n} messages written to {dst} (review before compile)")
