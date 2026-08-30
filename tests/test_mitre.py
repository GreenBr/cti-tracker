import json
from pathlib import Path

from click.testing import CliRunner

from cti import db, mitre
from cti.cli import main

FIX = Path(__file__).parent / "fixtures" / "attack_mini.json"


def test_china_intrusion_sets_filters_by_description_and_skips_revoked():
    bundle = json.loads(FIX.read_text())
    groups = mitre.china_intrusion_sets(bundle)
    assert [g["name"] for g in groups] == ["APT41"]
    g = groups[0]
    assert g["mitre_id"] == "G0096"
    assert "Brass Typhoon" in g["aliases"]
    assert "APT41" not in g["aliases"]  # canonical name is not repeated as alias
    assert g["attributed_country"] == "CN"


def _iset(name, desc):
    return {"type": "intrusion-set", "id": f"intrusion-set--{name}", "name": name, "aliases": [name],
            "description": desc, "external_references": [{"source_name": "mitre-attack", "external_id": "G0000"}]}


def test_attribution_filter_keeps_origin_phrases_and_drops_victim_mentions():
    bundle = {"objects": [
        _iset("A", "A is a Chinese-based threat group."),
        _iset("B", "B is a threat group believed to operate out of China."),
        _iset("C", "C appears to operate from the Guandong Province of China."),
        _iset("D", "D is a North Korean group that has targeted victims in Russia, China, and Sweden."),
        _iset("E", "E is an Indian threat group targeting China and Pakistan."),
    ]}
    assert [g["name"] for g in mitre.china_intrusion_sets(bundle)] == ["A", "B", "C"]


def test_init_command_seeds_actors_and_sources(tmp_path):
    src = tmp_path / "sources.yaml"
    src.write_text(
        "sources:\n"
        "  - name: Test Feed\n    url: https://example.com/feed\n    lang: en\n    type: news\n    enabled: true\n"
    )
    dbfile = tmp_path / "cti.db"
    runner = CliRunner()
    args = ["--db", str(dbfile), "init", "--mitre-file", str(FIX), "--sources", str(src),
            "--actors-out", str(tmp_path / "actors.json")]
    result = runner.invoke(main, args)
    assert result.exit_code == 0, result.output
    conn = db.connect(dbfile)
    assert conn.execute("select count(*) from actors").fetchone()[0] == 1
    assert conn.execute("select count(*) from sources").fetchone()[0] == 1
    # idempotent
    result = runner.invoke(main, args)
    assert result.exit_code == 0
    assert conn.execute("select count(*) from actors").fetchone()[0] == 1
    assert json.loads((tmp_path / "actors.json").read_text())[0]["name"] == "APT41"


def test_init_disables_sources_removed_from_yaml(tmp_path):
    src = tmp_path / "sources.yaml"
    dbfile = tmp_path / "cti.db"
    base = ["--db", str(dbfile), "init", "--mitre-file", str(FIX), "--sources", str(src),
            "--actors-out", str(tmp_path / "actors.json")]
    src.write_text("sources:\n  - {name: A, url: https://a/old, lang: en, type: news}\n")
    assert CliRunner().invoke(main, base).exit_code == 0
    src.write_text("sources:\n  - {name: A, url: https://a/new, lang: en, type: news}\n")
    result = CliRunner().invoke(main, base)
    assert result.exit_code == 0 and "stale disabled: 1" in result.output
    conn = db.connect(dbfile)
    rows = {r["url"]: r["enabled"] for r in conn.execute("select url, enabled from sources")}
    assert rows == {"https://a/old": 0, "https://a/new": 1}
