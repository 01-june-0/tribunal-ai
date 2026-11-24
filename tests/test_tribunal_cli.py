"""`tribunal` (tribunal_cli.py): one command, the same on every platform, for an installed Tribunal AI.

The console really starts here, in its own empty home and on a free port, so the machine's real console is never
touched; it is stopped again before the test ends."""
import json
import socket
from pathlib import Path

from click.testing import CliRunner

import tribunal_cli


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_the_director_commands_are_there_too():
    names = set(tribunal_cli.cli.commands)
    assert {"open", "start", "stop", "serve", "doctor"} <= names
    assert {"do", "mission", "run", "status", "resume", "clean-worktrees"} <= names


def test_doctor_says_what_is_missing(monkeypatch, tmp_path):
    monkeypatch.setenv("TRIBUNAL_HOME", str(tmp_path))
    monkeypatch.setattr(tribunal_cli.shutil, "which", lambda name: "/bin/git" if name == "git" else ("/bin/codex" if name == "codex" else None))
    monkeypatch.setattr(tribunal_cli, "_version", lambda exe: Path(exe).name + " 1.0")
    out = CliRunner().invoke(tribunal_cli.cli, ["doctor", "--json"])
    report = json.loads(out.output)
    assert report["home"] == str(tmp_path) and report["git"] == "git 1.0"
    assert report["clis"] == {"claude": None, "codex": "codex 1.0", "agy": None} and report["ready"] is False
    text = CliRunner().invoke(tribunal_cli.cli, ["doctor"]).output
    assert "✗ claude" in text and "아직 준비되지 않음" in text


def test_start_stop_in_an_empty_home(monkeypatch, tmp_path):
    monkeypatch.setenv("TRIBUNAL_HOME", str(tmp_path))
    port = _free_port()
    monkeypatch.setenv("TRIBUNAL_PORT", str(port))
    monkeypatch.delenv("TRIBUNAL_DB_PATH", raising=False)
    monkeypatch.delenv("DIRECTOR_TESTING", raising=False)
    try:
        url = tribunal_cli.start_console(wait=40)
        assert url == f"http://127.0.0.1:{port}" and tribunal_cli._url() == url
        assert tribunal_cli.start_console(wait=40) == url                     # a second start reuses it
        assert (tmp_path / "data" / "bridge.token").exists() and (tmp_path / "data" / "director.db").exists()
    finally:
        stopped = tribunal_cli.stop_console()
    assert stopped and tribunal_cli._url() is None and not (tmp_path / "data" / "companion.pid").exists()
    assert tribunal_cli.stop_console() is False


def test_a_number_in_the_pid_file_that_is_not_the_console_is_never_stopped(monkeypatch, tmp_path):
    import os
    monkeypatch.setenv("TRIBUNAL_HOME", str(tmp_path))
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "companion.pid").write_text(str(os.getpid()), encoding="utf-8")   # this test process
    assert tribunal_cli._running_pid() is None and tribunal_cli.stop_console() is False


def test_the_package_ships_what_core_paths_expects():
    import pytest
    tomllib = pytest.importorskip("tomllib")                                  # Python 3.11+
    meta = tomllib.loads((Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(encoding="utf-8"))
    assert meta["project"]["scripts"]["tribunal"] == "tribunal_cli:main"
    shipped = meta["tool"]["hatch"]["build"]["targets"]["wheel"]["force-include"]
    for need in ("director.py", "dashboard_server.py", "dashboard_i18n.py", "companion_server.py", "tribunal_cli.py",
                 "config.yaml", "companion.json", "console", "scripts/pick_folder.py"):
        assert need in shipped, need
    deps = {d.split(">")[0].split("=")[0].lower() for d in meta["project"]["dependencies"]}
    wanted = {line.split(">")[0].split("=")[0].strip().lower() for line in
              (Path(__file__).resolve().parents[1] / "requirements.txt").read_text().splitlines() if line.strip()}
    assert deps == wanted                                                     # one list of dependencies, not two
