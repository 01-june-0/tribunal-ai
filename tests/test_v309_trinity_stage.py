"""
v3.0.9 TRINITY STAGE: the 8081 console opens on a live visual stage (WebGL particles driven by the work ledger).
Server side this adds a fixed static allowlist, (the mission replay it once had was removed),
and keeps the strict CSP: the page may not rely on inline scripts or styles, or on any external host.
"""
import re
from pathlib import Path
from types import SimpleNamespace

from core import usage
from tests.test_v0238_dashboard_ux import env, server, _get_json  # noqa: F401
from tests.test_v301_companion_http import http_server, request  # noqa: F401

CONSOLE = Path(__file__).resolve().parents[1] / "console"


def result(duration=10.0, exit_code=0):
    return SimpleNamespace(stdout="ok", stderr="", exit_code=exit_code, duration_sec=duration, timed_out=False)


def record(role, cli, mission_id, run_id, stage, duration=10.0, exit_code=0):
    usage.set_context(role=role, stage=stage, run_id=run_id, mission_id=mission_id)
    rid = usage.call_started([cli], "prompt")
    usage.call_finished(rid, [cli], "prompt", result(duration, exit_code))


def test_stage_files_are_served_with_the_strict_csp(http_server):
    for path, marker in (("/", "trinity-canvas"), ("/stage.js", "TrinityStage"), ("/trinity.js", "window.Trinity"),
                         ("/stage.css", ".trinity")):
        code, body = request(http_server, "GET", path)
        assert code == 200 and marker.encode() in body, path
    import http.client
    conn = http.client.HTTPConnection("127.0.0.1", http_server.server_address[1], timeout=3)
    conn.request("GET", "/trinity.js")
    resp = conn.getresponse(); resp.read()
    assert "default-src 'self'" in resp.getheader("Content-Security-Policy")
    conn.close()


def test_only_the_allowlisted_console_files_are_served(http_server):
    for path in ("/stage.js.bak", "/../config.yaml", "/console/stage.js", "/companion.json", "/data/bridge.token"):
        assert request(http_server, "GET", path)[0] == 404, path


def test_stage_page_needs_no_inline_code_or_external_host():
    html = (CONSOLE / "index.html").read_text(encoding="utf-8")
    assert "Tribunal AI 자세히 보기" in html                                   # the workshop iframe is still there
    assert not re.search(r"<script(?![^>]*\bsrc=)", html)            # CSP default-src 'self': no inline script
    assert "style=" not in html and "<style" not in html              # ... and no inline style
    for name in ("index.html", "stage.js", "trinity.js", "stage.css"):
        text = (CONSOLE / name).read_text(encoding="utf-8")
        assert not re.search(r"https?://(?!127\.0\.0\.1)", text), name  # nothing is loaded from another host


def test_stage_only_calls_known_read_endpoints_and_the_chat_post():
    js = (CONSOLE / "stage.js").read_text(encoding="utf-8")
    called = set(re.findall(r"(?:getJSON|fetch)\('(/[a-z/_]+)", js))
    assert called == {"/ops/activity", "/status", "/chat/messages", "/chat", "/ops/roles", "/ops/mission/decide", "/ops/call", "/ops/record", "/ops/ai", "/ops/ai/refresh", "/providers/refresh",
                      "/ops/new",                       # /ops/new-project (the pattern stops at "-"): where a new project folder goes
                      "/ops/permissions",               # what the agent-mode Maker asks about first (AI settings > Permissions)
                      "/ops/open",                      # /ops/open-project (the pattern stops at "-"): opens the folder, changes nothing
                      "/result/clear",                  # the kept working copy of an applied result outside a task
                      "/result", "/run/inspect"}                       # read-only: what changed, and the ORDER of a run awaiting approval
    assert js.count("method:'POST'") == 13                            # writes: chat to ARCHITECT, a role change, a delivery decision, AI settings, "check now", AI status recheck, account actions, approve / reject a run, apply / discard a result that has no mission, open the project folder, try a result (plan + start), clear the kept copy of an applied result outside a task, a permission switch
    assert "fetch(kind==='approve'?'/run/approve':'/run/reject',{method:'POST'" in js
    assert "fetch(kind==='apply'?'/result/apply':'/result/discard',{method:'POST'" in js
    assert set(re.findall(r"accountPost\('(/[a-z/_]+)", js)) == {"/ops/ai/account", "/ops/ai/account/reveal"}     # both go through the one token-carrying helper
    assert "'X-Tribunal-Token':roleToken" in js                        # the role change carries the local token


def test_folder_picker_needs_the_local_token_and_returns_the_chosen_path(http_server, monkeypatch):
    import json
    import companion_server
    monkeypatch.setattr(companion_server, "pick_folder", lambda initial="": {"path": "E:/work/프로젝트"})
    assert request(http_server, "POST", "/ops/pick-folder")[0] == 403                    # no token: no dialog
    code, body = request(http_server, "POST", "/ops/pick-folder", headers={"X-Tribunal-Token": "test-token"})
    assert code == 200 and json.loads(body)["path"] == "E:/work/프로젝트"
    monkeypatch.setattr(companion_server, "pick_folder", lambda initial="": {"error": "busy"})
    assert request(http_server, "POST", "/ops/pick-folder", headers={"X-Tribunal-Token": "test-token"})[0] == 409


def test_only_one_folder_dialog_at_a_time_and_cancel_is_an_empty_path(monkeypatch):
    import companion_server
    from types import SimpleNamespace as NS
    seen = {}

    def fake_run(argv, capture_output, timeout):
        seen["argv"] = argv
        assert "error" in companion_server.pick_folder()                                   # a second dialog is refused
        return NS(returncode=0, stdout=b'{"path": ""}')
    monkeypatch.setattr(companion_server.subprocess, "run", fake_run)
    assert companion_server.pick_folder("E:/start") == {"path": ""}
    assert seen["argv"][1].endswith("pick_folder.py") and seen["argv"][2] == "E:/start"


def test_the_macos_folder_dialog_is_shown_by_system_events(monkeypatch):
    """Found by hand: the console runs in the background, and macOS refused osascript's own dialog there
    ("사용자 상호 작용이 허용되지 않습니다", -1713), so "폴더 선택…" always failed. System Events shows it instead;
    a refused permission (-1743) is said as such."""
    import subprocess
    import sys as _sys
    from pathlib import Path as _P
    src = (_P(__file__).resolve().parents[1] / "scripts" / "pick_folder.py").read_text(encoding="utf-8")
    assert '"  tell application \\"System Events\\"",' in src and '"    activate",' in src
    import scripts.pick_folder as pf
    monkeypatch.setattr(pf.sys, "platform", "darwin")
    seen = []
    def fake(argv, capture_output):
        seen.append(argv)
        return subprocess.CompletedProcess(argv, 1, b"", b"execution error: Not authorized (-1743)")
    monkeypatch.setattr(subprocess, "run", fake)
    try:
        pf.pick_macos("")
        raise AssertionError("expected exit 3")
    except SystemExit as stop:
        assert stop.code == 3
    monkeypatch.setattr(subprocess, "run", lambda argv, capture_output: subprocess.CompletedProcess(argv, 1, b"", b"User canceled. (-128)"))
    assert pf.pick_macos("") == ""
    import companion_server
    monkeypatch.setattr(companion_server.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 3, b"", b""))
    assert "자동화" in companion_server.pick_folder("")["error"]


def test_the_project_folder_opens_only_with_the_token_and_only_the_current_project(http_server, monkeypatch, tmp_path):
    """"폴더 열기" (Details tab) and the folder icon (top bar): the page sends no path, the server opens its own project."""
    import json
    import companion_server
    import dashboard_server
    from core.result_manager import ResultManager
    opened = []
    monkeypatch.setattr(ResultManager, "_open", staticmethod(lambda path: opened.append(path) or {"status": "ok", "path": path}))
    proj = tmp_path / "proj"; (proj / ".git").mkdir(parents=True)
    monkeypatch.setattr(dashboard_server, "cached_status_payload", lambda: {"project_path": str(proj)})
    assert request(http_server, "POST", "/ops/open-project")[0] == 403 and opened == []        # no token: nothing opens
    code, body = request(http_server, "POST", "/ops/open-project", headers={"X-Tribunal-Token": "test-token"}, body='{"path": "/etc"}')
    assert code == 200 and opened == [str(proj.resolve())] and json.loads(body)["path"] == str(proj.resolve())   # a sent path is ignored
    monkeypatch.setattr(dashboard_server, "cached_status_payload", lambda: {"project_path": str(tmp_path / "gone")})
    code, body = request(http_server, "POST", "/ops/open-project", headers={"X-Tribunal-Token": "test-token"})
    assert code == 409 and "프로젝트로 쓸 수 없습니다" in json.loads(body)["error"] and len(opened) == 1
    monkeypatch.setattr(dashboard_server, "cached_status_payload", lambda: {})
    assert request(http_server, "POST", "/ops/open-project", headers={"X-Tribunal-Token": "test-token"})[0] == 409
    html = (Path(__file__).resolve().parents[1] / "console" / "index.html").read_text(encoding="utf-8")
    assert 'id="top-open"' in html and 'aria-label="프로젝트 폴더 열기"' in html


def test_trying_a_result_needs_the_token_and_starts_only_the_shown_command(http_server, monkeypatch):
    """"실행해 보기": the plan is read, then that exact command is started; nothing runs without the local token."""
    import json
    from core import run_preview
    started = []
    monkeypatch.setattr(run_preview, "plan", lambda run_id, rm=None: {"found": True, "command": "python3 main.py", "where": "copy"})
    monkeypatch.setattr(run_preview, "start", lambda run_id, command, launcher=None, rm=None, expected_folder=None: started.append((run_id, command))
                        or {"status": "started" if command == "python3 main.py" else "stale", "command": command})
    body = json.dumps({"run_id": "RUN-1", "command": "python3 main.py"})
    assert request(http_server, "POST", "/ops/run-result", body=body)[0] == 403 and started == []
    code, out = request(http_server, "POST", "/ops/run-plan", headers={"X-Tribunal-Token": "test-token"}, body=json.dumps({"run_id": "RUN-1"}))
    assert code == 200 and json.loads(out)["command"] == "python3 main.py"
    code, out = request(http_server, "POST", "/ops/run-result", headers={"X-Tribunal-Token": "test-token"}, body=body)
    assert code == 200 and json.loads(out)["status"] == "started" and started == [("RUN-1", "python3 main.py")]
    code, out = request(http_server, "POST", "/ops/run-result", headers={"X-Tribunal-Token": "test-token"},
                        body=json.dumps({"run_id": "RUN-1", "command": "rm -rf ~"}))
    assert code == 409 and json.loads(out)["status"] == "stale"
    assert request(http_server, "POST", "/ops/run-plan", headers={"X-Tribunal-Token": "test-token"}, body=json.dumps({"run_id": "../x"}))[0] == 400
