"""core.call_activity: reading what a CLI did inside one call from the records the CLIs leave behind."""
import json
import os
from datetime import datetime, timedelta

import pytest

from core import call_activity as ca
from core import usage

SID = "00a91be6-d9e6-4e13-99b6-907b4f11a5bb"


@pytest.fixture(autouse=True)
def _fresh_cache():
    ca._codex_file_cache.clear()
    yield
    ca._codex_file_cache.clear()


def _write(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")


# ---------------------------------------------------------------- before the call
def test_prepare_gives_claude_a_session_id_and_leaves_the_rest_alone():
    argv, sid = ca.prepare("ANTHROPIC", ["claude", "--print"])
    assert argv[:2] == ["claude", "--print"] and argv[2] == "--session-id" and argv[3] == sid and ca._UUID_RE.match(sid)
    assert ca.prepare("ANTHROPIC", ["claude", "--version"]) == (["claude", "--version"], None)
    assert ca.prepare("ANTHROPIC", ["claude", "--print", "--session-id", "x"])[1] is None
    assert ca.prepare("OPENAI", ["codex", "exec", "-"]) == (["codex", "exec", "-"], None)


# ---------------------------------------------------------------- Claude transcript
def test_claude_events_tools_text_and_tool_errors(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
    cwd = str(tmp_path / "proj")
    _write(tmp_path / "projects" / "-proj" / f"{SID}.jsonl", [
        {"type": "queue-operation"},
        {"type": "user", "timestamp": "2026-01-01T00:00:00Z", "message": {"content": "SECRET PROMPT"}},
        {"type": "assistant", "timestamp": "2026-01-01T00:00:01Z", "message": {"content": [
            {"type": "thinking", "thinking": "hidden"},
            {"type": "tool_use", "id": "t1", "name": "Read", "input": {"file_path": cwd + "/src/a.py"}},
            {"type": "tool_use", "id": "t2", "name": "Grep", "input": {"pattern": "def ", "path": cwd}}]}},
        {"type": "user", "timestamp": "2026-01-01T00:00:02Z", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "t2", "is_error": True, "content": "FILE BODY"}]}},
        {"type": "assistant", "isSidechain": True, "message": {"content": [{"type": "text", "text": "sub"}]}},
        {"type": "assistant", "timestamp": "2026-01-01T00:00:03Z", "message": {"content": [
            {"type": "text", "text": "x" * 500}]}},
    ])
    with open(tmp_path / "projects" / "-proj" / f"{SID}.jsonl", "a") as fh:
        fh.write('{"type": "assistant", "message": {"content": [{"type": "te')      # a half-written last line
    events = ca.claude_events(SID, cwd)
    assert [(e["kind"], e["name"], e["error"]) for e in events] == [
        ("think", "", False), ("tool", "Read", False), ("tool", "Grep", True), ("say", "", False)]
    assert events[1]["detail"] == "src/a.py" and events[2]["detail"] == "def in ."
    assert len(events[3]["detail"]) == 500 and ca.SAY_CHARS > ca.DETAIL_CHARS      # the model's words are kept longer than a tool line
    assert len(ca._short("y" * 5000, ca.SAY_CHARS)) == ca.SAY_CHARS
    assert "SECRET" not in json.dumps(events) and "FILE BODY" not in json.dumps(events)


def test_claude_events_missing_or_malformed_id(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
    assert ca.claude_events(SID) is None                      # not written yet
    assert ca.claude_events("../../etc/passwd") is None       # never used as a path
    assert ca.claude_events(None) is None


# ---------------------------------------------------------------- Codex rollout
def _rollout(root, name, cwd, began, extra=()):
    """Laid out the way Codex does it: day folder and file name in local time."""
    local = datetime.fromisoformat(began.replace("Z", "+00:00")).astimezone()
    name = f"rollout-{local:%Y-%m-%dT%H-%M-%S}-{name}"
    path = root / "sessions" / f"{local.year:04d}" / f"{local.month:02d}" / f"{local.day:02d}" / name
    _write(path, [{"timestamp": began, "type": "session_meta", "payload": {"cwd": cwd, "timestamp": began}}, *extra])
    return path


def test_find_codex_rollout_matches_folder_and_start_time(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    cwd = str(tmp_path / "wt"); os.makedirs(cwd)
    _rollout(tmp_path, "rollout-old.jsonl", cwd, "2026-03-01T09:00:00Z")            # an earlier call, same folder
    _rollout(tmp_path, "rollout-other.jsonl", str(tmp_path), "2026-03-01T10:00:02Z")  # same time, other folder
    mine = _rollout(tmp_path, "rollout-mine.jsonl", cwd, "2026-03-01T10:00:02Z")
    assert ca.find_codex_rollout(cwd, "2026-03-01T10:00:00", "2026-03-01T10:01:00") == mine
    assert ca.find_codex_rollout(cwd, "2026-03-01T10:00:00", "2026-03-01T10:01:00", taken={str(mine)}) is None
    assert ca.find_codex_rollout(cwd, "2026-03-01T12:00:00", "2026-03-01T12:01:00") is None
    assert ca.find_codex_rollout(None, "2026-03-01T10:00:00") is None


def test_codex_events(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    cwd = str(tmp_path / "wt"); os.makedirs(cwd)

    def item(**fields):
        return {"timestamp": "2026-03-01T10:00:05Z", "type": "event_msg", "payload": {"type": "item_completed", "item": fields}}
    path = _rollout(tmp_path, "rollout-a.jsonl", cwd, "2026-03-01T10:00:02Z", [
        item(type="UserMessage", content=[{"type": "text", "text": "SECRET PROMPT"}]),
        item(type="Reasoning"),
        item(type="CommandExecution", command=["/bin/zsh", "-lc", f"cat {cwd}/a.py"], parsed_cmd=[{"cmd": f"cat {cwd}/a.py"}],
             exit_code=0, aggregated_output="FILE BODY"),
        item(type="CommandExecution", command=["/bin/zsh", "-lc", "false"], exit_code=1),
        item(type="AgentMessage", content=[{"type": "Text", "text": "looks fine"}]),
        {"timestamp": "2026-03-01T10:00:09Z", "type": "event_msg", "payload": {"type": "task_complete"}},
        {"timestamp": "2026-03-01T10:00:09Z", "type": "something_new", "payload": 3},
    ])
    events = ca.codex_events(path, cwd)
    assert [(e["kind"], e["detail"], e["error"]) for e in events] == [
        ("think", "", False), ("tool", "cat a.py", False), ("tool", "false", True), ("say", "looks fine", False), ("done", "", False)]
    assert "SECRET" not in json.dumps(events) and "FILE BODY" not in json.dumps(events)


# ---------------------------------------------------------------- Antigravity stream
def test_summarize_agy_line():
    cwd = "/work/wt"
    tool = {"event": "step_update", "step_update": {"state": "ACTIVE", "step_type": "tool", "tool_name": "write_file",
                                                    "tool_info": {"parameters": {"Path": "/work/wt/src/a.py"}}}}
    event = ca.summarize_agy_line(json.dumps(tool), cwd)
    assert (event["kind"], event["name"], event["detail"]) == ("tool", "write_file", "src/a.py")
    tool["step_update"]["state"] = "DONE"
    assert ca.summarize_agy_line(json.dumps(tool), cwd) is None                # one line per tool, not two
    ok = ca.summarize_agy_line(json.dumps({"event": "result", "result": {"status": "SUCCESS", "response": "BODY"}}))
    bad = ca.summarize_agy_line(json.dumps({"event": "result", "result": {"status": "ERROR"}}))
    assert (ok["kind"], ok["error"], bad["error"]) == ("done", False, True) and "BODY" not in json.dumps(ok)
    assert ca.summarize_agy_line("not json") is None and ca.summarize_agy_line("[1]") is None
    assert ca.summarize_agy_line(json.dumps({"event": "init", "init": {"tools": ["x"]}})) is None
    unknown = {"event": "step_update", "step_update": {"state": "ACTIVE", "step_type": "tool", "tool_name": "new_tool",
                                                       "tool_info": {"parameters": {"Content": "FILE BODY"}}}}
    assert ca.summarize_agy_line(json.dumps(unknown))["detail"] == ""          # unknown parameters are never copied


# ---------------------------------------------------------------- ledger + console answer
def test_ledger_keeps_cwd_and_trace_and_activity_reads_them(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
    rid = usage.call_started(["claude", "--print"], "prompt", cwd=str(tmp_path), trace_id=SID)
    row = usage.call_row(rid)
    assert row["cwd"] == str(tmp_path) and row["trace_id"] == SID
    assert usage.running_now()[0]["id"] == rid

    waiting = ca.activity(rid)
    assert waiting["known"] and not waiting["found"] and waiting["events"] == [] and waiting["status"] == "RUNNING"
    _write(tmp_path / "projects" / "-p" / f"{SID}.jsonl", [{"type": "assistant", "timestamp": "2026-01-01T00:00:01Z",
           "message": {"content": [{"type": "tool_use", "id": "t", "name": "Read", "input": {"file_path": "/x"}}]}}])
    seen = ca.activity(rid)
    assert seen["found"] and seen["source"] == "transcript" and seen["tools"] == 1 and seen["errors"] == 0

    unknown = ca.activity(999999)
    assert unknown["known"] is False and unknown["found"] is False


def test_activity_keeps_only_the_newest_events(tmp_path, monkeypatch):
    rid = usage.call_started(["agy"], "prompt", cwd=str(tmp_path))
    record = ca.stream_recorder("GOOGLE", rid, str(tmp_path))
    line = json.dumps({"event": "step_update", "step_update": {"state": "ACTIVE", "step_type": "tool", "tool_name": "read_file",
                                                               "tool_info": {"parameters": {"Path": str(tmp_path / "a")}}}})
    for _ in range(ca.MAX_EVENTS + 5):
        record(line)
    record("garbage that must not raise")
    out = ca.activity(rid)
    assert out["found"] and out["source"] == "stream" and out["total"] == ca.MAX_EVENTS + 5
    assert len(out["events"]) == ca.MAX_EVENTS and out["events"][0]["detail"] == "a"
    assert ca.stream_recorder("OPENAI", rid, None) is None and ca.stream_recorder("GOOGLE", None, None) is None


def test_old_database_gains_the_new_columns(tmp_path, monkeypatch):
    import sqlite3
    from core.db_path import get_db_path
    db = get_db_path()
    with sqlite3.connect(str(db)) as conn:
        conn.execute("DROP TABLE IF EXISTS ai_usage")
        conn.execute("""CREATE TABLE ai_usage (id INTEGER PRIMARY KEY AUTOINCREMENT, started_at TEXT NOT NULL, ended_at TEXT,
            status TEXT NOT NULL, provider TEXT NOT NULL, role TEXT, stage TEXT, run_id TEXT, mission_id TEXT, pid INTEGER,
            duration_sec REAL, prompt_chars INTEGER, output_chars INTEGER, tokens_in INTEGER, tokens_out INTEGER,
            tokens_total INTEGER, tokens_exact INTEGER DEFAULT 0, exit_code INTEGER, source TEXT DEFAULT 'live')""")
        conn.execute("INSERT INTO ai_usage (started_at, status, provider) VALUES ('2026-01-01T00:00:00', 'OK', 'OPENAI')")
    old = ca.activity(1)
    assert old["known"] and not old["found"]                 # a call from before this feature: no cwd to look up
    assert usage.call_started(["codex", "exec"], "p", cwd=str(tmp_path)) == 2


def test_codex_call_is_not_pinned_to_a_file_while_it_runs_and_never_shares_one(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    cwd = str(tmp_path / "wt"); os.makedirs(cwd)
    now = datetime.utcnow()
    first = usage.call_started(["codex", "exec"], "p", cwd=cwd)
    assert ca.activity(first)["found"] is False and not ca._codex_file_cache      # running + nothing yet: not remembered
    _rollout(tmp_path, "a.jsonl", cwd, (now + timedelta(seconds=1)).isoformat() + "Z")
    assert ca.activity(first)["found"] is True and not ca._codex_file_cache

    class Done:
        exit_code, stdout, stderr, duration_sec, timed_out = 0, "", "", 1.0, False
    usage.call_finished(first, ["codex", "exec"], "p", Done())
    assert ca.activity(first)["found"] is True and len(ca._codex_file_cache) == 1
    second = usage.call_started(["codex", "exec"], "p", cwd=cwd)                   # a retry in the same folder
    assert ca.activity(second)["found"] is False                                   # must not borrow the first one's file


def test_runner_wires_session_id_ledger_and_stream_callback(tmp_path, monkeypatch):
    """The real ProcessTreeRunner.run path with a stand-in executable named like the CLIs."""
    import stat
    import sys
    from core.process_runner import ProcessTreeRunner
    monkeypatch.setenv("DIRECTOR_ALLOW_REAL_CLI", "1")
    line = json.dumps({"event": "step_update", "step_update": {"state": "ACTIVE", "step_type": "tool", "tool_name": "read_file",
                                                               "tool_info": {"parameters": {"Path": str(tmp_path / "a.py")}}}})
    for name, body in (("claude", "import sys; print(' '.join(sys.argv[1:]))"), ("agy", f"print({line!r})")):
        script = tmp_path / name
        script.write_text(f"#!{sys.executable}\n{body}\n", encoding="utf-8")
        script.chmod(script.stat().st_mode | stat.S_IEXEC)
    if os.name == "nt":
        pytest.skip("stand-in executables need a shebang")

    res = ProcessTreeRunner.run([str(tmp_path / "claude"), "--print"], cwd=str(tmp_path), stdin_data="prompt", timeout=30)
    row = usage.call_row(usage.recent_calls(1)[0]["id"])
    assert res.exit_code == 0 and f"--session-id {row['trace_id']}" in res.stdout and row["cwd"] == str(tmp_path)

    res = ProcessTreeRunner.run([str(tmp_path / "agy")], cwd=str(tmp_path), stdin_data="prompt", timeout=30)
    out = ca.activity(usage.recent_calls(1)[0]["id"])
    assert res.exit_code == 0 and line in res.stdout                               # the call's own output is untouched
    assert out["found"] and [(e["name"], e["detail"]) for e in out["events"]] == [("read_file", "a.py")]

    monkeypatch.setattr(ca, "summarize_agy_line", lambda *a: 1 / 0)                 # a broken observer...
    res = ProcessTreeRunner.run([str(tmp_path / "agy")], cwd=str(tmp_path), stdin_data="prompt", timeout=30)
    assert res.exit_code == 0 and line in res.stdout                               # ...never disturbs the call


# ---------------------------------------------------------------- estimates (labelled as such in the console)
class _Result:
    def __init__(self, seconds, exit_code=0):
        self.exit_code, self.stdout, self.stderr, self.duration_sec, self.timed_out = exit_code, "", "", seconds, False


def _finished(argv0, role, stage, seconds, exit_code=0):
    usage.set_context(role=role, stage=stage, run_id=None, mission_id=None)
    rid = usage.call_started([argv0], "p")
    usage.call_finished(rid, [argv0], "p", _Result(seconds, exit_code))


def test_expected_duration_needs_enough_samples_and_prefers_the_same_ai():
    assert usage.expected_duration("OPENAI", "INSPECTOR", "REVIEWING") is None
    _finished("codex", "INSPECTOR", "REVIEWING", 10)
    _finished("codex", "INSPECTOR", "REVIEWING", 30)
    _finished("codex", "INSPECTOR", "REVIEWING", 999, exit_code=1)              # failures say nothing about a normal call
    assert usage.expected_duration("OPENAI", "INSPECTOR", "REVIEWING") is None  # two successes: not enough
    _finished("claude", "INSPECTOR", "REVIEWING", 50)
    assert usage.expected_duration("OPENAI", "INSPECTOR", "REVIEWING") == {"seconds": 30, "samples": 3, "basis": "any_ai"}
    _finished("codex", "INSPECTOR", "REVIEWING", 20)
    assert usage.expected_duration("OPENAI", "INSPECTOR", "REVIEWING") == {"seconds": 20, "samples": 3, "basis": "same_ai"}
    assert usage.expected_duration("OPENAI", "INSPECTOR", "DECIDING") is None   # another stage is another kind of call
    assert usage.expected_duration("OPENAI", None, None) is None


def test_overdue_rule_and_running_now_estimate():
    assert not usage.is_overdue(55, 30) and usage.is_overdue(61, 30)           # twice the median...
    assert not usage.is_overdue(15, 5) and usage.is_overdue(36, 5)             # ...and at least 30 s over it
    for seconds in (20, 20, 20):
        _finished("agy", "MAKER", "BUILDING", seconds)
    usage.set_context(role="MAKER", stage="BUILDING", run_id=None, mission_id=None)
    usage.call_started(["agy"], "p")
    now = usage.running_now()[0]
    assert now["estimate"] == {"seconds": 20, "samples": 3, "basis": "same_ai"} and now["overdue"] is False
    usage.set_context(role="ARCHITECT", stage="CHAT", run_id=None, mission_id=None)
    usage.call_started(["claude"], "p")
    assert [w["estimate"] for w in usage.running_now() if w["role"] == "ARCHITECT"] == [None]


def test_quiet_seconds_only_for_a_running_call(tmp_path, monkeypatch):
    import sqlite3
    from core.db_path import get_db_path
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
    rid = usage.call_started(["claude", "--print"], "prompt", cwd=str(tmp_path), trace_id=SID)
    assert ca.activity(rid)["quiet_sec"] is None                               # no record: unknown, not "quiet"
    with sqlite3.connect(str(get_db_path())) as conn:                           # the call began two minutes ago
        conn.execute("UPDATE ai_usage SET started_at=? WHERE id=?", ((datetime.utcnow() - timedelta(seconds=120)).isoformat(), rid))
    old = (datetime.utcnow() - timedelta(seconds=90)).isoformat() + "Z"
    _write(tmp_path / "projects" / "-p" / f"{SID}.jsonl", [{"type": "assistant", "timestamp": old,
           "message": {"content": [{"type": "tool_use", "id": "t", "name": "Read", "input": {"file_path": "/x"}}]}}])
    assert 88 <= ca.activity(rid)["quiet_sec"] <= 95
    usage.call_finished(rid, ["claude"], "prompt", _Result(1))
    assert ca.activity(rid)["quiet_sec"] is None


def test_paths_are_shortened_with_either_separator():
    """Found on Windows: the CLIs write `/` while the folder is reported with `\\`, so nothing was shortened and the
    reader saw the whole temp path."""
    from core import call_activity as ca
    assert ca._rel("C:\\work\\proj/src/a.py", "C:\\work\\proj") == "src/a.py"
    assert ca._rel("C:\\work\\proj\\src\\a.py", "C:\\work\\proj") == "src\\a.py"
    assert ca._rel("C:\\work\\project-other/a.py", "C:\\work\\proj") == "C:\\work\\project-other/a.py"   # not a prefix match
    assert ca._tidy("cat C:\\work\\proj/a.py && ls C:\\work\\proj", "C:\\work\\proj") == "cat a.py && ls ."
