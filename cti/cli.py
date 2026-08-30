"""cti command-line entry point."""
from __future__ import annotations

import json
from pathlib import Path

import click
import yaml

from cti import db, fetch, mitre

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "data" / "cti.db"
DEFAULT_SOURCES = ROOT / "sources.yaml"
DEFAULT_ACTORS_OUT = ROOT / "data" / "mitre_china_actors.json"
DEFAULT_MITRE_CACHE = ROOT / "data" / "enterprise-attack.json"
DEFAULT_KEYWORDS = ROOT / "keywords.yaml"


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
    for s in load_sources(sources_path):
        db.upsert_source(conn, s["name"], s["url"], s["lang"], s["type"], s.get("enabled", True))
        n_sources += 1
    click.echo(f"actors: {len(groups)} china-attributed ({created} new); sources synced: {n_sources}")


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
