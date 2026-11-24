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


def test_a_running_console_that_answers_slowly_is_never_started_twice(monkeypatch, tmp_path):
    """critic: a console alive but slow to answer got a second one started over its pid file, and `stop` lost it."""
    import os
    import click
    import pytest
    monkeypatch.setenv("TRIBUNAL_HOME", str(tmp_path))
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "companion.pid").write_text("4242", encoding="utf-8")
    monkeypatch.setattr(tribunal_cli, "_ours", lambda pid: pid == 4242)
    monkeypatch.setattr(tribunal_cli, "_url", lambda: None)
    started = []
    monkeypatch.setattr(tribunal_cli.subprocess, "Popen", lambda *a, **k: started.append(a))
    with pytest.raises(click.ClickException):
        tribunal_cli.start_console(wait=1)
    assert started == [] and (tmp_path / "data" / "companion.pid").read_text() == "4242"


def test_stop_finds_the_console_through_its_port_record_too(monkeypatch, tmp_path):
    monkeypatch.setenv("TRIBUNAL_HOME", str(tmp_path))
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "companion.port").write_text('{"port": 1, "pid": 5151}', encoding="utf-8")   # `tribunal serve`
    monkeypatch.setattr(tribunal_cli, "_ours", lambda pid: pid == 5151)
    assert tribunal_cli._running_pid() == 5151


def test_on_windows_the_console_starts_without_a_window_and_keeps_one_for_its_children(monkeypatch):
    monkeypatch.setattr(tribunal_cli.os, "name", "nt")
    for name, value in (("CREATE_NEW_PROCESS_GROUP", 0x200), ("CREATE_NO_WINDOW", 0x8000000), ("DETACHED_PROCESS", 0x8)):
        monkeypatch.setattr(tribunal_cli.subprocess, name, value, raising=False)
    flags = tribunal_cli._spawn_flags()["creationflags"]
    assert flags & 0x8000000 and flags & 0x200 and not flags & 0x8


def test_tribunals_records_folder_is_refused_as_a_project(monkeypatch, tmp_path):
    import subprocess
    import dashboard_server
    home = tmp_path / "home"
    (home / "data").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(home / "data")], check=True)
    monkeypatch.setenv("TRIBUNAL_HOME", str(home))
    ok, why = dashboard_server.validate_project_path(str(home / "data"))
    assert ok is False
