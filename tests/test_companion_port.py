"""core.companion_config: which port the console takes, finding a running console, and proving it is ours."""
import json
from pathlib import Path
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

import pytest

from core import companion_config as cc

TOKEN = "test-token"


def _serve(handler):
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


class _Quiet(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _json(self, payload, code=200):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture
def root(tmp_path, monkeypatch):
    monkeypatch.delenv("TRIBUNAL_PORT", raising=False)
    return tmp_path


@pytest.fixture
def ours(root):
    """A stand-in for this installation's console: answers /ops/hello like companion_server does."""
    class Handler(_Quiet):
        def do_GET(self):
            nonce = parse_qs(urlsplit(self.path).query).get("nonce", [""])[0]
            self._json(cc.hello_payload(root, TOKEN, nonce))
    server = _serve(Handler)
    yield server.server_address[1]
    server.shutdown(); server.server_close()


@pytest.fixture
def stranger():
    """Another program on a port: answers 200 to anything, like a web server would."""
    class Handler(_Quiet):
        def do_GET(self):
            self._json({"app": "something-else", "proof": "0" * 64})
    server = _serve(Handler)
    yield server.server_address[1]
    server.shutdown(); server.server_close()


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ---------------------------------------------------------------- which port
def test_default_port_is_not_a_choice_but_local_file_and_env_are(root, monkeypatch):
    assert cc.configured_port(root) == (cc.DEFAULT_PORT, False)
    (root / "companion.json").write_text('{"port": 9001}')
    assert cc.configured_port(root) == (9001, False)
    (root / "companion.local.json").write_text('{}')          # a local file without a port
    assert cc.configured_port(root) == (9001, False)
    (root / "companion.local.json").write_text('{"port": 9002}')
    assert cc.configured_port(root) == (9002, True) and cc.companion_port(root) == 9002
    monkeypatch.setenv("TRIBUNAL_PORT", "9003")
    assert cc.configured_port(root) == (9003, True)
    monkeypatch.setenv("TRIBUNAL_PORT", "70000")
    with pytest.raises(ValueError):
        cc.configured_port(root)


def test_busy_default_port_moves_to_the_next_free_one(root, stranger, monkeypatch):
    (root / "companion.json").write_text(json.dumps({"port": stranger}))
    states = {stranger: "other", stranger + 1: "other", stranger + 2: "free"}
    monkeypatch.setattr(cc, "probe", lambda port, r=None: states.get(port, "free"))
    action, port, note = cc.choose_port(root)
    assert (action, port) == ("bind", stranger + 2) and str(stranger) in note and str(stranger + 2) in note


def test_free_default_port_is_used_as_is_without_a_note(root):
    port = _free_port()
    (root / "companion.json").write_text(json.dumps({"port": port}))
    assert cc.choose_port(root) == ("bind", port, "")


def test_a_chosen_port_is_never_moved(root, stranger):
    (root / "companion.local.json").write_text(json.dumps({"port": stranger}))
    action, port, reason = cc.choose_port(root)
    assert (action, port) == ("blocked", stranger) and "explicitly" in reason


def test_no_free_port_in_range_is_reported(root, monkeypatch):
    monkeypatch.setattr(cc, "probe", lambda port, r=None: "other")
    action, port, reason = cc.choose_port(root)
    assert action == "blocked" and "no free port" in reason


def test_our_running_console_is_found_instead_of_starting_twice(root, ours):
    (root / "companion.json").write_text(json.dumps({"port": ours}))
    assert cc.choose_port(root) == ("running", ours, "")
    (root / "companion.local.json").write_text(json.dumps({"port": ours}))           # same for a chosen port
    assert cc.choose_port(root) == ("running", ours, "")


# ---------------------------------------------------------------- who is listening
def test_probe_tells_ours_from_another_install_and_from_strangers(root, ours, stranger, tmp_path_factory):
    assert cc.probe(ours, root) == "ours"
    assert cc.probe(ours, tmp_path_factory.mktemp("other-checkout")) == "other"      # same program, another folder
    assert cc.probe(stranger, root) == "other"
    assert cc.probe(_free_port(), root) == "free"


def test_verify_needs_the_token_on_both_sides(root, ours, stranger):
    assert cc.verify(ours, TOKEN) is True
    assert cc.verify(ours, "another-token") is False
    assert cc.verify(ours, "") is False
    assert cc.verify(stranger, TOKEN) is False                                       # says it is ours, cannot prove it
    assert cc.verify(_free_port(), TOKEN) is False


def test_hello_never_contains_the_token_and_only_signs_plain_nonces(root):
    plain = cc.hello_payload(root, TOKEN)
    assert plain["app"] == cc.APP_ID and "proof" not in plain and TOKEN not in json.dumps(plain)
    assert cc.hello_payload(root, TOKEN, "abc123")["proof"] == cc.hello_proof(TOKEN, "abc123")
    assert "proof" not in cc.hello_payload(root, TOKEN, "a b") and "proof" not in cc.hello_payload(root, TOKEN, "x" * 200)
    assert str(root) not in json.dumps(plain)                                        # the folder itself is not revealed


# ---------------------------------------------------------------- where it ended up
def test_active_port_follows_the_runtime_file_only_while_that_console_answers(root, ours):
    (root / "companion.json").write_text('{"port": 9001}')
    assert cc.active_port(root) == 9001                                              # nothing recorded
    cc.write_runtime(root, ours)
    assert cc.active_port(root) == ours
    dead = _free_port()
    (root / cc.RUNTIME_FILE).write_text(json.dumps({"port": dead, "pid": 1}))
    assert cc.active_port(root) == 9001                                              # a stale file is ignored
    (root / cc.RUNTIME_FILE).write_text("not json")
    assert cc.active_port(root) == 9001


def test_clear_runtime_only_removes_our_own_file(root):
    cc.write_runtime(root, 9001)
    cc.clear_runtime(root)
    assert not (root / cc.RUNTIME_FILE).exists()
    (root / cc.RUNTIME_FILE).write_text(json.dumps({"port": 9001, "pid": -1}))       # written by another process
    cc.clear_runtime(root)
    assert (root / cc.RUNTIME_FILE).exists()


# ---------------------------------------------------------------- the real server and `director do`
def test_companion_server_answers_hello_with_a_valid_proof(monkeypatch):
    import companion_server as cs
    server = cs.d.DashboardServer(("127.0.0.1", 0), cs.CompanionHandler)
    server.bridge_token = TOKEN
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        port = server.server_address[1]
        assert cc.probe(port, cs.ROOT) == "ours" and cc.verify(port, TOKEN) and not cc.verify(port, "wrong")
    finally:
        server.shutdown(); server.server_close()


@pytest.fixture
def do_env(tmp_path, monkeypatch):
    """`director do` with a token file of its own and the in-process fallback recorded instead of run."""
    import director
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "bridge.token").write_text(TOKEN)
    monkeypatch.setattr(director, "__file__", str(tmp_path / "director.py"))        # `do` looks for data/ next to itself
    ran = []
    monkeypatch.setattr(director.mission, "callback", lambda **kw: ran.append(kw))
    return director, ran, tmp_path


def _console(prove, posted):
    class Handler(_Quiet):
        def do_GET(self):
            nonce = parse_qs(urlsplit(self.path).query).get("nonce", [""])[0]
            self._json(cc.hello_payload(cc.ROOT, TOKEN if prove else "not-the-token", nonce))

        def do_POST(self):
            posted.append(self.headers.get("X-Tribunal-Token"))
            self.rfile.read(int(self.headers.get("Content-Length", 0)))
            self._json({"status": "started", "mission_id": "MSN-X"})
    return _serve(Handler)


def test_director_do_never_sends_the_token_to_a_listener_that_cannot_prove_itself(do_env, monkeypatch):
    from click.testing import CliRunner
    director, ran, tmp = do_env
    posted = []
    server = _console(prove=False, posted=posted)
    try:
        monkeypatch.setattr(cc, "active_port", lambda root=None: server.server_address[1])
        import companion_server
        monkeypatch.setattr(companion_server, "bridge_target_ok", lambda path: (True, path))
        result = CliRunner().invoke(director.cli, ["do", "-p", str(tmp), "--no-apply", "goal"])
        assert posted == [] and len(ran) == 1 and "unavailable" in result.output
        assert ran[0]["no_apply"] is True                       # found in a real run: the fallback applied anyway
    finally:
        server.shutdown(); server.server_close()


def test_director_do_takes_the_consoles_no_for_an_answer(do_env, monkeypatch):
    """Found in a real run: a request the console refused (400) was run here instead, around the very rule that
    refused it - and applied, --no-apply notwithstanding."""
    from click.testing import CliRunner
    director, ran, tmp = do_env
    posted = []

    class Refusing(_Quiet):
        def do_GET(self):
            nonce = parse_qs(urlsplit(self.path).query).get("nonce", [""])[0]
            self._json(cc.hello_payload(cc.ROOT, TOKEN, nonce))

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
            posted.append(body)
            self._json({"status": "rejected", "error": "이 폴더에는 지시할 수 없습니다"}, 400)
    server = _serve(Refusing)
    try:
        monkeypatch.setattr(cc, "active_port", lambda root=None: server.server_address[1])
        result = CliRunner().invoke(director.cli, ["do", "-p", str(tmp), "goal of five"])
        assert result.exit_code != 0 and ran == [] and "이 폴더에는 지시할 수 없습니다" in result.output
        assert posted[0]["create_project"] is True                # not a git folder: the console is asked to prepare it
    finally:
        server.shutdown(); server.server_close()


def test_director_do_without_a_console_keeps_the_consoles_folder_rule(do_env, monkeypatch):
    from click.testing import CliRunner
    director, ran, tmp = do_env
    monkeypatch.setattr(cc, "active_port", lambda root=None: 9)           # nothing listens there
    result = CliRunner().invoke(director.cli, ["do", "-p", str(Path(director.__file__).resolve().parent), "goal of five"])
    assert result.exit_code != 0 and ran == [] and "작업을 시킬 수 없습니다" in result.output


def test_director_do_posts_to_a_verified_console_and_never_through_a_proxy(do_env, monkeypatch):
    from click.testing import CliRunner
    director, ran, tmp = do_env
    posted, via_proxy = [], []

    class Proxy(_Quiet):                       # anything that reaches this stand-in proxy is a leak
        def do_GET(self):
            via_proxy.append(self.path); self._json({}, 502)
        do_POST = do_GET
    proxy = _serve(Proxy)
    server = _console(prove=True, posted=posted)
    try:
        for name in ("HTTP_PROXY", "http_proxy", "ALL_PROXY"):
            monkeypatch.setenv(name, f"http://127.0.0.1:{proxy.server_address[1]}")
        for name in ("NO_PROXY", "no_proxy"):
            monkeypatch.delenv(name, raising=False)
        monkeypatch.setattr(cc, "active_port", lambda root=None: server.server_address[1])
        result = CliRunner().invoke(director.cli, ["do", "-p", str(tmp), "--no-apply", "goal"])
        assert posted == [TOKEN] and ran == [] and "MSN-X" in result.output
        assert via_proxy == []
    finally:
        server.shutdown(); server.server_close(); proxy.shutdown(); proxy.server_close()


def test_a_console_that_moved_ports_is_still_found_before_starting_another(root, ours):
    """8081 was busy, the console took another port, 8081 became free again: a second start must not bind it."""
    free = _free_port()
    (root / "companion.json").write_text(json.dumps({"port": free}))
    cc.write_runtime(root, ours)
    assert cc.choose_port(root) == ("running", ours, "")


def test_an_older_console_without_hello_is_named_as_such(root):
    class Legacy(_Quiet):
        def do_GET(self):
            self._json({"csrf": "x", "orders": []} if self.path.startswith("/ops/state") else {"error": "not found"},
                       200 if self.path.startswith("/ops/state") else 404)
    server = _serve(Legacy)
    try:
        port = server.server_address[1]
        assert cc.probe(port, root) == "legacy"
        (root / "companion.json").write_text(json.dumps({"port": port}))
        action, where, reason = cc.choose_port(root)
        assert (action, where) == ("blocked", port) and "older" in reason
    finally:
        server.shutdown(); server.server_close()


def test_a_current_console_that_misses_hello_is_not_a_stranger(root):
    """Ours, but /ops/hello did not answer in time: its /ops/state (csrf + status, no orders) still stops a second start."""
    class Busy(_Quiet):
        def do_GET(self):
            self._json({"csrf": "x", "diagnostics": None, "status": {}} if self.path.startswith("/ops/state") else {"error": "busy"},
                       200 if self.path.startswith("/ops/state") else 500)
    server = _serve(Busy)
    try:
        assert cc.probe(server.server_address[1], root) == "legacy"
    finally:
        server.shutdown(); server.server_close()


def test_director_do_never_runs_a_goal_twice_when_the_answer_is_lost(do_env, monkeypatch):
    """From the review: the console answers only after its first ARCHITECT call, so a dropped connection after the
    request was sent must not start the same goal here as well."""
    from click.testing import CliRunner
    director, ran, tmp = do_env

    class Hanging(_Quiet):
        def do_GET(self):
            nonce = parse_qs(urlsplit(self.path).query).get("nonce", [""])[0]
            self._json(cc.hello_payload(cc.ROOT, TOKEN, nonce))

        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length", 0)))
            self.connection.close()                                   # took the request, never answered
    server = _serve(Hanging)
    try:
        monkeypatch.setattr(cc, "active_port", lambda root=None: server.server_address[1])
        import companion_server
        monkeypatch.setattr(companion_server, "bridge_target_ok", lambda path: (True, path))
        result = CliRunner().invoke(director.cli, ["do", "-p", str(tmp), "goal of five"])
        assert result.exit_code != 0 and ran == [] and "콘솔에서 작업이 시작됐는지" in result.output
    finally:
        server.shutdown(); server.server_close()


def test_the_bridge_folder_rule_cannot_be_dodged_and_skips_the_roots_themselves(tmp_path, monkeypatch):
    import companion_server as cs
    root = tmp_path / "work"; (root / "proj").mkdir(parents=True); (root / "Secret").mkdir()
    monkeypatch.setattr(cs, "bridge_config", lambda config=None: {"allowed_roots": [str(root)], "denied": [str(root / "Secret")]})
    assert cs.bridge_target_ok(str(root / "proj"))[0] is True
    assert cs.bridge_target_ok(str(root))[0] is False                                       # the root itself is not a project
    assert cs.bridge_target_ok(str(root / "Secret" / "x"))[0] is False
    assert cs.bridge_target_ok(str(root / "SECRET"))[0] is False                            # another spelling of a denied folder


def test_do_asks_to_prepare_only_a_named_folder_outside_any_repository(tmp_path):
    import subprocess
    import director
    lone = tmp_path / "lone"; lone.mkdir()
    repo = tmp_path / "repo"; (repo / "sub").mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    assert director._fresh_folder(lone) is True
    assert director._fresh_folder(repo) is False and director._fresh_folder(repo / "sub") is False
