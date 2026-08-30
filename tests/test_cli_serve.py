from click.testing import CliRunner

from cti import cli


def test_datasette_builds_command(tmp_path, monkeypatch):
    called = {}
    monkeypatch.setattr(cli.subprocess, "run", lambda cmd, **kw: called.setdefault("cmd", cmd))
    dbfile = tmp_path / "cti.db"
    result = CliRunner().invoke(cli.main, ["--db", str(dbfile), "datasette", "--port", "8123"])
    assert result.exit_code == 0, result.output
    cmd = called["cmd"]
    assert cmd[0] == "datasette" and str(dbfile) in cmd
    assert "-m" in cmd and cmd[cmd.index("-m") + 1].endswith("metadata.yaml")
    assert cmd[cmd.index("--port") + 1] == "8123"


def test_serve_runs_uvicorn_with_app(tmp_path, monkeypatch):
    import uvicorn
    called = {}
    monkeypatch.setattr(uvicorn, "run", lambda app, **kw: called.update(app=app, **kw))
    result = CliRunner().invoke(cli.main, ["--db", str(tmp_path / "cti.db"), "serve", "--port", "8123"])
    assert result.exit_code == 0, result.output
    assert called["port"] == 8123 and called["app"].title == "CTI Tracker"


def test_i18n_commands_call_pybabel(monkeypatch):
    calls = []
    monkeypatch.setattr(cli.subprocess, "run", lambda cmd, **kw: calls.append(cmd))
    r = CliRunner()
    assert r.invoke(cli.main, ["i18n", "extract"]).exit_code == 0
    assert r.invoke(cli.main, ["i18n", "compile"]).exit_code == 0
    assert calls[0][:2] == ["pybabel", "extract"] and "-k" in calls[0] and "gettext_lazy" in calls[0]
    assert calls[1][:2] == ["pybabel", "compile"]
