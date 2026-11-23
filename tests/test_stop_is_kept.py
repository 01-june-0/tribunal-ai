"""
A stop is final until the person continues the task. Found in a real run: "멈춰" in the chat killed the MAKER's CLI and
marked the task STOPPED - and the run went on anyway (the maker stage retried, then the tests, the INSPECTOR and the
final decision were called), the task was announced as done, and with auto-apply it would have been written into the
project. Three things let that happen: nothing refused the next CLI launch, the loop planned and finished after the
step, and "DONE" was saved over "STOPPED".
"""
import pytest

from core import usage
from core.mission import MissionRunner, MissionStore, stop_gate, stop_request
from core.process_runner import ProcessTreeRunner, StopRequested
from core.state_machine import State


@pytest.fixture
def clean():
    before = ProcessTreeRunner.stop_gate
    ProcessTreeRunner.stop_gate = None
    usage.set_context(mission_id=None)
    yield
    ProcessTreeRunner.stop_gate = before
    usage.set_context(mission_id=None)


def _mission(store, mid="MSN-STOP", status="RUNNING", **more):
    m = {"mission_id": mid, "status": status, "goal": "g", "project_path": "/nowhere", "max_steps": 2,
         "max_consecutive_failures": 3, "steps": [{"index": 1, "order": {"goal": "g"}, "run_id": "RUN-S", "result": None}],
         "base_worktree": None, **more}
    store.save(m, force=True)
    return m


def test_a_stopped_task_is_never_saved_as_anything_else(tmp_path):
    store = MissionStore(tmp_path)
    held = _mission(store)                               # the copy the running loop holds
    stop_request("MSN-STOP", "멈춰", store=store)
    for status in ("RUNNING", "DONE", "BLOCKED", "INCOMPLETE", "FAILED"):
        held["status"] = status
        store.save(held)
        assert store.load("MSN-STOP")["status"] == "STOPPED" and held["status"] == "STOPPED"
    held["status"] = "RUNNING"
    store.save(held, force=True)                         # only "continue" (reopen) clears it
    assert store.load("MSN-STOP")["status"] == "RUNNING"


def test_nothing_is_planned_finished_announced_or_applied_after_a_stop(tmp_path):
    store, said, calls = MissionStore(tmp_path), [], []

    class Orch:
        config = {}
        class sm:
            @staticmethod
            def get_run(rid): return {"current_state": State.BUILDING}
    runner = MissionRunner(lambda: Orch(), store, notify=lambda text, **k: said.append(text))
    runner._execute = lambda orch, mission, step: stop_request(mission["mission_id"], "멈춰", store=store)    # stopped mid-step
    runner._plan = lambda *a: calls.append("plan") or {"status": "DONE"}
    runner._auto_apply = lambda m: calls.append("apply")
    m = _mission(store)
    out = runner._advance(m)
    assert out["status"] == "STOPPED" and calls == [] and said == []
    assert out["steps"][0]["result"] is None             # cut short: "continue" takes the step up again
    assert runner._finish(m, "DONE", summary="all good")["status"] == "STOPPED" and calls == [] and said == []
    assert store.load("MSN-STOP")["status"] == "STOPPED"
    assert runner._advance(m)["status"] == "STOPPED" and calls == []       # and no further step starts


def test_a_step_that_had_already_ended_keeps_its_result(tmp_path):
    store = MissionStore(tmp_path)

    class Orch:
        config = {}
        class sm:
            @staticmethod
            def get_run(rid): return {"current_state": State.PASS}
    runner = MissionRunner(lambda: Orch(), store)
    runner._execute = lambda orch, mission, step: stop_request(mission["mission_id"], store=store)
    runner._evidence = lambda orch, rid: {"final_state": State.PASS}
    runner._plan = lambda *a: pytest.fail("planned after a stop")
    out = runner._advance(_mission(store))
    assert out["status"] == "STOPPED" and out["steps"][0]["result"] == {"final_state": State.PASS}


def test_the_gate_closes_only_for_the_stopped_tasks_own_loop(tmp_path, clean):
    store = MissionStore(tmp_path)
    _mission(store); _mission(store, mid="MSN-OTHER")
    usage.set_context(mission_id="MSN-STOP")
    assert stop_gate("/anywhere", store) is False        # running: nothing is refused
    stop_request("MSN-STOP", store=store)
    assert stop_gate("/anywhere", store) is True and stop_gate(None, store) is True
    usage.set_context(mission_id="MSN-OTHER")
    assert stop_gate("/anywhere", store) is False        # another task's loop
    usage.set_context(mission_id=None)
    assert stop_gate("/anywhere", store) is False        # a chat, a plain run


def test_a_refused_launch_starts_nothing_and_is_not_an_ordinary_error(clean):
    assert not issubclass(StopRequested, Exception)      # `except Exception` around a call must not turn a stop into a retry
    ProcessTreeRunner.stop_gate = staticmethod(lambda cwd: True)
    with pytest.raises(StopRequested):
        ProcessTreeRunner.run(["this-command-does-not-exist-anywhere"], cwd=".")
    ProcessTreeRunner.stop_gate = staticmethod(lambda cwd: 1 / 0)          # a broken gate never blocks work
    try:
        ProcessTreeRunner.run(["this-command-does-not-exist-anywhere"], cwd=".", timeout=5)
    except StopRequested:
        pytest.fail("a broken gate refused a launch")
    except Exception:
        pass                                             # the command itself does not exist: that is the ordinary failure


def test_the_loop_ends_quietly_when_a_call_is_refused(tmp_path, clean):
    store = MissionStore(tmp_path)
    runner = MissionRunner(lambda: None, store)

    def advance(mission):
        stop_request(mission["mission_id"], store=store)
        raise StopRequested("refused")
    runner._advance = advance
    _mission(store)
    out = runner.run("MSN-STOP")
    assert out["status"] == "STOPPED" and out["owner_pid"] is None
    assert ProcessTreeRunner.stop_gate is None and usage.context().get("mission_id") is None     # nothing left behind for whatever runs next


def test_a_run_parked_by_a_stop_does_not_keep_its_project_busy(tmp_path, monkeypatch):
    """The run cut short stays in BUILDING with a fresh timestamp; counted as active, it refused every new task and
    approval in that project for the next fifteen minutes."""
    import dashboard_server as d
    from datetime import datetime
    store = MissionStore(tmp_path)
    _mission(store, project_path=str(tmp_path / "proj"))
    rows = [{"run_id": "RUN-S", "current_state": State.BUILDING, "project_path": str(tmp_path / "proj"), "updated_at": datetime.utcnow().isoformat()}]
    sm = type("SM", (), {"list_runs": lambda self: rows})()
    monkeypatch.setattr(d, "MissionStore", lambda: store)
    assert d._project_busy(sm, str(tmp_path / "proj")) is True          # at work
    stop_request("MSN-STOP", store=store)
    assert d._project_busy(sm, str(tmp_path / "proj")) is False         # parked


def test_a_stop_that_arrives_while_a_command_is_starting_still_ends_it(tmp_path, clean):
    import sys, time
    answers = iter([False, True])                        # not stopped when asked first; stopped by the time it is registered
    ProcessTreeRunner.stop_gate = staticmethod(lambda cwd: next(answers, True))
    began = time.monotonic()
    with pytest.raises(StopRequested):
        ProcessTreeRunner.run([sys.executable, "-c", "import time; time.sleep(30)"], cwd=str(tmp_path), timeout=60)
    assert time.monotonic() - began < 10                 # killed at once, not left to run
    from core.process_runner import active_processes
    assert not active_processes()
