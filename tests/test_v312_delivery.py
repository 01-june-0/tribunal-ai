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
