"""Send candidate articles to `claude -p` and store structured results."""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import time
from pathlib import Path

import jsonschema

from cti import db

MAX_CHARS = 12_000
SLEEP_SECONDS = 3


class ExtractError(Exception):
    pass


def build_prompt(template: str, actors: list[dict], article: dict) -> str:
    known = "\n".join(
        f"- {a['canonical_name']}: {', '.join(a['aliases']) if a['aliases'] else '(no aliases)'}" for a in actors
    ) or "- (none)"
    meta = (f"Title: {article.get('title') or ''}\nURL: {article.get('url') or ''}\n"
            f"Published: {article.get('published_at') or 'unknown'}\nLanguage: {article.get('lang') or 'unknown'}")
    text = (article.get("text") or "")[:MAX_CHARS]
    return (template.replace("{{KNOWN_ACTORS}}", known)
                    .replace("{{ARTICLE_META}}", meta)
                    .replace("{{ARTICLE_TEXT}}", text))


def parse_claude_output(stdout: str) -> dict:
    try:
        outer = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise ExtractError(f"claude output is not JSON: {exc}") from exc
    if isinstance(outer, dict) and isinstance(outer.get("structured_output"), dict):
        return outer["structured_output"]
    if isinstance(outer, dict) and isinstance(outer.get("result"), str):
        try:
            return json.loads(outer["result"])
        except json.JSONDecodeError as exc:
            raise ExtractError(f"claude result text is not JSON: {exc}") from exc
    if isinstance(outer, dict) and "relevant" in outer:
        return outer
    raise ExtractError("claude output has neither structured_output nor result")


def run_claude(prompt: str, schema_path: Path, *, model: str = "sonnet", timeout: int = 180,
               runner=subprocess.run) -> dict:
    schema_text = Path(schema_path).read_text(encoding="utf-8")
    cmd = ["claude", "-p", "--model", model, "--output-format", "json", "--json-schema", schema_text]
    env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}  # allow running from inside a Claude Code session
    try:
        proc = runner(cmd, input=prompt, capture_output=True, text=True, timeout=timeout, env=env)
    except subprocess.TimeoutExpired as exc:
        raise ExtractError(f"claude timeout after {timeout}s") from exc
    if proc.returncode != 0:
        raise ExtractError(f"claude exit {proc.returncode}: {(proc.stderr or proc.stdout or '')[:500]}")
    return parse_claude_output(proc.stdout)


def validate(payload: dict, schema: dict) -> None:
    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError as exc:
        raise ExtractError(f"schema validation failed: {exc.message}") from exc


def write_extraction(conn: sqlite3.Connection, article_id: int, payload: dict, reported_at: str | None) -> dict:
    stats = {"incidents": 0, "new_actors": 0}
    now = db.now_iso()
    with conn:  # single transaction
        actor_ids = set()
        for a in payload.get("actors_mentioned", []):
            aid, created = db.get_or_create_actor(conn, a["name"], aliases=a.get("aliases_in_text", []))
            stats["new_actors"] += int(created)
            actor_ids.add(aid)
        for inc in payload.get("incidents", []):
            actor_id = None
            if inc.get("actor"):
                actor_id, created = db.get_or_create_actor(conn, inc["actor"])
                stats["new_actors"] += int(created)
                actor_ids.add(actor_id)
            cur = conn.execute(
                """INSERT INTO incidents(title, summary, occurred_at, reported_at, direction, actor_id,
                                         victim_country, victim_sector, confidence, article_id, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (inc["title"], inc.get("summary"), inc.get("occurred_at"), reported_at, inc["direction"], actor_id,
                 inc.get("victim_country"), inc.get("victim_sector"), inc.get("confidence"), article_id, now),
            )
            for t in inc.get("ttps", []):
                conn.execute("INSERT OR IGNORE INTO incident_ttps(incident_id, technique_id, technique_name) VALUES (?,?,?)",
                             (cur.lastrowid, t["id"], t.get("name")))
            stats["incidents"] += 1
        for aid in actor_ids:
            conn.execute("INSERT OR IGNORE INTO article_actors(article_id, actor_id) VALUES (?,?)", (article_id, aid))
        conn.execute("UPDATE articles SET extract_status='done', extract_error=NULL, extracted_at=? WHERE id=?",
                     (now, article_id))
    return stats


def mark_failed(conn: sqlite3.Connection, article_id: int, error: str) -> None:
    with conn:
        conn.execute("UPDATE articles SET extract_status='failed', extract_error=?, extracted_at=? WHERE id=?",
                     (error[:1000], db.now_iso(), article_id))


def extract_pending(conn: sqlite3.Connection, *, template: str, schema_path: Path, batch: int = 5, limit: int = 20,
                    retry_failed: bool = False, model: str = "sonnet", runner=subprocess.run,
                    sleep=time.sleep, log=print) -> dict:
    schema = json.loads(Path(schema_path).read_text(encoding="utf-8"))
    status = "failed" if retry_failed else "pending"
    stats = {"processed": 0, "done": 0, "failed": 0, "incidents": 0, "new_actors": 0}
    seen: set[int] = set()
    while stats["processed"] < limit:
        take = min(batch, limit - stats["processed"])
        rows = conn.execute(
            "SELECT * FROM articles WHERE relevance='candidate' AND extract_status=? ORDER BY published_at, id LIMIT ?",
            (status, take + len(seen))).fetchall()
        rows = [r for r in rows if r["id"] not in seen][:take]
        if not rows:
            break
        for row in rows:
            article = dict(row)
            seen.add(article["id"])
            stats["processed"] += 1
            try:
                prompt = build_prompt(template, db.list_actors(conn), article)
                payload = run_claude(prompt, schema_path, model=model, runner=runner)
                validate(payload, schema)
                s = write_extraction(conn, article["id"], payload, article.get("published_at"))
            except ExtractError as exc:
                mark_failed(conn, article["id"], str(exc))
                stats["failed"] += 1
                log(f"[extract] #{article['id']} FAILED: {exc}")
            else:
                stats["done"] += 1
                stats["incidents"] += s["incidents"]
                stats["new_actors"] += s["new_actors"]
                log(f"[extract] #{article['id']} ok: {s['incidents']} incidents, {s['new_actors']} new actors")
            if stats["processed"] < limit:
                sleep(SLEEP_SECONDS)
    return stats
