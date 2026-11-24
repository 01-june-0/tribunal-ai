"""Accounts in the AI settings panel: who is signed in, and the CLI's own sign-in / switch / sign-out."""
import json
import os
import subprocess
from pathlib import Path

import pytest

from core import cli_accounts as acc

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    acc.clear_cache()
    monkeypatch.setattr("core.env_utils.resolve_cli", lambda name: "/opt/tools/" + name)
    yield
    acc.clear_cache()


def done(stdout="", code=0, stderr=""):
    return subprocess.CompletedProcess([], code, stdout, stderr)


def test_an_address_is_masked_unless_asked_for():
    assert acc.mask_email("user@example.com") == "u•••@e•••.com"
    assert acc.mask_email("a@localhost") == "a•••@l•••" and acc.mask_email(None) is None and acc.mask_email("nope") is None
    shown = acc.public("claude", {"installed": True, "signed_in": True, "email": "user@example.com", "method": "subscription", "org": "acme"})
    assert "user@example.com" not in json.dumps(shown, ensure_ascii=False) and shown["email_masked"] == "u•••@e•••.com" and shown["has_email"]
    assert shown["actions"] == ["switch", "logout"]                         # signed in: no "sign in" button


def test_claude_and_codex_are_asked_through_their_own_commands(monkeypatch):
    calls = []

    def run(argv, timeout):
        calls.append(argv[1:])
        if argv[1:] == ["auth", "status"]:
            return done('{"loggedIn": true, "authMethod": "claude.ai", "email": "one@example.com", "orgName": "acme", "subscriptionType": "max"}')
        if argv[1:] == ["login", "status"]:
            return done("Logged in using ChatGPT")
        raise AssertionError(argv)
    monkeypatch.setattr(acc, "_run", run)
    monkeypatch.setattr("core.cli_limits._codex_rpc", lambda requests, timeout=20.0: {1: {"account": {"email": "two@example.com", "planType": "pro"}}})
    assert acc._read("claude") == {"installed": True, "signed_in": True, "email": "one@example.com", "method": "subscription", "org": "acme"}
    assert acc._read("openai") == {"installed": True, "signed_in": True, "email": "two@example.com", "method": "subscription", "org": None}
    assert acc._read("antigravity") == {"installed": True, "signed_in": None}      # its CLI has nothing to ask
    assert calls == [["auth", "status"], ["login", "status"]]


def test_signed_out_and_unreadable_states(monkeypatch):
    monkeypatch.setattr(acc, "_run", lambda argv, timeout: done('{"loggedIn": false}') if "auth" in argv else done("Not logged in", 1))
    assert acc._read("claude")["signed_in"] is False and acc._read("openai")["signed_in"] is False
    assert acc.public("openai", {"installed": True, "signed_in": False})["actions"] == ["login"]
    monkeypatch.setattr(acc, "_run", lambda argv, timeout: (_ for _ in ()).throw(subprocess.TimeoutExpired(argv, timeout)))
    assert acc._read("claude") == {"installed": True, "signed_in": None, "error": "TimeoutExpired"}
    monkeypatch.setattr("core.env_utils.resolve_cli", lambda name: None)
    assert acc._read("claude") == {"installed": False, "signed_in": None}
    assert acc.public("claude", {"installed": False, "signed_in": None})["actions"] == []
    quota = acc.public("antigravity", {"installed": True, "signed_in": None}, quota_ok=True)
    assert quota["signed_in"] is True and quota["identity_known"] is False and quota["actions"] == ["open"]


def test_only_the_fixed_commands_can_be_started(monkeypatch):
    opened = []
    launcher = lambda exe, parts, cli, action: opened.append((exe, parts, cli, action)) or True
    assert acc.start("claude", "login", launcher=launcher, busy=False)["status"] == "started"
    assert acc.start("openai", "switch", launcher=launcher, busy=False) == {"status": "started", "command": "codex logout && codex login"}
    assert acc.start("antigravity", "open", launcher=launcher, busy=False)["command"] == "agy"
    assert opened == [("/opt/tools/claude", [["auth", "login"]], "claude", "login"),
                      ("/opt/tools/codex", [["logout"], ["login"]], "openai", "switch"), ("/opt/tools/agy", [[]], "antigravity", "open")]
    for cli, action in (("claude", "rm -rf ~"), ("antigravity", "logout"), ("antigravity", "login"), ("gemini", "login"), ("claude", "")):
        with pytest.raises(ValueError):
            acc.start(cli, action, launcher=launcher, busy=False)
    assert len(opened) == 3


def test_signing_out_waits_for_work_to_finish_and_runs_directly(monkeypatch):
    ran = []
    monkeypatch.setattr(acc, "_run", lambda argv, timeout: ran.append(argv) or done())
    launcher = lambda *a: pytest.fail("no terminal for a sign-out")
    assert acc.start("claude", "logout", launcher=launcher, busy=True) == {"status": "busy"}
    assert acc.start("openai", "switch", launcher=launcher, busy=True) == {"status": "busy"} and ran == []
    assert acc.start("claude", "login", launcher=launcher, busy=True) == {"status": "busy"}             # state unknown: could replace live credentials
    with monkeypatch.context() as m:                                       # (never monkeypatch.undo(): it would drop the test sandbox)
        m.setattr(acc, "account", lambda cli, max_age=30.0, wait=False: {"installed": True, "signed_in": False})
        assert acc.start("claude", "login", launcher=lambda *a: True, busy=True)["status"] == "started"     # signed out: nothing to break
    assert acc.start("claude", "logout", launcher=launcher, busy=False) == {"status": "done", "code": 0}
    assert ran == [["/opt/tools/claude", "auth", "logout"]]
    monkeypatch.setattr("core.env_utils.resolve_cli", lambda name: None)
    assert acc.start("openai", "login", launcher=launcher, busy=False)["status"] == "unavailable"


def test_no_known_terminal_gives_the_command_to_type(monkeypatch):
    assert acc.start("openai", "login", launcher=lambda *a: False, busy=False) == {"status": "manual", "command": "codex login"}
    assert not acc._PENDING


def test_a_started_sign_in_is_pending_until_the_account_changes(monkeypatch):
    before = {"installed": True, "signed_in": False}
    with acc._LOCK:
        acc._PENDING["claude"] = {"since": acc.time.time(), "was": acc._identity(before)}
    assert acc.public("claude", before)["pending"] is True
    monkeypatch.setattr("core.cli_limits.refresh_now", lambda: True)
    assert acc.public("claude", {"installed": True, "signed_in": None})["pending"] is True    # mid-switch (signed out for a moment) is not the end
    after = {"installed": True, "signed_in": True, "email": "new@example.com", "method": "subscription"}
    assert acc.public("claude", after)["pending"] is False and "claude" not in acc._PENDING
    with acc._LOCK:
        acc._PENDING["openai"] = {"since": acc.time.time() - acc.PENDING_SECONDS - 1, "was": acc._identity(before)}
    assert acc.public("openai", before)["pending"] is False                 # given up on after ten minutes
    with acc._LOCK:
        acc._PENDING["antigravity"] = {"since": acc.time.time(), "was": None}
    assert acc.public("antigravity", before)["pending"] is True
    assert acc.start("antigravity", "check") == {"status": "checked"} and "antigravity" not in acc._PENDING


def test_the_terminal_script_only_runs_the_cli(tmp_path):
    text = acc._script("/Applications/My Tools/claude", [["auth", "logout"], ["auth", "login"]])
    lines = text.splitlines()
    assert lines[0] == "#!/bin/sh" and "'/Applications/My Tools/claude' auth logout" in lines and "'/Applications/My Tools/claude' auth login" in lines
    assert all(l.startswith(("#", "cd ", "echo", "'/Applications/My Tools/claude' ")) for l in lines)


def test_an_organisation_named_after_an_address_is_masked_too():
    shown = acc.public("claude", {"installed": True, "signed_in": True, "email": "user@example.com", "org": "user@example.com's Organization"})
    assert shown["org"] == "u•••@e•••.com's Organization" and "user@" not in json.dumps(shown, ensure_ascii=False)


def test_reading_an_account_does_not_hold_the_request(monkeypatch):
    import threading
    monkeypatch.setattr(acc, "_testing", lambda: False)
    gate, asked = threading.Event(), []
    monkeypatch.setattr(acc, "_read", lambda cli: (asked.append(cli), gate.wait(5), {"installed": True, "signed_in": True, "email": "a@b.co"})[2])
    assert acc.account("claude") == {"installed": True, "signed_in": None, "loading": True}     # answered at once
    assert acc.account("claude").get("loading") and asked == ["claude"]                         # and only one look-up is started
    gate.set()
    for _ in range(100):
        if not acc._REFRESHING:
            break
        acc.time.sleep(.02)
    assert acc.account("claude")["email"] == "a@b.co" and acc.account("claude", wait=True)["signed_in"] is True and asked == ["claude"]


def test_a_script_is_never_written_through_a_link(tmp_path, monkeypatch):
    monkeypatch.setattr("core.db_path.get_db_path", lambda: str(tmp_path / "data" / "director.db"))
    (tmp_path / "data").mkdir()
    path = acc._write_script("claude-login.command", "#!/bin/sh\n")
    assert path.read_text() == "#!/bin/sh\n" and (os.name == "nt" or (path.stat().st_mode & 0o777) == 0o700)   # Windows has no mode bits
    victim = tmp_path / "victim.txt"; victim.write_text("keep")
    path.unlink(); path.symlink_to(victim)
    acc._write_script("claude-login.command", "#!/bin/sh\necho hi\n")
    assert victim.read_text() == "keep" and not path.is_symlink()


def test_tests_never_ask_a_real_cli():
    assert acc.account("claude") == {"installed": True, "signed_in": None}  # DIRECTOR_TESTING: no process is started


def test_console_side():
    js = (ROOT / "console" / "stage.js").read_text(encoding="utf-8")
    server = (ROOT / "companion_server.py").read_text(encoding="utf-8")
    assert "'accounts': cli_accounts.snapshot(limits)" in server
    block = server[server.index("if self.path in ('/ops/ai/account', '/ops/ai/account/reveal'):"):]
    block = block[:block.index("if self.path == '/ops/ai':")]
    assert "not self.authorized()" in block and "is_request_origin_allowed" in block      # the token and a local origin, both
    for part in ("function accountBox(p,key)", "accountPost('/ops/ai/account/reveal',{cli:key})", "},20000)", "if(act==='logout'&&!confirm(", "if(act==='switch'&&!confirm("):
        assert part in js, part
    assert "localStorage" not in js[js.index("const revealed={}"):js.index("function paintAI(force){")]     # an address is never kept


def test_account_details_are_folded_away_until_asked_for():
    js = (ROOT / "console" / "stage.js").read_text(encoding="utf-8")
    css = (ROOT / "console" / "stage.css").read_text(encoding="utf-8")
    assert "const open=!!accountOpen[key]||!!a.pending" in js and "wrap.append(tog);if(!open)return wrap;" in js   # closed: only the button
    assert "tog.setAttribute('aria-expanded',String(open))" in js
    assert "if(open&&revealed[key]){clearTimeout(revealed[key].timer);delete revealed[key];}" in js              # folding hides a revealed address
    assert "accountOpen" not in js.replace("const revealed={},accountOpen={};", "").split("function accountBox")[0]   # nothing opens it but the user
    assert ".ai-card-head{display:flex;flex-wrap:nowrap;" in css                                                   # the plan select stays on the first row
