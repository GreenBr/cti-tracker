import json
import subprocess
from pathlib import Path

import pytest

from cti import db, extract

ROOT = Path(__file__).parent.parent
FIX = Path(__file__).parent / "fixtures"
SCHEMA_PATH = ROOT / "schema" / "extract.json"
TEMPLATE = (ROOT / "prompts" / "extract.md").read_text()
QUIET = dict(sleep=lambda s: None, log=lambda m: None)


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "t.db")
    db.init_schema(c)
    db.get_or_create_actor(c, "APT41", aliases=["Brass Typhoon", "Winnti"], mitre_id="G0096")
    sid = db.upsert_source(c, "T", "https://ex.com/feed", "en", "news")
    for i in range(3):
        db.insert_article(c, source_id=sid, url=f"https://ex.com/{i}", title=f"Art {i}",
                          published_at="2026-08-30T00:00:00+00:00", lang="en", text="x" * 20000, relevance="candidate")
    db.insert_article(c, source_id=sid, url="https://ex.com/skip", title="skip", published_at=None,
                      lang="en", text="nothing", relevance="skip")
    return c


def fake_runner(payload_file, returncode=0):
    def runner(cmd, **kw):
        assert cmd[0] == "claude" and "-p" in cmd and "--json-schema" in cmd
        out = {"type": "result", "structured_output": json.loads((FIX / payload_file).read_text())}
        return subprocess.CompletedProcess(cmd, returncode, stdout=json.dumps(out), stderr="")
    return runner


def test_build_prompt_includes_actors_and_truncates(conn):
    article = {"title": "T", "url": "https://ex.com/0", "published_at": "2026-08-30", "lang": "en", "text": "ж" * 20000}
    p = extract.build_prompt(TEMPLATE, db.list_actors(conn), article)
    assert "APT41: Brass Typhoon, Winnti" in p
    assert "https://ex.com/0" in p
    assert p.count("ж") == extract.MAX_CHARS
    assert "{{" not in p


def test_parse_claude_output_prefers_structured_output_then_result_text():
    assert extract.parse_claude_output(json.dumps({"structured_output": {"relevant": False}})) == {"relevant": False}
    assert extract.parse_claude_output(json.dumps({"result": "{\"relevant\": true}"})) == {"relevant": True}
    with pytest.raises(extract.ExtractError):
        extract.parse_claude_output("not json")


def test_run_claude_raises_on_nonzero_and_timeout():
    def bad(cmd, **kw):
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="login required")
    with pytest.raises(extract.ExtractError, match="login required"):
        extract.run_claude("p", SCHEMA_PATH, runner=bad)

    def slow(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, 1)
    with pytest.raises(extract.ExtractError, match="timeout"):
        extract.run_claude("p", SCHEMA_PATH, runner=slow)


def test_write_extraction_resolves_aliases_creates_new_actors_and_links(conn):
    payload = json.loads((FIX / "claude_ok.json").read_text())
    stats = extract.write_extraction(conn, 1, payload, "2026-08-30T00:00:00+00:00")
    assert stats == {"incidents": 2, "new_actors": 1}  # UNC9999 is new; Brass Typhoon -> APT41
    inc = conn.execute("select * from incidents where direction='from_cn'").fetchone()
    apt41 = db.resolve_actor(conn, "APT41")
    assert inc["actor_id"] == apt41 and inc["reported_at"] == "2026-08-30T00:00:00+00:00"
    assert inc["victim_country"] == "TW"
    ttps = conn.execute("select technique_id from incident_ttps where incident_id=?", (inc["id"],)).fetchall()
    assert {r["technique_id"] for r in ttps} == {"T1566.001", "T1059.001"}
    links = conn.execute("select actor_id from article_actors where article_id=1").fetchall()
    assert len(links) == 2
    assert conn.execute("select actor_id from incidents where direction='to_cn'").fetchone()["actor_id"] is None
    assert conn.execute("select extract_status from articles where id=1").fetchone()["extract_status"] == "done"


def test_extract_pending_processes_candidates_marks_done_and_respects_limit(conn):
    calls = []
    runner = fake_runner("claude_ok.json")

    def counting(cmd, **kw):
        calls.append(cmd)
        return runner(cmd, **kw)

    stats = extract.extract_pending(conn, template=TEMPLATE, schema_path=SCHEMA_PATH, batch=2, limit=2,
                                    runner=counting, **QUIET)
    assert stats["processed"] == 2 and stats["done"] == 2 and stats["failed"] == 0
    assert len(calls) == 2
    rows = conn.execute("select extract_status from articles where relevance='candidate' order by id").fetchall()
    assert [r["extract_status"] for r in rows] == ["done", "done", "pending"]
    assert conn.execute("select extract_status from articles where relevance='skip'").fetchone()["extract_status"] == "pending"


def test_extract_pending_marks_failed_without_retry_and_retry_flag_reprocesses(conn):
    def bad(cmd, **kw):
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="rate limited")

    stats = extract.extract_pending(conn, template=TEMPLATE, schema_path=SCHEMA_PATH, limit=1, runner=bad, **QUIET)
    assert stats["failed"] == 1
    row = conn.execute("select extract_status, extract_error from articles where id=1").fetchone()
    assert row["extract_status"] == "failed" and "rate limited" in row["extract_error"]
    # normal run skips failed
    stats = extract.extract_pending(conn, template=TEMPLATE, schema_path=SCHEMA_PATH, limit=5,
                                    runner=fake_runner("claude_irrelevant.json"), **QUIET)
    assert stats["processed"] == 2
    assert conn.execute("select extract_status from articles where id=1").fetchone()["extract_status"] == "failed"
    # --retry-failed reprocesses only failed
    stats = extract.extract_pending(conn, template=TEMPLATE, schema_path=SCHEMA_PATH, limit=5, retry_failed=True,
                                    runner=fake_runner("claude_irrelevant.json"), **QUIET)
    assert stats["processed"] == 1
    assert conn.execute("select extract_status, extract_error from articles where id=1").fetchone()["extract_error"] is None


def test_retry_failed_does_not_loop_when_article_fails_again(conn):
    def bad(cmd, **kw):
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="still broken")

    extract.extract_pending(conn, template=TEMPLATE, schema_path=SCHEMA_PATH, limit=3, runner=bad, **QUIET)
    stats = extract.extract_pending(conn, template=TEMPLATE, schema_path=SCHEMA_PATH, limit=50, retry_failed=True,
                                    runner=bad, **QUIET)
    assert stats["processed"] == 3 and stats["failed"] == 3


def test_schema_violation_marks_failed(conn):
    def bad_shape(cmd, **kw):
        out = {"structured_output": {"relevant": True, "actors_mentioned": [], "incidents": [{"title": "x"}]}}
        return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(out), stderr="")

    stats = extract.extract_pending(conn, template=TEMPLATE, schema_path=SCHEMA_PATH, limit=1, runner=bad_shape, **QUIET)
    assert stats["failed"] == 1
    assert "schema" in conn.execute("select extract_error from articles where id=1").fetchone()["extract_error"].lower()
    assert conn.execute("select count(*) from incidents").fetchone()[0] == 0
