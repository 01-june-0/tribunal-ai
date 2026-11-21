"""Independent tests proposed by the inspector: Tribunal writes them, runs them and takes them out again."""
import json
import logging
import sys
from pathlib import Path

import pytest

from core import autopilot, inspector_tests as it
from core.orchestrator import Orchestrator
from schemas.review_result import ReviewResultSchema

LOG = logging.getLogger("test")
GOOD = "from calc import add\n\n\ndef test_add_small_numbers():\n    assert add(2, 3) == 5\n"
BAD = "from calc import add\n\n\ndef test_add_rejects_text():\n    assert add('a', 'b') == 0        # the code has no such rule: this test fails\n"


@pytest.fixture
def project(tmp_path):
    tmp_path = tmp_path / "proj"; tmp_path.mkdir()                          # the run record (tmp_path/_run) is outside it, as in real runs
    (tmp_path / "calc.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_calc.py").write_text("from calc import add\n\n\ndef test_add():\n    assert add(1, 1) == 2\n", encoding="utf-8")
    (tmp_path / "conftest.py").write_text("", encoding="utf-8")
    return tmp_path


class FakeOrch:
    """Just what core.inspector_tests needs from the orchestrator."""
    def __init__(self, tmp_path, proxy=False):
        self.dir = tmp_path / "_run"; self.dir.mkdir(parents=True, exist_ok=True)
        self.saved, self.audit, self.proxy, self.settled = {}, [], proxy, []
        self.sm = type("SM", (), {"log_audit": lambda _s, *a: self.audit.append(a)})()
        self.config = {"autonomy": {}}
    def _verification_cmds(self): return None, f'"{sys.executable}" -m pytest -q -p no:cacheprovider tests', None
    def _get_run_dir(self, run_id): return self.dir
    def _save_json(self, run_id, name, data): self.saved[name] = data
    def _load_json(self, run_id, name): return self.saved.get(name)


def review(*tests):
    return ReviewResultSchema(verdict="pass", summary="looks fine", tests=[{"path": p, "content": c} for p, c in tests])


def test_only_new_marked_files_inside_a_test_directory_are_accepted(project):
    (project / "src").mkdir()
    wanted = [("tests/test_inspector_edges.py", GOOD), ("tests/test_calc.py", GOOD), ("tests/test_edges.py", GOOD), ("src/test_inspector_x.py", GOOD),
              ("../test_inspector_out.py", GOOD), ("/tmp/tests/test_inspector_abs.py", GOOD), ("tests\\test_inspector_win.py", GOOD),
              ("tests/missing/test_inspector_dir.py", GOOD), ("tests/test_inspector_big.py", "x" * (it.MAX_CHARS + 1)), ("tests/test_inspector_empty.py", " "),
              ("calc.py", "def add(a, b):\n    return 0\n"), ("tests/test_inspector_edges.py", GOOD), (".git/tests/test_inspector_g.py", GOOD)]
    accepted, rejected = it.select([{"path": p, "content": c} for p, c in wanted], str(project))
    assert accepted == [("tests/test_inspector_edges.py", GOOD)] and len(rejected) == len(wanted) - 1
    assert {r["path"]: r["reason"] for r in rejected}["calc.py"]            # never a way to change the code under review
    many = [{"path": f"tests/test_inspector_n{i}.py", "content": GOOD} for i in range(5)]
    assert len(it.select(many, str(project))[0]) == it.MAX_FILES
    assert it.select([{"path": "tests/inspector_api.test.js", "content": "test('x',()=>{})"}], str(project))[0]
    assert not list(project.rglob("test_inspector_*"))                      # choosing writes nothing


def test_passing_tests_are_run_recorded_and_taken_out_again(project, tmp_path):
    orch, rv = FakeOrch(tmp_path, proxy=True), review(("tests/test_inspector_sum.py", GOOD))
    before = sorted(p.relative_to(project).as_posix() for p in project.rglob("*"))
    it.run(orch, "RUN-1", rv, str(project), {"passed": True}, LOG)
    after = sorted(p.relative_to(project).as_posix() for p in project.rglob("*"))
    assert after == before                                                  # the worktree is exactly as it was: not even a cache file
    record = orch.saved["inspector_tests.json"]
    assert record["ran"] and record["passed"] is True and record["files"] == ["tests/test_inspector_sum.py"] and record["test_counts"]["passed"] == 2
    assert (orch.dir / "inspector_tests" / "files" / "tests" / "test_inspector_sum.py").read_text() == GOOD      # kept as evidence
    assert not (orch.dir / "inspector_tests" / "sandbox").exists()          # the copy it ran in is gone
    assert rv.verdict == "pass" and not rv.p1 and rv.tests == [] and "independent tests by the inspector: 1 file(s), PASS" in rv.summary
    assert orch.audit[-1][2] == "INSPECTOR_TESTS"


def test_whatever_an_inspector_test_does_to_files_stays_in_the_copy(project, tmp_path):
    vandal = ("from pathlib import Path\n\n\ndef test_breaks_things():\n    root = Path(__file__).resolve().parent.parent\n"
              "    (root / 'calc.py').write_text('def add(a, b):\\n    return 0\\n')\n    (root / 'tests' / 'test_calc.py').unlink()\n"
              "    (root / 'planted.txt').write_text('x')\n")
    orch, rv = FakeOrch(tmp_path), review(("tests/test_inspector_vandal.py", vandal))
    it.run(orch, "RUN-1", rv, str(project), {"passed": True}, LOG)
    assert orch.saved["inspector_tests.json"]["ran"]
    assert (project / "calc.py").read_text() == "def add(a, b):\n    return a + b\n"          # the real worktree is untouched
    assert (project / "tests" / "test_calc.py").exists() and not (project / "planted.txt").exists()
    assert not (project / "tests" / "test_inspector_vandal.py").exists()


def test_a_worktree_too_large_to_copy_skips_the_check(project, tmp_path, monkeypatch):
    monkeypatch.setattr(it, "MAX_COPY_FILES", 1)
    orch, rv = FakeOrch(tmp_path), review(("tests/test_inspector_sum.py", GOOD))
    it.run(orch, "RUN-1", rv, str(project), {"passed": True}, LOG)
    assert orch.saved["inspector_tests.json"]["skipped"] == "the worktree is too large to copy" and rv.verdict == "pass"


def test_a_failing_test_becomes_a_p1_finding(project, tmp_path):
    orch, rv = FakeOrch(tmp_path), review(("tests/test_inspector_types.py", BAD))
    it.run(orch, "RUN-1", rv, str(project), {"passed": True}, LOG)
    assert rv.verdict == "changes_required" and len(rv.p1) == 1 and rv.p1[0].startswith("INSPECTOR_TEST_FAILED:")
    assert "tests/test_inspector_types.py" in rv.p1[0] and "test_add_rejects_text" in rv.p1[0]
    assert not (project / "tests" / "test_inspector_types.py").exists()
    assert orch.saved["inspector_tests.json"]["passed"] is False and [t.path for t in rv.tests] == ["tests/test_inspector_types.py"]
    told = it.previous_failure(orch, "RUN-1")
    assert "tests/test_inspector_types.py" in told and "test_add_rejects_text" in told
    assert "YOUR TESTS FROM THE PREVIOUS ROUND FAILED" in it.prompt_section({"inspector_tests": {"wanted": True, "previous": told}})
    it.run(orch, "RUN-1", review(), str(project), {"passed": True}, LOG)      # next round: the inspector dropped its test
    assert it.previous_failure(orch, "RUN-1") is None                       # so the old failure is no longer brought up


def test_nothing_runs_when_there_is_nothing_sound_to_run(project, tmp_path):
    for case, verification, tests in (("none", {"passed": True}, []), ("rejected", {"passed": True}, [("calc.py", "x = 1\n")]),
                                      ("red", {"passed": False}, [("tests/test_inspector_a.py", GOOD)])):
        orch = FakeOrch(tmp_path / case)
        rv = review(*tests)
        it.run(orch, "RUN-1", rv, str(project), verification, LOG)
        assert rv.verdict == "pass" and not rv.p1, case
        assert orch.saved.get("inspector_tests.json", {}).get("ran", False) is False, case
    assert not list(project.rglob("test_inspector_*"))
    assert it.previous_failure(FakeOrch(tmp_path / "x"), "RUN-1") is None


def test_a_run_record_inside_the_worktree_is_never_copied_into_itself(project):
    orch, rv = FakeOrch(project), review(("tests/test_inspector_sum.py", GOOD))
    it.run(orch, "RUN-1", rv, str(project), {"passed": True}, LOG)
    assert orch.saved["inspector_tests.json"]["skipped"] == "the run record is inside the worktree"


def test_the_review_asks_for_tests_only_when_they_will_be_run():
    assert it.prompt_section({"passed": True}) == "" and it.prompt_section({"inspector_tests": {"wanted": False}}) == ""
    text = it.prompt_section({"inspector_tests": {"wanted": True, "previous": None}})
    assert "INDEPENDENT TESTS (optional)" in text and "test_inspector_<topic>.py" in text and "PREVIOUS ROUND" not in text
    for agent in ("claude_inspector.py", "codex_inspector.py", "google_roles.py"):
        source = (Path(__file__).resolve().parent.parent / "agents" / agent).read_text(encoding="utf-8")
        assert "inspector_tests.prompt_section(verification)" in source, agent


def test_a_malformed_tests_field_never_spoils_the_review():
    rv = ReviewResultSchema.model_validate({"verdict": "pass", "summary": "ok", "tests": "none"})
    assert rv.tests == []
    rv = ReviewResultSchema.model_validate({"verdict": "pass", "summary": "ok", "tests": [{"path": "a"}, 3, {"path": "tests/x.py", "content": "c"},
                                                                                         {"path": "tests/huge.py", "content": "x" * 20_001}]})
    assert [t.path for t in rv.tests] == ["tests/x.py"]
    assert ReviewResultSchema.model_validate({"verdict": "pass", "summary": "ok"}).tests == []


def test_it_is_on_by_default_and_off_for_quick_requests():
    assert it.enabled({}) and it.enabled({"autonomy": {"inspector_tests": True}}) and not it.enabled({"autonomy": {"inspector_tests": False}})
    assert autopilot.profile_overrides({}, "quick")["inspector_tests"] is False
    assert "inspector_tests" not in autopilot.profile_overrides({}, "standard")
    assert autopilot.profile_overrides({"autonomy": {"profiles": {"quick": {"inspector_tests": True}}}}, "quick")["inspector_tests"] is True


def test_the_pipeline_runs_them_after_the_review(project, tmp_path, monkeypatch):
    orch = FakeOrch(tmp_path)
    seen = {}

    def reviewer(run_id, order, verification, context, worktree, logger, records):
        seen.update(verification["inspector_tests"])
        return review(("tests/test_inspector_types.py", BAD)), None
    orch._review_with_failover = reviewer
    rv, stop = Orchestrator.run_inspector_with_failover(orch, "RUN-1", None, {"passed": True, "git_diff": ""}, {}, str(project), LOG, [])
    assert stop is None and seen == {"wanted": True, "previous": None}
    assert rv.verdict == "changes_required" and orch.saved["review.json"] is rv
    orch.config = {"autonomy": {"inspector_tests": False}}                  # switched off: asked for nothing, runs nothing
    orch.saved.clear()
    rv, _ = Orchestrator.run_inspector_with_failover(orch, "RUN-2", None, {"passed": True}, {}, str(project), LOG, [])
    assert seen["wanted"] is False and rv.verdict == "pass" and rv.tests == [] and "inspector_tests.json" not in orch.saved
    orch.saved["inspector_tests.json"] = {"passed": False, "files": ["tests/test_inspector_old.py"], "output_tail": "x"}
    Orchestrator.run_inspector_with_failover(orch, "RUN-2", None, {"passed": True}, {}, str(project), LOG, [])
    assert it.previous_failure(orch, "RUN-2") is None                       # an old failure is cleared when the check is off
    orch._review_with_failover = lambda *a: (None, {"final_state": "FAIL"})   # a review that stopped the run is passed through
    assert Orchestrator.run_inspector_with_failover(orch, "RUN-3", None, {"passed": True}, {}, str(project), LOG, []) == (None, {"final_state": "FAIL"})
