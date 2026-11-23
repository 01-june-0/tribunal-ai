"""
v3.2 DELIVERY: a mission's finished worktree is applied to the project file by file (new / changed-by-the-AIs /
conflict-with-the-user), chains of milestones resolve to the project snapshot they started from, and the finished
mission applies itself under the auto_apply policy. Plus the goal-level bridge and execution profiles.
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from core import autopilot
from core.bootstrap import snapshot
from core.git_manager import GitManager
from core.result_manager import ResultManager
from core.state_machine import StateMachine, State
from tests.test_v301_companion_http import http_server, request  # noqa: F401

RUNS = Path(__file__).resolve().parents[1] / "runs"


def git(cwd, *a):
    subprocess.run(["git", *a], cwd=cwd, check=True, capture_output=True)


def project(tmp_path):
    p = tmp_path / "proj"
    p.mkdir()
    git(p, "init", "-q"); git(p, "config", "user.email", "t@t"); git(p, "config", "user.name", "t")
    (p / "a.py").write_text("a = 1\n", encoding="utf-8")
    (p / "b.py").write_text("b = 1\n", encoding="utf-8")
    git(p, "add", "-A"); git(p, "commit", "-qm", "base")
    (p / "u.txt").write_text("untracked original\n", encoding="utf-8")        # never committed by the user
    return p


def fake_run(proj, run_id, base_ref, base_worktree=None, evidence_ok=True, state=State.PASS):
    sm = StateMachine()
    sm.create_run(run_id, str(proj), "goal")
    wt, branch = GitManager.create_worktree(str(proj), run_id, base_ref=base_ref)
    sm.update_run_worktree(run_id, wt, branch)
    for nxt in (State.PLANNING, State.ORDER_READY, State.BUILDING, State.VERIFYING, State.REVIEWING, State.DECIDING, state):
        sm.transition_to(run_id, nxt, details="t")
    d = RUNS / run_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "source_snapshot.json").write_text(json.dumps({"base_ref": base_ref, "source_head_unchanged": True, "base_worktree": base_worktree}), encoding="utf-8")
    if evidence_ok:
        (d / "final_evidence.json").write_text(json.dumps({"reasons": [], "canonical_containment": "PASS", "verification": "PASS",
                                                           "baseline": "PASS", "regression": "PASS", "inspector_verdict": "pass"}), encoding="utf-8")
        (d / "verification.json").write_text(json.dumps({"test_counts": {"passed": 0}}), encoding="utf-8")
    return Path(wt)


@pytest.fixture
def cleanup_runs():
    made = []
    yield made
    for rid in made:
        shutil.rmtree(RUNS / rid, ignore_errors=True)


def test_tree_manifest_classifies_new_changed_unchanged_and_conflicting_files(tmp_path, cleanup_runs):
    proj = project(tmp_path)
    base = snapshot(str(proj))                                   # includes the untracked u.txt
    rid = "RUN-TEST-DLV1"; cleanup_runs.append(rid)
    wt = fake_run(proj, rid, base)
    (wt / "a.py").write_text("a = 2\n", encoding="utf-8")        # AI changed
    (wt / "u.txt").write_text("untracked edited by AI\n", encoding="utf-8")
    (wt / "new.py").write_text("new = 1\n", encoding="utf-8")   # AI added
    (wt / "b.py").write_text("b = 2\n", encoding="utf-8")        # AI changed ...
    (proj / "b.py").write_text("b = 99\n", encoding="utf-8")     # ... and so did the user: conflict
    (proj / "mine.md").write_text("user file\n", encoding="utf-8")   # user-only file: irrelevant
    tree = ResultManager().tree_manifest(rid)
    kinds = {m["path"]: m["type"] for m in tree["manifest"]}
    assert kinds == {"a.py": "M", "u.txt": "M", "new.py": "A"}
    assert [c["path"] for c in tree["conflicts"]] == ["b.py"]
    assert tree["origin_ref"] == base and tree["deleted"] == []


def test_apply_tree_delivers_into_the_project_and_blocks_on_conflicts(tmp_path, cleanup_runs):
    proj = project(tmp_path)
    base = snapshot(str(proj))
    rid = "RUN-TEST-DLV2"; cleanup_runs.append(rid)
    wt = fake_run(proj, rid, base)
    (wt / "a.py").write_text("a = 2\n", encoding="utf-8")
    (wt / "new.py").write_text("new = 1\n", encoding="utf-8")
    (wt / "b.py").write_text("b = 2\n", encoding="utf-8")
    (proj / "b.py").write_text("b = 99\n", encoding="utf-8")
    rm = ResultManager(config={"verification": {"test_command": None}})
    blocked = rm.apply_tree(rid, request_id="dlv2-a")
    assert blocked["status"] == "blocked" and any("Conflicts" in b for b in blocked["blocks"])
    assert (proj / "a.py").read_text(encoding="utf-8") == "a = 1\n"            # nothing written when blocked
    done = rm.apply_tree(rid, request_id="dlv2-b", on_conflict="skip")
    assert done["status"] == "applied" and sorted(done["files"]) == ["a.py", "new.py"]
    assert (proj / "a.py").read_text(encoding="utf-8") == "a = 2\n" and (proj / "new.py").exists()
    assert (proj / "b.py").read_text(encoding="utf-8") == "b = 99\n"           # the user's edit survives
    assert [c["path"] for c in done["skipped_conflicts"]] == ["b.py"]
    assert rm.apply_tree(rid, request_id="dlv2-c")["status"] == "blocked"      # already applied


def test_milestone_chain_resolves_to_the_project_snapshot_it_started_from(tmp_path, cleanup_runs):
    proj = project(tmp_path)
    base = snapshot(str(proj))
    r1, r2 = "RUN-TEST-DLV3A", "RUN-TEST-DLV3B"; cleanup_runs += [r1, r2]
    wt1 = fake_run(proj, r1, base)
    (wt1 / "a.py").write_text("a = 2\n", encoding="utf-8")                    # milestone 1's change
    base2 = snapshot(str(wt1))                                                # milestone 2 builds on milestone 1
    wt2 = fake_run(proj, r2, base2, base_worktree=str(wt1))
    (wt2 / "new.py").write_text("new = 1\n", encoding="utf-8")                # milestone 2's change
    rm = ResultManager()
    assert rm.origin_ref(r2) == base
    kinds = {m["path"]: m["type"] for m in rm.tree_manifest(r2)["manifest"]}
    assert kinds == {"a.py": "M", "new.py": "A"}                                # both milestones are delivered


def test_the_change_screen_of_a_task_of_several_steps_shows_everything_applying_would_write(tmp_path, cleanup_runs):
    """Found in a real run: the last step's own change set held 2 files while applying wrote 4 (the earlier step's
    too), so the person approved less than they got. The screen is given the whole apply set instead."""
    proj = project(tmp_path)
    base = snapshot(str(proj))
    r1, r2 = "RUN-TEST-DLV7A", "RUN-TEST-DLV7B"; cleanup_runs += [r1, r2]
    wt1 = fake_run(proj, r1, base)
    (wt1 / "a.py").write_text("a = 2\n", encoding="utf-8")                    # step 1
    (wt1 / "b.py").write_text("b = 2\n", encoding="utf-8")                    # step 1 ... and the user too, below
    wt2 = fake_run(proj, r2, snapshot(str(wt1)), base_worktree=str(wt1))
    (wt2 / "new.py").write_text("new = 1\n", encoding="utf-8")                # step 2
    (proj / "b.py").write_text("b = 99\n", encoding="utf-8")
    rm = ResultManager()
    from core import result_manager
    result_manager._APPLY_VIEW_CACHE.clear()
    view = rm.apply_view(r2)
    assert {f["path"]: f["type"] for f in view["changed_files"]} == {"a.py": "M", "new.py": "A"}
    assert view["changed_count"] == 2 and view["counts"] == {"A": 1, "M": 1, "D": 0} and view["steps"] == 2
    assert "-a = 1" in view["file_diffs"]["a.py"] and "+a = 2" in view["file_diffs"]["a.py"]   # against the project, not step 1
    assert "new = 1" in view["file_diffs"]["new.py"]
    assert view["conflicts"] == ["b.py"] and view["deleted_not_applied"] == []
    assert rm.apply_view(r1)["steps"] == 1


def test_the_change_screen_shows_a_file_the_project_lacks_whole_and_reads_odd_names_literally(tmp_path, cleanup_runs):
    from core import result_manager
    proj = project(tmp_path)
    (proj / "c[1].py").write_text("c = 1\n", encoding="utf-8"); (proj / "c1.py").write_text("other = 1\n", encoding="utf-8")
    base = snapshot(str(proj))
    rid = "RUN-TEST-DLV9"; cleanup_runs.append(rid)
    wt = fake_run(proj, rid, base)
    (wt / "a.py").write_text("a = 1\nmore = 2\n", encoding="utf-8")
    (wt / "c[1].py").write_text("c = 2\n", encoding="utf-8"); (wt / "c1.py").write_text("other = 2\n", encoding="utf-8")
    (proj / "a.py").unlink()                                                  # the person deleted it since the snapshot
    result_manager._APPLY_VIEW_CACHE.clear()
    view = ResultManager().apply_view(rid)
    assert {f["path"]: f["type"] for f in view["changed_files"]}["a.py"] == "A"
    assert view["file_diffs"]["a.py"] == "(new file)\na = 1\nmore = 2\n"      # all of what gets written, not one hunk
    assert "other" not in view["file_diffs"]["c[1].py"] and "+c = 2" in view["file_diffs"]["c[1].py"]
    (wt / "late.py").write_text("x = 1\n", encoding="utf-8")
    assert ResultManager().apply_view(rid) is view                            # asked again within seconds: not recomputed


def test_the_change_screen_keeps_the_runs_own_changes_when_there_is_nothing_to_resolve(tmp_path, cleanup_runs):
    proj = project(tmp_path)
    rid = "RUN-TEST-DLV8"; cleanup_runs.append(rid)
    wt = fake_run(proj, rid, snapshot(str(proj)))
    rm = ResultManager()
    (RUNS / rid / "source_snapshot.json").unlink()                           # a run from before snapshots
    assert rm.apply_view(rid) is None
    assert rm.apply_view("RUN-TEST-NOPE") is None
    shutil.rmtree(wt, ignore_errors=True)


def test_result_endpoint_swaps_in_the_whole_apply_set_only_for_a_result_still_waiting():
    src = (Path(__file__).resolve().parents[1] / "dashboard_server.py").read_text(encoding="utf-8")
    at = src.index("whole = _result_manager().apply_view(run_id)")
    block = src[at - 300:at + 900]
    assert 'not in ("APPLIED", "DISCARDED")' in block and 'payload.get("is_pass")' in block
    assert 'payload["run_changed_files"] = payload.get("changed_files")' in block      # the run's own set is kept
    stage = (Path(__file__).resolve().parents[1] / "console" / "stage.js").read_text(encoding="utf-8")
    assert "av.steps" in stage and "앞 단계의 결과물도 함께 적용됩니다" in stage
    assert "av.conflicts" in stage and "av.deleted_not_applied" in stage       # what the list leaves out is said


def test_apply_tree_requires_full_pass_evidence(tmp_path, cleanup_runs):
    proj = project(tmp_path)
    rid = "RUN-TEST-DLV4"; cleanup_runs.append(rid)
    wt = fake_run(proj, rid, snapshot(str(proj)), evidence_ok=False)
    (wt / "a.py").write_text("a = 2\n", encoding="utf-8")
    res = ResultManager().apply_tree(rid, request_id="dlv4")
    assert res["status"] == "blocked" and any("final_evidence" in b for b in res["blocks"])


def test_profiles_and_tags():
    assert autopilot.split_profile_tag("[빠르게] 캡션 검사기") == ("quick", "캡션 검사기")
    assert autopilot.split_profile_tag("  [deep] big goal") == ("deep", "big goal")
    assert autopilot.split_profile_tag("plain goal") == (None, "plain goal")
    assert autopilot.profile_overrides({}, "quick")["max_steps"] == 2
    assert autopilot.profile_overrides({"autonomy": {"profiles": {"quick": {"max_steps": 3}}}}, "quick")["max_steps"] == 3
    assert autopilot.profile_overrides({}, None) == {} and autopilot.profile_overrides({}, "nope") == {}


def test_mission_records_profile_source_and_auto_apply_policy(tmp_path):
    from core.mission import MissionRunner, MissionStore, deliverable_run_id
    from schemas.order import OrderSchema
    runner = MissionRunner(lambda: None, MissionStore(tmp_path / "missions"))
    m = runner.create(str(tmp_path / "p"), "g", OrderSchema(goal="g", allowed_paths=["src/**"]), config={"autonomy": {"auto_apply": "on_done"}},
                      profile="quick", source="bridge", request_id="req-12345678")
    assert m["max_steps"] == 2 and m["profile"] == "quick" and m["source"] == "bridge" and m["auto_apply"] == "on_done"
    assert deliverable_run_id(m) is None
    m["base_worktree"] = "X/.director_worktrees/RUN-Z"
    m["steps"][0].update(run_id="RUN-Z", result={"final_state": "PASS", "worktree_path": "X/.director_worktrees/RUN-Z"})
    assert deliverable_run_id(m) == "RUN-Z"


# ------------------------------------------------------------------ bridge v2 (goal-level missions)

def test_bridge_missions_need_the_token_and_respect_the_allowlist(http_server, monkeypatch):
    import companion_server
    monkeypatch.setattr(companion_server.d, "load_config", lambda: {"bridge": {"allowed_roots": ["E:/work"], "denied": ["E:/work/CONSOLE"]}, "projects": {}})
    assert request(http_server, "GET", "/bridge/projects")[0] == 403
    body = json.dumps({"request_id": "bridge-req-0001", "project_path": "C:/elsewhere/proj", "goal": "make a thing"})
    code, data = request(http_server, "POST", "/bridge/missions", body=body, headers={"X-Tribunal-Token": "test-token", "Content-Type": "application/json"})
    assert code == 400 and "허용된 폴더 밖" in json.loads(data)["error"]
    body = json.dumps({"request_id": "bridge-req-0002", "project_path": "E:/work/CONSOLE", "goal": "modify yourself"})
    code, data = request(http_server, "POST", "/bridge/missions", body=body, headers={"X-Tribunal-Token": "test-token", "Content-Type": "application/json"})
    assert code == 400 and "지시할 수 없" in json.loads(data)["error"]


def test_bridge_mission_start_decide_and_duplicate_request(http_server, monkeypatch, tmp_path):
    import companion_server
    from core.mission import MissionStore
    monkeypatch.setattr(companion_server.d, "load_config", lambda: {"solomon": {"allowed_roots": [str(tmp_path)], "denied": []}, "projects": {}})
    target = tmp_path / "game"; target.mkdir()
    calls = []
    monkeypatch.setattr(companion_server.d, "start_goal_mission", lambda path, goal, **kw: calls.append((path, goal, kw)) or {"status": "started", "mission_id": "MSN-X"})
    hdr = {"X-Tribunal-Token": "test-token", "Content-Type": "application/json"}
    body = json.dumps({"request_id": "bridge-req-1234", "project_path": str(target), "goal": "[빠르게] 데일리 미션 추가", "profile": "quick"})
    code, data = request(http_server, "POST", "/bridge/missions", body=body, headers=hdr)
    assert code == 202 and json.loads(data)["mission_id"] == "MSN-X"
    assert calls[0][2]["source"] == "bridge" and calls[0][2]["request_id"] == "bridge-req-1234" and calls[0][2]["profile"] == "quick"
    # a retry with the same request_id finds the mission instead of starting another
    store = MissionStore()
    m = {"mission_id": "MSN-X", "project_path": str(target), "goal": "g", "status": "RUNNING", "steps": [], "request_id": "bridge-req-1234",
         "updated_at": "2026-10-24T00:00:00", "created_at": "2026-10-24T00:00:00", "max_steps": 2}
    store.save(m)
    code, data = request(http_server, "POST", "/bridge/missions", body=body, headers=hdr)
    assert code == 200 and json.loads(data)["status"] == "duplicate" and len(calls) == 1
    code, data = request(http_server, "GET", "/bridge/missions/MSN-X", headers=hdr)
    assert code == 200 and json.loads(data)["source"] in ("chat", "bridge") and json.loads(data)["mission_id"] == "MSN-X"
    decided = []
    monkeypatch.setattr(companion_server.d, "decide_mission", lambda mid, action, **kw: decided.append((mid, action, kw)) or {"status": "applied", "files": ["a.py"]})
    code, data = request(http_server, "POST", "/bridge/missions/MSN-X/decide", body=json.dumps({"action": "apply", "on_conflict": "skip"}), headers=hdr)
    assert code == 200 and decided[0][0] == "MSN-X" and decided[0][2]["by"] == "BRIDGE" and decided[0][2]["on_conflict"] == "skip"
    code, data = request(http_server, "GET", "/bridge/digest", headers=hdr)
    assert code == 200 and "awaiting_decision" in json.loads(data)


def test_a_decision_is_refused_for_a_running_mission_or_another_result(monkeypatch):
    """The stage's change panel names the run it showed: nothing unseen is applied or discarded, twice is once."""
    import dashboard_server as d
    mission = {"mission_id": "MSN-D", "status": "DONE", "project_path": "/nowhere", "steps": [], "base_worktree": "/nowhere/wt"}
    saved, applied = [], []

    class Store:
        def load(self, mid): return dict(mission) if mid == "MSN-D" else None
        def save(self, m): saved.append(m); mission.update(m)

    class Results:
        def apply_tree(self, rid, **kw): applied.append(rid); return {"status": "applied", "files": ["a.py"], "request_id": "x"}
        def discard(self, rid, **kw): applied.append("discard " + rid); return {"status": "discarded"}
    monkeypatch.setattr(d, "MissionStore", Store)
    monkeypatch.setattr(d, "_result_manager", lambda: Results())
    monkeypatch.setattr(d, "active_session_id", lambda: "S")
    monkeypatch.setattr(d, "ChatManager", lambda: type("C", (), {"add_message": lambda *a, **k: None})())
    monkeypatch.setattr(d, "invalidate_status_cache", lambda: None)
    import core.mission
    monkeypatch.setattr(core.mission, "deliverable_run_id", lambda m: "RUN-2")

    assert d.decide_mission("MSN-D", "apply", expected_run="RUN-1")["status"] == "stale" and applied == []
    assert d.decide_mission("MSN-D", "discard", expected_run="RUN-1")["status"] == "stale" and applied == []
    mission["status"] = "RUNNING"
    assert d.decide_mission("MSN-D", "apply", expected_run="RUN-2")["status"] == "busy"
    assert d.decide_mission("MSN-D", "discard")["status"] == "busy" and applied == []
    mission["status"] = "DONE"
    first = d.decide_mission("MSN-D", "apply", expected_run="RUN-2")
    assert first["status"] == "applied" and applied == ["RUN-2"] and mission["applied"]["status"] == "applied"
    again = d.decide_mission("MSN-D", "apply", expected_run="RUN-2")
    assert again["status"] == "applied" and again["already"] is True and applied == ["RUN-2"]      # not applied twice, record untouched
    assert mission["applied"]["status"] == "applied"


# ------------------------------------------------------------------ working copies do not pile up

def _branches(proj):
    out = subprocess.run(["git", "branch", "--format=%(refname:short)"], cwd=proj, capture_output=True, text=True).stdout.split()
    return sorted(b for b in out if b.startswith("RUN-"))


def _in_task(run_id, task):
    (RUNS / run_id / "mission_base.json").write_text(json.dumps({"mission_id": task}), encoding="utf-8")


def test_an_applied_result_takes_its_working_copies_and_branches_with_it(tmp_path, cleanup_runs):
    """Found in real runs: every applied task left a worktree and a branch per step behind."""
    from core import result_manager
    proj = project(tmp_path)
    r0, r1, r2 = "RUN-TEST-REL0", "RUN-TEST-REL1", "RUN-TEST-REL2"; cleanup_runs += [r0, r1, r2]
    wt0 = fake_run(proj, r0, snapshot(str(proj))); _in_task(r0, "MSN-OTHER")        # an earlier task it continued from
    (wt0 / "zero.py").write_text("z = 0\n", encoding="utf-8")
    wt1 = fake_run(proj, r1, snapshot(str(wt0)), base_worktree=str(wt0)); _in_task(r1, "MSN-T")
    (wt1 / "a.py").write_text("a = 2\n", encoding="utf-8")
    wt2 = fake_run(proj, r2, snapshot(str(wt1)), base_worktree=str(wt1)); _in_task(r2, "MSN-T")
    (wt2 / "new.py").write_text("new = 1\n", encoding="utf-8")
    result_manager._APPLY_VIEW_CACHE.clear()
    rm = ResultManager(config={"verification": {"test_command": None}})
    done = rm.apply_tree(r2, request_id="rel-a")
    assert done["status"] == "applied" and sorted(done["files"]) == ["a.py", "new.py", "zero.py"]
    assert done["released"] == [r2, r1]
    assert not wt2.exists() and not wt1.exists() and wt0.exists()               # another task's copy is its own business
    assert _branches(proj) == [r0]
    assert rm.result_state(r1)["state"] == "APPLIED" and r2 in rm.result_state(r1)["detail"]     # not left "ready" with no copy
    kept = json.loads((RUNS / r2 / "applied_view.json").read_text(encoding="utf-8"))            # what was written stays readable
    assert sorted(f["path"] for f in kept["changed_files"]) == ["a.py", "new.py", "zero.py"] and "+a = 2" in kept["file_diffs"]["a.py"]
    assert json.loads((RUNS / r1 / "applied_view.json").read_text(encoding="utf-8"))["applied_with"] == r2     # the earlier step shows the same
    assert (proj / "new.py").read_text(encoding="utf-8") == "new = 1\n"
    assert "WORKTREE_RELEASED" in [a["action"] for a in StateMachine().get_audit_logs(r2)]


def test_the_working_copy_stays_when_a_conflicting_file_was_skipped(tmp_path, cleanup_runs):
    proj = project(tmp_path)
    rid = "RUN-TEST-REL3"; cleanup_runs.append(rid)
    wt = fake_run(proj, rid, snapshot(str(proj))); _in_task(rid, "MSN-T")
    (wt / "a.py").write_text("a = 2\n", encoding="utf-8"); (wt / "b.py").write_text("b = 2\n", encoding="utf-8")
    (proj / "b.py").write_text("b = 99\n", encoding="utf-8")
    done = ResultManager(config={"verification": {"test_command": None}}).apply_tree(rid, request_id="rel-b", on_conflict="skip")
    assert done["status"] == "applied" and "released" not in done
    assert (wt / "b.py").read_text(encoding="utf-8") == "b = 2\n" and _branches(proj) == [rid]    # the AIs' b.py exists only here


def test_a_task_never_continues_from_a_working_copy_that_is_gone(tmp_path):
    """After an apply removed the copy, "continue" must start from the project - not from a path that is not there
    (snapshotting it would create an empty repository in its place)."""
    from core.mission import MissionRunner, MissionStore
    store = MissionStore(tmp_path / "missions")
    seen = {}

    class Orch:
        config = {}
        class sm:
            @staticmethod
            def get_run(rid): return None
    runner = MissionRunner(lambda: Orch(), store)
    runner._execute = lambda orch, mission, step: seen.update(base=mission.get("base_worktree")) or (_ for _ in ()).throw(RuntimeError("stop here"))
    gone, here = tmp_path / "gone", tmp_path / "here"; here.mkdir()
    for base, expect in ((gone, None), (here, str(here))):
        mission = {"mission_id": "MSN-B", "status": "RUNNING", "max_steps": 2, "steps": [{"index": 1, "run_id": None, "result": None}], "base_worktree": str(base)}
        with pytest.raises(RuntimeError):
            runner._advance(mission)
        assert seen["base"] == expect
    src = (Path(__file__).resolve().parents[1] / "core" / "orchestrator.py").read_text(encoding="utf-8")
    assert "if base_worktree and not Path(base_worktree).is_dir():" in src                     # the engine checks too
    closed = {"mission_id": "MSN-C", "status": "STOPPED", "closed": True, "steps": [], "project_path": str(tmp_path), "goal": "g"}
    store.save(closed)
    assert runner.reopen("MSN-C")["status"] == "STOPPED"                                       # a cleared task is not reopened


def test_release_touches_only_a_runs_own_directory_and_branch(tmp_path, cleanup_runs):
    proj = project(tmp_path)
    rid = "RUN-TEST-REL4"; cleanup_runs.append(rid)
    wt = fake_run(proj, rid, snapshot(str(proj)))
    sm, rm = StateMachine(), ResultManager()
    elsewhere = tmp_path / "elsewhere"; elsewhere.mkdir(); (elsewhere / "keep.txt").write_text("mine\n", encoding="utf-8")
    sm.update_run_worktree(rid, str(elsewhere), rid)
    assert rm.release_worktrees([rid, "RUN-TEST-NOPE", ""]) == [] and (elsewhere / "keep.txt").exists() and wt.exists()
    sm.update_run_worktree(rid, str(wt), "main")                       # a branch the run did not create is never deleted
    git(proj, "branch", "-M", "main")
    assert rm.release_worktrees([rid]) == [rid] and not wt.exists()
    assert "main" in subprocess.run(["git", "branch"], cwd=proj, capture_output=True, text=True).stdout


def test_a_task_that_stopped_with_nothing_passed_can_have_its_working_copies_cleared(tmp_path, cleanup_runs, monkeypatch):
    """A stopped task has no result, so "discard" used to answer "no deliverable" and the copy stayed for good."""
    import dashboard_server as d
    proj = project(tmp_path)
    rid = "RUN-TEST-REL5"; cleanup_runs.append(rid)
    sm = StateMachine()
    sm.create_run(rid, str(proj), "goal")
    wt, branch = GitManager.create_worktree(str(proj), rid, base_ref=snapshot(str(proj)))
    sm.update_run_worktree(rid, wt, branch)
    for nxt in (State.PLANNING, State.ORDER_READY, State.BUILDING, State.VERIFYING):     # stopped by the person here
        sm.transition_to(rid, nxt, details="t")
    mission = {"mission_id": "MSN-S", "status": "STOPPED", "project_path": str(proj), "steps": [{"index": 1, "run_id": rid}], "base_worktree": None}

    class Store:
        def load(self, mid): return dict(mission) if mid == "MSN-S" else None
        def save(self, m): mission.update(m)
    monkeypatch.setattr(d, "MissionStore", Store)
    monkeypatch.setattr(d, "_result_manager", lambda: ResultManager())
    monkeypatch.setattr(d, "active_session_id", lambda: "S")
    monkeypatch.setattr(d, "ChatManager", lambda: type("C", (), {"add_message": lambda *a, **k: None})())
    monkeypatch.setattr(d, "invalidate_status_cache", lambda: None)
    mission["status"] = "RUNNING"
    assert d.decide_mission("MSN-S", "discard")["status"] == "busy" and Path(wt).exists()        # never under a running task
    mission["status"] = "STOPPED"
    monkeypatch.setitem(d._ACTIVE_PROJECTS, d._project_key(str(proj)), "MSN-S")                 # its loop is still finishing the step
    assert d.decide_mission("MSN-S", "discard")["status"] == "busy" and Path(wt).exists()
    monkeypatch.delitem(d._ACTIVE_PROJECTS, d._project_key(str(proj)))
    out = d.decide_mission("MSN-S", "discard")
    assert out["status"] == "discarded" and out["released"] == [rid]
    assert not Path(wt).exists() and _branches(proj) == [] and mission["closed"] is True
    assert (proj / "a.py").read_text(encoding="utf-8") == "a = 1\n"                           # the project is untouched
    assert d.decide_mission("MSN-S", "extend")["status"] == "refused"                          # nothing left to continue from
    assert d.decide_mission("MSN-S", "discard")["status"] == "refused"                         # and nothing left to clear


def test_the_stage_offers_to_clear_a_stopped_task_and_shows_why_it_stopped():
    stage = (Path(__file__).resolve().parents[1] / "console" / "stage.js").read_text(encoding="utf-8")
    assert "['BLOCKED','INCOMPLETE','FAILED','STOPPED']" in stage and "ms.status!=='STOPPED'&&last&&AT_WORK.has(last.state)" in stage
    assert "!ms.deliverable&&ms.leftover" in stage and "decideMission(ms.id,'discard',{cleared:'1'})" in stage
    assert "ms.closed" in stage and "ms.settling" in stage


def test_the_stage_says_why_an_apply_was_undone():
    """Found in a real run: skipping a conflicting file left the result broken, the engine put the project back, and
    the open change panel went on saying "held back: conflict" while the card said only "failed"."""
    stage = (Path(__file__).resolve().parents[1] / "console" / "stage.js").read_text(encoding="utf-8")
    assert "else if(state==='rolled_back')said=undone(live.applied);" in stage
    assert "else if(out.status==='rolled_back')mine.done='rolled_back';" in stage
    assert "if(state==='rolled_back')box.append(el('small',undone(ms.applied),'ai-sub'));" in stage


def test_the_working_copy_kept_after_a_skipped_conflict_can_be_cleared_from_the_card(tmp_path, cleanup_runs, monkeypatch):
    import dashboard_server as d
    proj = project(tmp_path)
    rid = "RUN-TEST-REL6"; cleanup_runs.append(rid)
    wt = fake_run(proj, rid, snapshot(str(proj))); _in_task(rid, "MSN-K")
    (wt / "a.py").write_text("a = 2\n", encoding="utf-8"); (wt / "b.py").write_text("b = 2\n", encoding="utf-8")
    (proj / "b.py").write_text("b = 99\n", encoding="utf-8")
    mission = {"mission_id": "MSN-K", "status": "DONE", "project_path": str(proj), "steps": [{"index": 1, "run_id": rid}], "base_worktree": str(wt)}

    class Store:
        def load(self, mid): return dict(mission) if mid == "MSN-K" else None
        def save(self, m): mission.update(m)
    monkeypatch.setattr(d, "MissionStore", Store)
    monkeypatch.setattr(d, "_result_manager", lambda: ResultManager(config={"verification": {"test_command": None}}))
    monkeypatch.setattr(d, "active_session_id", lambda: "S")
    monkeypatch.setattr(d, "ChatManager", lambda: type("C", (), {"add_message": lambda *a, **k: None})())
    monkeypatch.setattr(d, "invalidate_status_cache", lambda: None)
    assert d.decide_mission("MSN-K", "clear")["status"] == "refused" and wt.exists()          # a result still waiting is not cleared this way
    ResultManager(config={"verification": {"test_command": None}}).apply_tree(rid, request_id="rel6", on_conflict="skip")
    mission["applied"] = {"status": "applied", "run_id": rid}
    assert wt.exists()                                                                          # kept: the AIs' b.py is only there
    monkeypatch.setitem(d._ACTIVE_PROJECTS, d._project_key(str(proj)), "MSN-OTHER")
    assert d.decide_mission("MSN-K", "clear")["status"] == "busy" and wt.exists()
    monkeypatch.delitem(d._ACTIVE_PROJECTS, d._project_key(str(proj)))
    out = d.decide_mission("MSN-K", "clear")
    assert out == {"status": "cleared", "released": [rid]} and not wt.exists() and _branches(proj) == []
    assert (proj / "a.py").read_text(encoding="utf-8") == "a = 2\n" and (proj / "b.py").read_text(encoding="utf-8") == "b = 99\n"
    stage = (Path(__file__).resolve().parents[1] / "console" / "stage.js").read_text(encoding="utf-8")
    assert "if(state==='applied'&&ms.leftover){" in stage and "decideMission(ms.id,'clear')" in stage
