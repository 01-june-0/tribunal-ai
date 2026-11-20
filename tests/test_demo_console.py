"""scripts/demo_console.py: an invented data set that the real console code can read, with nothing real in it."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _run(code_or_args, env_extra, as_code=False):
    env = {k: v for k, v in os.environ.items() if k not in ("DIRECTOR_TESTING", "TEST_DB_PATH")}
    env.update(env_extra)
    cmd = [sys.executable, "-c", code_or_args] if as_code else [sys.executable, str(ROOT / "scripts" / "demo_console.py"), *code_or_args]
    return subprocess.run(cmd, cwd=str(ROOT), env=env, capture_output=True, text=True, timeout=120)


@pytest.fixture(scope="module")
def demo(tmp_path_factory):
    folder = tmp_path_factory.mktemp("demo")
    seeded = _run(["--dir", str(folder), "--seed-only"], {})
    assert seeded.returncode == 0, seeded.stderr
    return folder


def test_db_path_override_needs_an_absolute_path_and_yields_to_test_isolation(monkeypatch, tmp_path):
    from core import db_path
    isolated = db_path.get_db_path()
    monkeypatch.setenv("TRIBUNAL_DB_PATH", str(tmp_path / "x.db"))
    assert db_path.get_db_path() == isolated                      # the test database always wins
    monkeypatch.delenv("DIRECTOR_TESTING")
    assert db_path.get_db_path() == tmp_path / "x.db"
    assert db_path.get_lock_dir() == tmp_path / "locks"
    monkeypatch.setenv("TRIBUNAL_DB_PATH", "relative/x.db")
    with pytest.raises(ValueError):                               # never a silent fall-back to the real records
        db_path.get_db_path()


def test_seed_refuses_a_folder_that_already_has_data(demo):
    again = _run(["--dir", str(demo), "--seed-only"], {})
    assert again.returncode != 0 and "already holds a data set" in again.stderr


def test_the_console_code_reads_the_demo_set(demo):
    """Every seeded call shows its inner activity through the same reader the real console uses."""
    probe = """
import json
from core import call_activity as ca, usage
from core.mission import MissionStore
from core.db_path import get_db_path
rows = usage._rows()
acts = [ca.activity(r["id"]) for r in rows]
print(json.dumps({
  "db": str(get_db_path()), "calls": len(rows), "found": sum(a["found"] for a in acts),
  "tools": sum(a["tools"] for a in acts), "errors": sum(a["errors"] for a in acts),
  "providers": sorted({r["provider"] for r in rows}),
  "missions": sorted((m["mission_id"], m["status"]) for m in MissionStore().all()),
  "estimate": usage.expected_duration("GOOGLE", "BUILDER", "BUILDING"),
}))
"""
    out = _run(probe, {"TRIBUNAL_DB_PATH": str(demo / "director.db"), "CLAUDE_CONFIG_DIR": str(demo / "claude"),
                       "CODEX_HOME": str(demo / "codex")}, as_code=True)
    assert out.returncode == 0, out.stderr
    data = json.loads(out.stdout.strip().splitlines()[-1])
    assert data["db"] == str(demo / "director.db")
    assert data["calls"] >= 20 and data["found"] == data["calls"]           # no call without its record
    assert data["tools"] > data["calls"] and data["errors"] >= 1            # the "오류만" filter has something to show
    assert data["providers"] == ["ANTHROPIC", "GOOGLE", "OPENAI"]
    assert [status for _, status in data["missions"]] == ["DONE", "DONE", "RUNNING"]
    assert data["estimate"] and data["estimate"]["samples"] >= 3            # the time estimate appears from the start


def test_nothing_from_this_machine_ends_up_in_the_demo_set(demo):
    home = str(Path.home())
    for path in demo.rglob("*"):
        if path.is_file() and path.suffix in (".json", ".jsonl", ".ndjson"):
            text = path.read_text(encoding="utf-8")
            assert home not in text and str(ROOT) not in text, path
    import sqlite3
    with sqlite3.connect(str(demo / "director.db")) as conn:
        dump = "\n".join(conn.iterdump())
    assert home not in dump and str(ROOT) not in dump


def _real_data_snapshot():
    data = ROOT / "data"
    names = ("director.db", "role_settings.json", "bridge.token", "cli_settings.json", "companion.port")
    stamp = {n: (data / n).stat().st_mtime_ns for n in names if (data / n).exists()}
    missions = sorted(p.name for p in (data / "missions").glob("*.json")) if (data / "missions").exists() else []
    runs = sorted(p.name for p in (ROOT / "runs").glob("RUN-DEMO*")) if (ROOT / "runs").exists() else []
    return stamp, missions, runs


def test_seeding_leaves_the_real_data_folder_alone(tmp_path):
    before = _real_data_snapshot()
    assert _run(["--dir", str(tmp_path / "d"), "--seed-only"], {}).returncode == 0
    assert _real_data_snapshot() == before and not (tmp_path / "d" / "bridge.token").exists()


def test_no_live_set_has_no_open_run(tmp_path):
    """--no-live is a still picture: no mission is running and no run is left mid-pipeline."""
    code = """
import sys, json, sqlite3
sys.path.insert(0, "scripts")
import demo_console as dc
from datetime import datetime, timezone
from pathlib import Path
demo = dc.Demo(Path(%r))
demo.seed(datetime.now(timezone.utc)); demo.close_live_mission()
from core.mission import MissionStore
con = sqlite3.connect(str(demo.dir / "director.db"))
print(json.dumps({"open": con.execute("select count(*) from runs where current_state not in ('PASS','FAIL')").fetchone()[0],
                  "statuses": sorted(m["status"] for m in MissionStore().all())}))
""" % str(tmp_path)
    out = _run(code, {}, as_code=True)
    assert out.returncode == 0, out.stderr
    assert json.loads(out.stdout.strip().splitlines()[-1]) == {"open": 0, "statuses": ["DONE", "DONE", "DONE"]}


@pytest.fixture
def demo_server(tmp_path, monkeypatch):
    """The demo's own server class, in this process, on the isolated test database."""
    import threading
    import types
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    import demo_console as dc
    from core.chat_manager import ChatManager
    from core.state_machine import StateMachine
    StateMachine(); ChatManager()                                 # the tables Demo.__init__ creates
    server = dc.serve(types.SimpleNamespace(dir=tmp_path), 0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield server
    server.shutdown(); server.server_close()


def _http(server, path, method="GET", body=None, headers=None):
    import urllib.error
    import urllib.request
    port = server.server_address[1]
    request = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=body, method=method, headers=headers or {})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(request, timeout=10) as response:
            return response.status, json.loads(response.read().decode("utf-8") or "null")
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read().decode("utf-8") or "null")


def test_demo_server_is_read_only_and_keeps_the_real_machine_out(demo_server):
    from core import companion_config as cc
    from core import role_settings
    token = {"X-Tribunal-Token": demo_server.bridge_token, "Content-Type": "application/json"}
    before = _real_data_snapshot(), (role_settings.PATH.read_bytes() if role_settings.PATH.exists() else None)
    roles = json.dumps({"head": "openai", "builder": "claude", "reviewer": "antigravity"}).encode()
    for path, body in (("/ops/roles", roles), ("/chat", b"message=hi"), ("/project", b"path=/tmp"), ("/ops/pick-folder", b""),
                       ("/ops/mission/decide", b"mission_id=MSN-DEMO-0003&action=discard"), ("/bridge/missions", b"{}"),
                       ("/ops/shutdown", b""), ("/providers/refresh", b"")):
        assert _http(demo_server, path, "POST", body, token)[0] == 403, path
    assert _http(demo_server, "/bridge/projects", headers=token)[0] == 403       # would list real project folders
    status, roles_seen = _http(demo_server, "/ops/roles")
    assert status == 200 and roles_seen == {"roles": {"head": "claude", "builder": "antigravity", "reviewer": "openai"},
                                            "independence": "full", "csrf": ""}
    status, ai = _http(demo_server, "/ops/ai")                                  # invented plan and limits, nothing looked up
    assert status == 200 and ai["limits"]["claude"]["plan"] == "max" and ai["settings"]["claude"]["model"] == "sonnet"
    assert _http(demo_server, "/ops/ai", "POST", json.dumps(ai["settings"]).encode(), token)[0] == 403
    assert _http(demo_server, "/ops/ai/refresh", "POST", b"{}", token)[0] == 403
    assert ai["alerts"][0]["cli"] == "openai" and ai["settings"]["usage_poll_minutes"] == 5
    status, state = _http(demo_server, "/ops/state")
    assert status == 200 and state["diagnostics"] is None and state["allowed_projects"] == []
    assert (_real_data_snapshot(), (role_settings.PATH.read_bytes() if role_settings.PATH.exists() else None)) == before
    # ... and it is not mistaken for this folder's real console
    port = demo_server.server_address[1]
    assert cc.probe(port, cc.ROOT) == "other" and _http(demo_server, "/ops/hello")[1]["app"] == cc.APP_ID


def test_demo_blocks_every_ai_call(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    import demo_console as dc
    from core.process_runner import ProcessTreeRunner
    monkeypatch.setattr(ProcessTreeRunner, "run", ProcessTreeRunner.run)         # restored after the test
    dc.block_real_ai_calls()
    with pytest.raises(RuntimeError, match="demo console"):
        ProcessTreeRunner.run(["claude", "--print"], stdin_data="x")
