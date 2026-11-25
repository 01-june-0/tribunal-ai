"""Phase 4 of docs/PACKAGING.md: `tribunal app`, the console in a window of its own (core/app_window.py).

No real window opens here: a stand-in for pywebview records what the code asks of it. The real window is checked by
`tribunal app --smoke` in the GitHub Actions installer job (macOS, Windows) and was checked by hand on a Mac."""
import json
import threading
from pathlib import Path

import pytest
from click.testing import CliRunner

import tribunal_cli
from core import app_window

ROOT = Path(__file__).resolve().parents[1]


class FakeEvent:
    def __init__(self):
        self.handlers = []

    def __iadd__(self, handler):
        self.handlers.append(handler)
        return self

    def fire(self):
        return [h() for h in self.handlers]


class FakeWindow:
    def __init__(self, confirm=True, page="TRIBUNAL AI · TRINITY"):
        self.events = type("Events", (), {})()
        self.events.closing = FakeEvent()
        self.events.loaded = threading.Event()
        self.confirm, self.page = confirm, page
        self.asked, self.destroyed = [], threading.Event()

    def create_confirmation_dialog(self, title, message):
        self.asked.append((title, message))
        return self.confirm

    def destroy(self):
        self.destroyed.set()

    def run_js(self, script):
        assert "#ai-setup" in script
        return self.page


class FakeWebview:
    """create_window + start like pywebview; `during` runs while the window is "open" (instead of a person)."""
    screens = []

    def __init__(self, window, during=None):
        self.window, self.during, self.created, self.started = window, during, None, None

    def create_window(self, title, url, **kw):
        self.created = (title, url, kw)
        return self.window

    def start(self, func=None, **kw):
        self.started = kw
        if func:
            self.window.events.loaded.set()
            func()
        elif self.during:
            self.during(self.window)


@pytest.fixture
def home(monkeypatch, tmp_path):
    monkeypatch.setenv("TRIBUNAL_HOME", str(tmp_path))
    (tmp_path / "data").mkdir()
    return tmp_path


def test_a_quiet_close_just_closes_and_the_page_keeps_its_storage(home, monkeypatch):
    monkeypatch.setattr(app_window, "busy", lambda url: False)
    results = []

    def person(w):
        results.extend(w.events.closing.fire())            # every close is held once and decided off the GUI thread
        assert w.destroyed.wait(5)
        results.extend(w.events.closing.fire())            # the close that follows goes through
    window = FakeWindow()
    fake = FakeWebview(window, during=person)
    state = app_window.show("http://127.0.0.1:9", lambda: True, webview_module=fake)
    assert results == [False, None] and not window.asked and state["stopped_work"] is False
    title, url, kw = fake.created
    assert (title, url) == ("Tribunal AI", "http://127.0.0.1:9") and kw["text_select"] is True
    assert kw["width"] >= 960 and kw["height"] >= 640 and kw["min_size"] == (960, 640)
    assert fake.started["private_mode"] is False
    assert fake.started["storage_path"] == str(home / "data" / "app-window")


def test_closing_while_working_asks_then_stops_the_work(home, monkeypatch):
    monkeypatch.setattr(app_window, "busy", lambda url: True)
    stopped = []
    monkeypatch.setattr(app_window, "stop_work", lambda url: stopped.append(url) or True)
    window = FakeWindow(confirm=True)

    def person(w):
        assert w.events.closing.fire() == [False]          # cancelled at first: the dialog decides
        assert w.destroyed.wait(5)
    state = app_window.show("http://127.0.0.1:9", lambda: True, webview_module=FakeWebview(window, during=person))
    assert len(window.asked) == 1 and "작업이 진행 중" in window.asked[0][1] and "Work is running" in window.asked[0][1]
    assert stopped == ["http://127.0.0.1:9"] and state["stopped_work"] is True
    assert window.events.closing.fire() == [None]           # the close that follows goes through


def test_saying_no_keeps_the_window_and_the_work(home, monkeypatch):
    monkeypatch.setattr(app_window, "busy", lambda url: True)
    monkeypatch.setattr(app_window, "stop_work", lambda url: pytest.fail("must not stop"))
    window = FakeWindow(confirm=False)
    answers = []

    def person(w):
        answers.append(w.events.closing.fire())
        for _ in range(250):                                  # the dialog runs on its own thread
            if w.asked:
                break
            threading.Event().wait(0.02)
        threading.Event().wait(0.1)
        answers.append(w.events.closing.fire())               # trying again after "no" asks again
    state = app_window.show("http://127.0.0.1:9", lambda: True, webview_module=FakeWebview(window, during=person))
    for _ in range(250):
        if len(window.asked) == 2:
            break
        threading.Event().wait(0.02)
    assert answers == [[False], [False]] and len(window.asked) == 2
    assert not window.destroyed.is_set() and state["stopped_work"] is False


def test_no_question_when_the_console_stays_on_anyway(home, monkeypatch):
    monkeypatch.setattr(app_window, "busy", lambda url: pytest.fail("not even asked"))
    window = FakeWindow()

    def person(w):
        w.events.closing.fire()
        assert w.destroyed.wait(5)
    app_window.show("http://127.0.0.1:9", lambda: False, webview_module=FakeWebview(window, during=person))
    assert not window.asked


def test_when_the_console_cannot_say_it_is_asked_like_busy(home, monkeypatch):
    monkeypatch.setattr(app_window, "busy", lambda url: None)          # no answer in time
    monkeypatch.setattr(app_window, "stop_work", lambda url: True)
    window = FakeWindow(confirm=True)

    def person(w):
        w.events.closing.fire()
        assert w.destroyed.wait(5)
    state = app_window.show("http://127.0.0.1:9", lambda: True, webview_module=FakeWebview(window, during=person))
    assert len(window.asked) == 1 and state["stopped_work"] is True


def test_the_installer_check_reads_the_page_and_closes(home, monkeypatch):
    state = app_window.show("http://127.0.0.1:9", lambda: True, smoke=True, webview_module=FakeWebview(FakeWindow()))
    assert state["smoke"] == "TRIBUNAL AI · TRINITY"
    monkeypatch.setattr(app_window, "SMOKE_TRIES", 3)
    monkeypatch.setattr(app_window, "SMOKE_PAUSE", 0.01)
    window = FakeWindow(page="")
    state = app_window.show("http://127.0.0.1:9", lambda: True, smoke=True, webview_module=FakeWebview(window))
    assert state["smoke"] == "" and window.destroyed.is_set()


def test_the_checks_watchdog_is_called_off_when_the_window_ends(home, monkeypatch):
    timers = []
    real = threading.Timer

    def spy(*a, **k):
        t = real(*a, **k)
        timers.append(t)
        return t
    monkeypatch.setattr(threading, "Timer", spy)
    app_window.show("http://127.0.0.1:9", lambda: True, smoke=True, webview_module=FakeWebview(FakeWindow()))
    assert len(timers) == 1 and timers[0].finished.is_set()          # cancelled: it can no longer end the process


def test_who_owns_the_console(home, monkeypatch):
    monkeypatch.setattr(app_window, "_alive", lambda pid: pid == 222)
    app_window.claim(555)
    assert app_window.owned(555) and not app_window.owned(556) and not app_window.owned(None)
    app_window.register(111); app_window.register(222); app_window.register(333)
    assert app_window.other_windows(111) == [222]
    assert not (home / "data" / "app-windows" / "333").exists()            # an ended window is cleared away
    app_window.unregister(111)
    app_window.release()
    assert not app_window.owned(555)


def test_busy_reads_the_activity(monkeypatch):
    class Reply:
        def __init__(self, data): self.data = json.dumps(data).encode("utf-8")
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return self.data
    replies = iter([{"missions": [{"live": False}], "working_now": []},
                    {"missions": [{"live": True}], "working_now": []},
                    {"missions": [], "working_now": [{"role": "maker"}]}])
    monkeypatch.setattr(app_window, "_open", lambda req, timeout: Reply(next(replies)))
    assert [app_window.busy("http://x") for _ in range(3)] == [False, True, True]

    def down(req, timeout):
        raise OSError("no answer")
    monkeypatch.setattr(app_window, "_open", down)
    assert app_window.busy("http://x") is None                        # unknown is not idle


def test_stop_work_is_the_stop_button_with_the_token(home, monkeypatch):
    (home / "data" / "bridge.token").write_text("secret-token\n", encoding="utf-8")
    monkeypatch.setattr("core.companion_config.bridge_token_path", lambda root: home / "data" / "bridge.token")
    sent = []

    class Reply:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *a): return False
    monkeypatch.setattr(app_window, "_open", lambda req, timeout: sent.append(req) or Reply())
    assert app_window.stop_work("http://127.0.0.1:9") is True
    req = sent[0]
    assert req.full_url == "http://127.0.0.1:9/ops/missions/stop" and req.get_method() == "POST"
    assert req.get_header("X-tribunal-token") == "secret-token" and req.get_header("Origin") == "http://127.0.0.1:9"


# ---- `tribunal app` ----------------------------------------------------------------------------------------------------

@pytest.fixture
def cli_home(home, monkeypatch):
    calls = {"stopped": 0, "opened": []}
    monkeypatch.setattr(tribunal_cli, "start_console", lambda wait=30.0: "http://127.0.0.1:9")
    monkeypatch.setattr(tribunal_cli, "stop_console", lambda: calls.__setitem__("stopped", calls["stopped"] + 1) or True)
    monkeypatch.setattr(tribunal_cli.webbrowser, "open", calls["opened"].append)
    monkeypatch.setattr(app_window, "unavailable", lambda: None)
    monkeypatch.setattr(app_window, "_alive", lambda pid: False)
    monkeypatch.setattr(app_window, "busy", lambda url: False)
    return calls


def test_the_window_that_started_the_console_turns_it_off(cli_home, monkeypatch):
    pids = iter([None, 4242, 4242])                        # not running, then started by this window
    monkeypatch.setattr(tribunal_cli, "_running_pid", lambda: next(pids))
    monkeypatch.setattr(app_window, "show", lambda url, will_stop, smoke=False: {"smoke": None, "stopped_work": False})
    out = CliRunner().invoke(tribunal_cli.cli, ["app"])
    assert out.exit_code == 0, out.output
    assert cli_home["stopped"] == 1 and not app_window.owned(4242)


def test_a_console_that_was_already_on_stays_on(cli_home, monkeypatch):
    monkeypatch.setattr(tribunal_cli, "_running_pid", lambda: 4242)
    seen = []
    monkeypatch.setattr(app_window, "show", lambda url, will_stop, smoke=False: seen.append(will_stop()) or {})
    assert CliRunner().invoke(tribunal_cli.cli, ["app"]).exit_code == 0
    assert seen == [False] and cli_home["stopped"] == 0


def test_no_window_means_the_browser_and_the_console_stays(cli_home, monkeypatch):
    pids = iter([None, 4242, 4242])
    monkeypatch.setattr(tribunal_cli, "_running_pid", lambda: next(pids))

    def broken(url, will_stop, smoke=False):
        raise RuntimeError("WebView2 runtime missing")
    monkeypatch.setattr(app_window, "show", broken)
    out = CliRunner().invoke(tribunal_cli.cli, ["app"])
    assert out.exit_code == 0 and cli_home["opened"] == ["http://127.0.0.1:9"] and cli_home["stopped"] == 0
    assert "WebView2" in out.output


def test_linux_opens_the_browser_and_the_check_says_so(cli_home, monkeypatch):
    monkeypatch.setattr(app_window, "unavailable", lambda: "이 운영체제에서는 창 대신 브라우저로 엽니다")
    out = CliRunner().invoke(tribunal_cli.cli, ["app"])
    assert out.exit_code == 0 and cli_home["opened"] == ["http://127.0.0.1:9"]
    out = CliRunner().invoke(tribunal_cli.cli, ["app"], env={"TRIBUNAL_APP_SMOKE": "1"})
    assert out.exit_code == 3 and "브라우저" in out.output


def test_the_check_reports_the_page(cli_home, monkeypatch):
    pids = iter([None, 4242, 4242])
    monkeypatch.setattr(tribunal_cli, "_running_pid", lambda: next(pids))
    monkeypatch.setattr(app_window, "show", lambda url, will_stop, smoke=False: {"smoke": "TRIBUNAL AI · TRINITY" if smoke else None})
    out = CliRunner().invoke(tribunal_cli.cli, ["app", "--smoke"])
    assert out.exit_code == 0 and "TRIBUNAL AI" in out.output and cli_home["stopped"] == 1


def test_work_left_running_is_stopped_cleanly_or_the_console_stays(cli_home, monkeypatch):
    monkeypatch.setattr(app_window, "busy", lambda url: True)          # e.g. a quit that bypassed the question
    monkeypatch.setattr(app_window, "show", lambda url, will_stop, smoke=False: {"stopped_work": False})
    stops = []
    monkeypatch.setattr(app_window, "stop_work", lambda url: stops.append(url) or True)
    pids = iter([None, 4242, 4242])
    monkeypatch.setattr(tribunal_cli, "_running_pid", lambda: next(pids))
    assert CliRunner().invoke(tribunal_cli.cli, ["app"]).exit_code == 0
    assert stops == ["http://127.0.0.1:9"] and cli_home["stopped"] == 1

    monkeypatch.setattr(app_window, "stop_work", lambda url: False)    # the stop did not go through
    pids = iter([None, 4343, 4343])
    monkeypatch.setattr(tribunal_cli, "_running_pid", lambda: next(pids))
    out = CliRunner().invoke(tribunal_cli.cli, ["app"])
    assert out.exit_code == 0 and cli_home["stopped"] == 1 and "켜 둡니다" in out.output
    assert not app_window.owned(4343)


def test_an_owner_record_left_behind_does_not_turn_off_a_console_already_on(cli_home, monkeypatch):
    app_window.claim(4242)                                              # left by a window that crashed
    monkeypatch.setattr(tribunal_cli, "_running_pid", lambda: 4242)
    seen = []
    monkeypatch.setattr(app_window, "show", lambda url, will_stop, smoke=False: seen.append(will_stop()) or {})
    assert CliRunner().invoke(tribunal_cli.cli, ["app"]).exit_code == 0
    assert seen == [False] and cli_home["stopped"] == 0


def test_detach_on_linux_opens_as_before(cli_home, monkeypatch):
    monkeypatch.setattr(app_window, "unavailable", lambda: "browser here")
    monkeypatch.setattr(tribunal_cli.subprocess, "Popen", lambda *a, **k: pytest.fail("no window to detach"))
    out = CliRunner().invoke(tribunal_cli.cli, ["app", "--detach"])
    assert out.exit_code == 0 and "http://127.0.0.1:9" in out.output and cli_home["opened"] == ["http://127.0.0.1:9"]


def test_detach_starts_the_icons_command_and_returns(monkeypatch):
    monkeypatch.setattr(app_window, "unavailable", lambda: None)
    started = []
    monkeypatch.setattr(tribunal_cli.subprocess, "Popen", lambda cmd, **kw: started.append(cmd))
    assert CliRunner().invoke(tribunal_cli.cli, ["app", "--detach"]).exit_code == 0
    assert started and started[0][-4:] == ["-m", "tribunal_cli", "app", "--from-shortcut"]


def test_the_window_library_is_installed_only_where_it_is_used():
    line = "pywebview>=6.0; sys_platform == 'darwin' or sys_platform == 'win32'"
    assert line in (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert line in (ROOT / "requirements.txt").read_text(encoding="utf-8")
    for name in ("install.sh", "install.ps1"):
        assert "app --detach" in (ROOT / name).read_text(encoding="utf-8")
