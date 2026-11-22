"""The record on the Overview tab (core/work_log.py): AI calls, Tribunal's own steps and the user's decisions as one
list, and one line in full. A value is shown only when a record of it exists; a file's content is tied to a call or
a test round only when the file was written inside that call's or round's time window."""
import json
import os
import time
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from core import usage, work_log
from core.state_machine import StateMachine

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "console" / "stage.js").read_text(encoding="utf-8")
HTML = (ROOT / "console" / "index.html").read_text(encoding="utf-8")


def _result(stdout="ok", exit_code=0):
    return SimpleNamespace(stdout=stdout, stderr="", exit_code=exit_code, duration_sec=1.5, timed_out=False)


def _call(stage, role, run_id, argv=("codex", "exec", "-m", "gpt-x", "-c", 'model_reasoning_effort="high"')):
    usage.set_context(role=role, stage=stage, run_id=run_id, mission_id=None)
    rid = usage.call_started(list(argv), "prompt")
    usage.call_finished(rid, list(argv), "prompt", _result())
    return rid


@pytest.fixture
def run(tmp_path, monkeypatch):
    monkeypatch.setattr(work_log, "_runs_dir", lambda: tmp_path)
    run_id = "RUN-LOG-" + os.urandom(4).hex().upper()
    sm = StateMachine()
    sm.create_run(run_id, str(tmp_path / "proj"), "add a thing")
    (tmp_path / run_id).mkdir()
    return SimpleNamespace(id=run_id, sm=sm, dir=tmp_path / run_id)


def test_model_and_effort_come_from_the_command_line():
    assert work_log.model_of(["claude", "--print", "--model", "sonnet", "--effort", "low"]) == ("sonnet", "low")
    assert work_log.model_of(["codex", "exec", "-m", "gpt-x", "-c", 'model_reasoning_effort="high"']) == ("gpt-x", "high")
    assert work_log.model_of(["agy", "--print"]) == ("", "")              # nothing asked for: the CLI's own default
    assert work_log.model_of([]) == ("", "")


def test_a_call_is_recorded_with_its_model_and_shows_only_its_own_result(run):
    for state in ("PLANNING", "ORDER_READY", "BUILDING"):
        run.sm.transition_to(run.id, state, "x")
    first = _call("BUILDING", "MAKER", run.id)
    (run.dir / "maker.json").write_text(json.dumps({"status": "COMPLETED", "files_modified": ["a.py", "b.py"], "summary": "did it"}), encoding="utf-8")
    detail = work_log.detail(f"call-{first}")
    assert detail["model"] == "gpt-x" and detail["effort"] == "high" and detail["exit_code"] == 0
    assert detail["result"] == {"type": "build", "files": ["a.py", "b.py"], "summary": "did it", "status": "COMPLETED", "error": ""}
    assert "maker.json" in detail["sources"] and detail["result_missing"] is False
    row = next(r for r in work_log.rows() if r["key"] == f"call-{first}")
    assert row["result"] == {"type": "build", "files": 2} and row["group"]["key"] == run.id and row["group"]["title"] == "add a thing"
    # a file written long after the call belongs to a later round: it is not shown as this call's result
    late = time.time() + 600
    os.utime(run.dir / "maker.json", (late, late))
    second = _call("BUILDING", "MAKER", run.id)
    again = work_log.detail(f"call-{first}")
    assert again["result"] is None and again["result_missing"] is True   # said as missing, with no guessed cause
    assert next(r for r in work_log.rows() if r["key"] == f"call-{first}")["result"] is None
    assert work_log.detail(f"call-{second}")["result"] is None            # nor guessed for the newer call


def test_a_test_round_shows_the_record_of_that_round(run):
    for state in ("PLANNING", "ORDER_READY", "BUILDING", "VERIFYING"):
        run.sm.transition_to(run.id, state, "x")
    red = {"passed": False, "test": {"command": "pytest", "executed": True, "passed": False, "exit_code": 1, "output": "x" * 5000 + "1 failed"},
           "test_counts": {"passed": 1, "failed": 1, "total": 2}, "git_status": " M a.py"}
    (run.dir / "repair_history.json").write_text(json.dumps([{"round": 1, "verification": red}]), encoding="utf-8")
    for state, why in (("REVIEWING", "x"), ("DECIDING", "x"), ("BUILDING", "ARCHITECT requested correction round 1"), ("VERIFYING", "x")):
        run.sm.transition_to(run.id, state, why)
    green = dict(red, passed=True, test_counts={"passed": 2, "failed": 0, "total": 2}, test=dict(red["test"], passed=True, exit_code=0, output="2 passed"))
    (run.dir / "verification.json").write_text(json.dumps(green), encoding="utf-8")
    rounds = sorted((r for r in work_log.rows() if r.get("event") == "verify" and r["run_id"] == run.id), key=lambda r: r["round"])
    assert [(r["round"], r["rounds"], r["passed"], r["counts"]["failed"]) for r in rounds] == [(1, 2, False, 1), (2, 2, True, 0)]
    first = work_log.detail(rounds[0]["key"])
    assert first["found"] and first["test"]["exit_code"] == 1 and first["test"]["output_tail"].endswith("1 failed")
    assert len(first["test"]["output_tail"]) == work_log.TAIL_CHARS and first["changed"] == [" M a.py"]
    assert first["sources"][0] == "repair_history.json" and work_log.detail(rounds[1]["key"])["sources"][0] == "verification.json"
    # the last round's file written outside its window (an older file left behind) is not shown as this round
    old = time.time() - 3600
    os.utime(run.dir / "verification.json", (old, old))
    assert work_log.detail(rounds[1]["key"])["found"] is False


def test_a_test_run_that_no_repair_round_followed_is_not_given_a_rounds_record(run):
    """Stopped after the build, approved, tested again: the first test run has no record that can be tied to it."""
    for state in ("PLANNING", "ORDER_READY", "BUILDING", "VERIFYING"):
        run.sm.transition_to(run.id, state, "x")
    run.sm.transition_to(run.id, "HUMAN_REQUIRED", "Scope violation: Dependency configuration modified: req.txt")
    with usage._conn() as conn:                       # the engine reopens a stopped run this way after an approval
        conn.execute("INSERT INTO state_transitions (run_id, from_state, to_state, details, timestamp) VALUES (?, 'HUMAN_REQUIRED', 'VERIFYING', 'reopened', ?)",
                     (run.id, datetime.utcnow().isoformat()))
    other = {"passed": True, "test": {"command": "pytest", "executed": True, "passed": True, "exit_code": 0, "output": "ok"},
             "test_counts": {"passed": 2, "failed": 0, "total": 2}}
    (run.dir / "repair_history.json").write_text(json.dumps([{"round": 1, "verification": other}]), encoding="utf-8")
    (run.dir / "verification.json").write_text(json.dumps(other), encoding="utf-8")
    rounds = sorted((r for r in work_log.rows() if r.get("event") == "verify" and r["run_id"] == run.id), key=lambda r: r["round"])
    assert [(r["round"], r["known"]) for r in rounds] == [(1, False), (2, True)]
    stop = next(r for r in work_log.rows() if r.get("event") == "end" and r["run_id"] == run.id)
    assert work_log.detail(stop["key"])["stage"] == "POST_BUILD" and work_log.detail(stop["key"])["is_last"] is False


def test_a_decision_tribunal_changed_is_not_shown_as_the_calls_own(run):
    for state in ("PLANNING", "ORDER_READY", "BUILDING", "VERIFYING", "REVIEWING", "DECIDING"):
        run.sm.transition_to(run.id, state, "x")
    rid = _call("DECIDING", "ARCHITECT", run.id, argv=("claude", "--print"))
    (run.dir / "decision.json").write_text(json.dumps({"decision": "HUMAN_REQUIRED", "rationale": "Overridden by Orchestrator: gate"}), encoding="utf-8")
    assert work_log.detail(f"call-{rid}")["result"]["changed_by_tribunal"] is True
    assert next(r for r in work_log.rows() if r["key"] == f"call-{rid}")["result"]["changed_by_tribunal"] is True
    (run.dir / "decision.json").write_text(json.dumps({"decision": "PASS", "rationale": "all good"}), encoding="utf-8")
    assert work_log.detail(f"call-{rid}")["result"]["changed_by_tribunal"] is False
    assert "x.changed_by_tribunal?T('Tribunal이 바꾼 최종 판단'):T('이 호출의 판단')" in JS


def test_an_ending_counts_only_what_came_before_it_and_keeps_its_own_answer(run):
    run.sm.transition_to(run.id, "HUMAN_REQUIRED", "APPROVAL_REQUIRED: x")
    first = next(r for r in work_log.rows() if r.get("event") == "end" and r["run_id"] == run.id)
    with usage._conn() as conn:                       # reopened without a decision, stopped again, then approved
        now = datetime.utcnow()
        conn.execute("INSERT INTO state_transitions (run_id, from_state, to_state, details, timestamp) VALUES (?, 'HUMAN_REQUIRED', 'ORDER_READY', 'retry', ?)",
                     (run.id, (now + timedelta(seconds=1)).isoformat()))
        conn.execute("INSERT INTO state_transitions (run_id, from_state, to_state, details, timestamp) VALUES (?, 'ORDER_READY', 'HUMAN_REQUIRED', 'APPROVAL_REQUIRED: x', ?)",
                     (run.id, (now + timedelta(seconds=2)).isoformat()))
        conn.execute("INSERT INTO audit_logs (run_id, agent, action, payload, timestamp) VALUES (?, 'HUMAN', 'HUMAN_APPROVAL', '{}', ?)",
                     (run.id, (now + timedelta(seconds=3)).isoformat()))
        conn.execute("UPDATE ai_usage SET started_at=? WHERE run_id=?", ((now + timedelta(seconds=5)).isoformat(), run.id))
    _call("BUILDING", "MAKER", run.id)
    with usage._conn() as conn:
        conn.execute("UPDATE ai_usage SET started_at=? WHERE run_id=?", ((datetime.utcnow() + timedelta(seconds=5)).isoformat(), run.id))
    detail = work_log.detail(first["key"])
    assert "answer" not in detail and detail["totals"]["calls"] == 0 and detail["is_last"] is False


def test_a_failed_read_is_said_not_shown_as_an_empty_record(monkeypatch):
    import dashboard_server as d
    monkeypatch.setattr(work_log, "rows", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("locked")))
    assert d._work_log() is None
    assert "logLost:a.log===null" in JS and "m.logLost?T('기록을 읽지 못했습니다. 곧 다시 시도합니다.')" in JS


def test_an_earlier_rounds_review_and_decision_come_from_the_repair_they_led_to(run):
    for state in ("PLANNING", "ORDER_READY", "BUILDING", "VERIFYING", "REVIEWING"):
        run.sm.transition_to(run.id, state, "x")
    review = _call("REVIEWING", "INSPECTOR", run.id, argv=("agy", "--print"))
    run.sm.transition_to(run.id, "DECIDING", "x")
    decide = _call("DECIDING", "ARCHITECT", run.id, argv=("claude", "--print"))
    assert work_log.detail(f"call-{decide}")["result_missing"] is True     # nothing saved yet: said, not guessed
    run.sm.transition_to(run.id, "BUILDING", "ARCHITECT requested correction round 1")
    (run.dir / "repair_history.json").write_text(json.dumps([{"round": 1, "review": {"verdict": "changes_required", "p1": ["fix it"]},
                                                            "architect": {"decision": "FAIL", "rationale": "red"}, "verification": {}}]), encoding="utf-8")
    got = work_log.detail(f"call-{review}")
    assert got["result"]["verdict"] == "changes_required" and got["result"]["findings"] == [{"level": "p1", "text": "fix it"}]
    assert got["sources"][-1] == "repair_history.json"
    got = work_log.detail(f"call-{decide}")
    assert got["result"]["decision"] == "FAIL" and got["result"]["file"] == "repair_history.json" and got["result_missing"] is False
    # a later cycle's calls are not given round 1's answers
    for state in ("VERIFYING", "REVIEWING"):
        run.sm.transition_to(run.id, state, "x")
    later = _call("REVIEWING", "INSPECTOR", run.id, argv=("agy", "--print"))
    assert work_log.detail(f"call-{later}")["result"] is None


def test_endings_and_my_decisions_are_lines_too(run):
    run.sm.transition_to(run.id, "HUMAN_REQUIRED", "APPROVAL_REQUIRED: USER_DECISION_REQUIRED (pay)")
    run.sm.log_audit(run.id, "HUMAN", "HUMAN_REJECTED", json.dumps({"stage": "ENTRY", "reason": "APPROVAL_REQUIRED: pay"}))
    mine = [r for r in work_log.rows() if r["run_id"] == run.id]
    assert [(r["kind"], r.get("event") or r.get("action")) for r in mine] == [("me", "HUMAN_REJECTED"), ("sys", "end")]
    stop = work_log.detail(mine[1]["key"])
    assert stop["state"] == "HUMAN_REQUIRED" and stop["stage"] == "ENTRY" and stop["answer"]["action"] == "HUMAN_REJECTED" and stop["is_last"]
    assert stop["totals"]["calls"] == 0 and "gates" not in stop
    said = work_log.detail(mine[0]["key"])
    assert said["action"] == "HUMAN_REJECTED" and said["stage"] == "ENTRY" and said["maker_ran"] is False and said["resumed"] is False


def test_only_known_lines_can_be_asked_for(run):
    for bad in ("", "call-", "tr-1; DROP", "x-1", "call-1/../2", None):
        with pytest.raises(ValueError):
            work_log.detail(bad)
    assert work_log.detail("call-99999999")["known"] is False
    assert work_log.detail("tr-99999999")["known"] is False and work_log.detail("au-99999999")["known"] is False
    run.sm.transition_to(run.id, "PLANNING", "secret planning note")
    with usage._conn() as conn:
        tid = conn.execute("SELECT id FROM state_transitions WHERE run_id=? AND to_state='PLANNING'", (run.id,)).fetchone()[0]
        run.sm.log_audit(run.id, "ORCHESTRATOR", "VERIFICATION", "{}")
        aid = conn.execute("SELECT id FROM audit_logs WHERE run_id=? ORDER BY id DESC LIMIT 1", (run.id,)).fetchone()[0]
    assert work_log.detail(f"tr-{tid}") == {"key": f"tr-{tid}", "known": False}       # not a line of the record
    assert work_log.detail(f"au-{aid}") == {"key": f"au-{aid}", "known": False}
    assert work_log._run_dir("../etc") is None and work_log._run_dir("a/b") is None


def test_the_list_never_shows_a_stretch_with_one_kind_missing(run):
    old = (datetime.utcnow() - timedelta(days=2)).isoformat()
    run.sm.transition_to(run.id, "HUMAN_REQUIRED", "x")
    with usage._conn() as conn:
        conn.execute("UPDATE state_transitions SET timestamp=? WHERE run_id=?", (old, run.id))
    for _ in range(3):
        _call("CHAT", "ARCHITECT", None)
    rows = work_log.rows(3)                                               # the calls fill the quota: nothing older is shown
    assert len(rows) == 3 and all(r["kind"] == "ai" for r in rows)
    assert [r["at"] for r in rows] == sorted((r["at"] for r in rows), reverse=True)


def test_the_overview_has_one_record_and_one_panel():
    assert 'id="log-list"' in HTML and 'id="log-filter"' in HTML and "event-feed" not in HTML and "call-feed" not in HTML
    assert 'id="cp-facts"' in HTML and 'id="cp-src"' in HTML and 'id="cp-body" tabindex="0"' in HTML
    assert "getJSON('/ops/record?key='+encodeURIComponent(key))" in JS and "b.onclick=()=>openRecord(r.key);" in JS
    assert "if(list.dataset.sig===sig)return;list.dataset.sig=sig;" in JS      # the list keeps its scroll position between polls
    assert "dd.append(el('span',T('기록 없음'),'none'))" in JS                  # a missing value says so
    panel = JS[JS.index("function facts(title,rows,extra){"):JS.index("function openRecord(key){")]
    assert "innerHTML" not in panel                                          # the model's words and file names go in as text
    import dashboard_server as d
    src = Path(d.__file__).read_text(encoding="utf-8")
    block = src[src.index("elif parsed.path == '/ops/record':"):]
    assert "is_request_origin_allowed" in block[:400]                        # same care as /ops/call
