from click.testing import CliRunner

from cti import cli


def test_serve_builds_datasette_command(tmp_path, monkeypatch):
    called = {}
    monkeypatch.setattr(cli.subprocess, "run", lambda cmd, **kw: called.setdefault("cmd", cmd))
    dbfile = tmp_path / "cti.db"
    result = CliRunner().invoke(cli.main, ["--db", str(dbfile), "serve", "--port", "8123"])
    assert result.exit_code == 0, result.output
    cmd = called["cmd"]
    assert cmd[0] == "datasette" and str(dbfile) in cmd
    assert "-m" in cmd and cmd[cmd.index("-m") + 1].endswith("metadata.yaml")
    assert cmd[cmd.index("--port") + 1] == "8123"
