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


def test_a_stop_by_the_scope_guard_is_not_shown_as_a_test_run(run):
    """Stopped after the build before any test, approved, then tested: one real test run, and the stop says so."""
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
    assert [(r["round"], r["known"], r["skipped"]) for r in rounds] == [(0, False, True), (1, True, False)]   # the guard stopped it: no test ran, and it is not counted as a round
    assert work_log.detail(rounds[0]["key"])["skipped"] is True and work_log.detail(rounds[1]["key"])["rounds"] == 1
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


def test_a_test_run_in_progress_shows_what_it_has_printed_so_far(run):
    for state in ("PLANNING", "ORDER_READY", "BUILDING", "VERIFYING"):
        run.sm.transition_to(run.id, state, "x")
    row = next(r for r in work_log.rows() if r.get("event") == "verify" and r["run_id"] == run.id)
    assert work_log.detail(row["key"]).get("live") is None and work_log.detail(row["key"])["running"] is True   # nothing printed yet
    (run.dir / work_log.LIVE_LOG).write_text("--- test ---\ncollected 3 items\ntests/test_a.py ..", encoding="utf-8")
    live = work_log.detail(row["key"])["live"]
    assert live["tail"].endswith("tests/test_a.py ..") and live["lines"] == 2 and live["bytes"] > 0
    # a long output: only its end travels
    (run.dir / work_log.LIVE_LOG).write_text("x" * 50_000 + "\nTHE END", encoding="utf-8")
    live = work_log.detail(row["key"])["live"]
    assert len(live["tail"]) == work_log.LIVE_CHARS and live["tail"].endswith("THE END") and live["lines"] is None
    # a file left over from an earlier round is not this run's output
    old = time.time() - 3600
    os.utime(run.dir / work_log.LIVE_LOG, (old, old))
    assert work_log.detail(row["key"])["live"] is None
    # once the run has moved on, the record is the result file, not the live output
    os.utime(run.dir / work_log.LIVE_LOG, None)
    run.sm.transition_to(run.id, "REVIEWING", "x")
    after = work_log.detail(row["key"])
    assert "live" not in after and "running" not in after


def test_the_engine_writes_the_test_output_line_by_line(tmp_path, monkeypatch):
    import sys
    from core.orchestrator import Orchestrator
    from core.verifier import Verifier
    seen = []
    script = tmp_path / "t.py"
    script.write_text("import sys\nprint('one')\nprint('two', file=sys.stderr)\nprint('three')\n", encoding="utf-8")
    out = Verifier.verify(worktree_path=str(tmp_path), test_cmd=[sys.executable, str(script)], git_checks=False,
                          on_line=lambda phase, text: seen.append((phase, text)))
    assert out["passed"] and {p for p, _ in seen} == {"test"}
    assert sorted("".join(t for _, t in seen).split()) == ["one", "three", "two"]                        # stdout and stderr both
    # a line still being written is seen before its newline: the child waits for the observer's signal to go on
    go = tmp_path / "go"
    slow = tmp_path / "slow.py"
    slow.write_text("import os, sys, time\nsys.stdout.write('a.py .'); sys.stdout.flush()\n"
                    "t = time.time()\nwhile not os.path.exists(sys.argv[1]) and time.time() - t < 10: time.sleep(.02)\n"
                    "sys.stdout.write('.\\r\\nend\\n' if os.path.exists(sys.argv[1]) else 'NOT SEEN\\n'); sys.stdout.flush()\n", encoding="utf-8")
    pieces = []

    def see(phase, text):
        pieces.append(text)
        if "".join(pieces) == "a.py .":
            go.write_text("", encoding="utf-8")
    watched = Verifier.verify(worktree_path=str(tmp_path), test_cmd=[sys.executable, str(slow), str(go)], git_checks=False, on_line=see)
    assert "".join(pieces) == "a.py ..\nend\n"                                    # the dot was seen before its line ended
    plain = Verifier.verify(worktree_path=str(tmp_path), test_cmd=[sys.executable, str(slow), str(go)], git_checks=False)
    assert watched["test"]["output"] == plain["test"]["output"] == "a.py ..\nend"  # same text, same newline handling
    # what is collected for the result is line by line, exactly as unwatched: an unfinished line only when the stream ends
    src_runner = Path(sys.modules["core.process_runner"].__file__).read_text(encoding="utf-8")
    assert 'chunk_list.append(pending + text[:cut])' in src_runner and "if pending:\n                            chunk_list.append(pending)" in src_runner
    orch = Orchestrator.__new__(Orchestrator)
    monkeypatch.setattr(orch, "_get_run_dir", lambda run_id: tmp_path, raising=False)
    write = orch._live_log("RUN-X")
    assert (tmp_path / Orchestrator.LIVE_LOG).read_text(encoding="utf-8") == ""                          # every test run starts empty
    write("test", "a\n"); write("test", "b ."); write("test", ".\n"); write("test", "tail"); write("lint", "c\n"); write.close()
    assert (tmp_path / Orchestrator.LIVE_LOG).read_text(encoding="utf-8") == "--- test ---\na\nb ..\ntail\n--- lint ---\nc\n"   # pieces join as written
    monkeypatch.setattr(Orchestrator, "LIVE_LOG_MAX", 40)
    write = orch._live_log("RUN-X")
    began = time.time()
    for _ in range(20000):
        write("test", "0123456789\n")                                    # the reader side only queues: it never waits for the disk
    assert time.time() - began < 1.0
    write.close()
    text = (tmp_path / Orchestrator.LIVE_LOG).read_text(encoding="utf-8")
    assert text.endswith("--- output too long: the rest is not shown live ---\n") and len(text) < 200   # a runaway run cannot fill the disk
    watched = Path(sys.modules["core.verifier"].__file__).read_text(encoding="utf-8")
    assert 'env["PYTHONUNBUFFERED"] = "1"' in watched and "if on_line is not None:\n                env" not in watched   # the same environment watched or not
    src = Path(sys.modules["core.orchestrator"].__file__).read_text(encoding="utf-8")
    assert "self._verify(run_id, worktree_path, live=True)" in src and "baseline = self._verify(run_id, worktree_path)" in src   # the baseline run is not shown as the round


def test_the_core_follows_a_running_test():
    core = JS[JS.index("function paintCore(){"):JS.index("function tickInside(){")]
    assert "going&&going.tail?going.tail" in core and "if(stick)out.scrollTop=out.scrollHeight;" in core
    assert "going=live&&d&&d.live&&!done?d.live:null;" in core              # only while the scene says a test run is going
    assert "if(live&&d&&d.found&&!d.running&&Date.now()-utc(d.ended_at||d.at)>8000)d=null;" in core   # the previous run's result is never shown as this run's
    assert "const {group,live:_l,...rest}=d" in core                        # the panes are not rebuilt for every new line
    assert "if(inside===CORE&&lastModel&&lastModel.phase==='VERIFYING')pollInside();},700)" in JS
    # a comment once swallowed the rest of this line: every poller must be real code
    at = JS.index("  pollActivity();pollStatus();pollChat();pollRoles();every(pollRoles,8000);")
    boot = JS[at:at + 1500]
    code = "\n".join(line.split("//")[0] for line in boot.splitlines())
    for poller in ("every(pollActivity,", "every(pollStatus,", "every(pollChat,", "every(pollCall,", "every(pollInside,", "pollAI();every(pollAI,20000)"):
        assert poller in code, poller


def test_the_record_says_which_untracked_files_reached_the_worktree(run):
    for state in ("PLANNING", "ORDER_READY", "BUILDING"):
        run.sm.transition_to(run.id, state, "x")
    rid = _call("BUILDING", "MAKER", run.id)
    assert work_log.detail(f"call-{rid}")["snapshot"] is None                # an older run: nothing was recorded, nothing is claimed
    (run.dir / "source_snapshot.json").write_text(json.dumps({
        "base_ref": "abc", "base_worktree": None, "untracked_included": ["data/fixture.json", "src/new.py"], "untracked_included_count": 2,
        "untracked_skipped": {"secret_name": ["secrets/key.json"]}, "untracked_skipped_count": {"secret_name": 1, "too_large": 0},
        "exclude_patterns": ["*.csv"]}), encoding="utf-8")
    snap = work_log.detail(f"call-{rid}")["snapshot"]
    assert snap == {"included": ["data/fixture.json", "src/new.py"], "included_count": 2, "skipped": {"secret_name": 1},
                    "from_previous_step": False, "patterns": 1}
    assert "secrets/key.json" not in json.dumps(snap)                        # names of what stayed out are not sent to the page
    run.sm.transition_to(run.id, "VERIFYING", "x"); run.sm.transition_to(run.id, "REVIEWING", "x")
    run.sm.transition_to(run.id, "DECIDING", "x"); run.sm.transition_to(run.id, "PASS", "Final decision: ok")
    end = next(r for r in work_log.rows() if r.get("event") == "end" and r["run_id"] == run.id)
    assert work_log.detail(end["key"])["snapshot"]["included_count"] == 2
    assert "function snapshotFacts(sn){" in JS and "if(d.snapshot)out.push(snapshotFacts(d.snapshot));" in JS


def test_a_windows_line_end_split_across_two_pieces_never_glues_lines_together(tmp_path):
    """Found on Windows: a piece ended in the \\r of \\r\\n, the decoder held it back, the other stream's line came first
    and the observer saw "twothree". The collected result was always right; now the live view is too."""
    import sys
    from core.verifier import Verifier
    seen = []
    script = tmp_path / "t.py"
    script.write_text(
        "import sys, time\n"
        "sys.stderr.buffer.write(b'two\\r'); sys.stderr.flush(); time.sleep(0.4)\n"
        "sys.stdout.buffer.write(b'three\\n'); sys.stdout.flush(); time.sleep(0.4)\n"
        "sys.stderr.buffer.write(b'\\n'); sys.stderr.flush()\n", encoding="utf-8")
    out = Verifier.verify(worktree_path=str(tmp_path), test_cmd=[sys.executable, str(script)], git_checks=False,
                          on_line=lambda phase, text: seen.append(text))
    shown = "".join(seen)
    assert out["passed"] and "twothree" not in shown and sorted(shown.split()) == ["three", "two"]
    assert shown.count("\n") == 2                                       # the held line end is shown once, not twice
