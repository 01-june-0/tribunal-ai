"""core/role_checks.py and the opt-in tools in scripts/ that use it - with stand-in agents, never a real CLI."""
import json
import sys
from pathlib import Path

import pytest

from core import role_checks

ROOT = Path(__file__).resolve().parents[1]


class FakeOrch:
    """Builds stand-ins the way Orchestrator._init_* builds real agents."""
    def __init__(self, maker_code="def add(a, b):\n    return a + b\n", fail=None):
        self.maker_code, self.fail, self.built = maker_code, fail, []

    def _init_architect(self, provider):
        self.built.append(("architect", provider))
        outer = self

        class A:
            def create_order(self, goal, ctx):
                if outer.fail == "architect":
                    raise RuntimeError("CLI exited 1")
                assert Path(ctx["project_path"]).is_dir() and "tribunal-role-check-" in ctx["project_path"]
                return role_checks._order()
        return A()

    def _init_maker(self, provider):
        self.built.append(("maker", provider))
        outer = self

        class M:
            def run(self, order, folder):
                (Path(folder) / "src" / "add.py").write_text(outer.maker_code, encoding="utf-8")
                return type("R", (), {"status": "COMPLETED", "files_modified": ["src/add.py"]})()
        return M()

    def _init_inspector(self, provider):
        self.built.append(("inspector", provider))

        class I:
            def review(self, order, diff, verification, worktree_path=None):
                assert "src/add.py" in diff
                return type("V", (), {"verdict": "pass"})()
        return I()


def test_each_role_is_checked_with_the_agent_a_run_would_build():
    orch = FakeOrch()
    results = [role_checks.check(orch, r, "openai") for r in role_checks.ROLES]
    assert [r["ok"] for r in results] == [True, True, True], results
    assert orch.built == [("architect", "openai"), ("maker", "openai"), ("inspector", "openai")]


def test_the_makers_code_runs_in_another_process_and_never_in_this_one(monkeypatch):
    monkeypatch.setattr(role_checks, "CODE_TIMEOUT", 3.0)
    marker = "TRIBUNAL_ROLE_CHECK_RAN_HERE"
    code = f"import os\nos.environ['{marker}'] = '1'\n\ndef add(a, b):\n    return a + b\n"
    result = role_checks.check(FakeOrch(maker_code=code), "maker", "claude")
    assert result["ok"] is True
    import os
    assert marker not in os.environ and "src.add" not in sys.modules            # nothing of it was imported here
    wrong = role_checks.check(FakeOrch(maker_code="def add(a, b):\n    return a - b\n"), "maker", "claude")
    assert wrong["ok"] is False and "AssertionError" in wrong["detail"]
    stuck = role_checks.check(FakeOrch(maker_code="import subprocess, sys\nsubprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\nwhile True:\n    pass\n"), "maker", "claude")
    assert stuck["ok"] is False and stuck["detail"] == "the written code did not finish"   # cut off, child and all


def test_an_inspector_that_reports_its_own_failure_as_a_verdict_is_a_failed_check(monkeypatch):
    """From the review: the Codex and Claude inspectors return a failed call as verdict 'changes_required' with a p0
    such as CONFIG_ERROR or TIMEOUT - counting that as 'works' would pass a broken CLI."""
    for p0, ok in ((["CONFIG_ERROR: Official Codex CLI ('codex') not found"], False), (["TIMEOUT: timed out"], False),
                   (["Codex CLI exited with error code 1: boom"], False), (["add has no tests"], True), ([], True)):
        orch = FakeOrch()
        monkeypatch.setattr(orch, "_init_inspector", lambda provider, p0=p0: type("I", (), {
            "review": lambda self, *a, **k: type("V", (), {"verdict": "changes_required", "p0": p0})()})())
        result = role_checks.check(orch, "inspector", "openai")
        assert result["ok"] is ok, (p0, result)


def test_every_check_works_in_a_git_folder_like_a_real_run(monkeypatch):
    seen = {}
    orch = FakeOrch()
    real = orch._init_architect

    def spy(provider):
        agent = real(provider)
        create = agent.create_order
        def create_order(goal, ctx):
            seen["git"] = (Path(ctx["project_path"]) / ".git").exists()
            return create(goal, ctx)
        agent.create_order = create_order
        return agent
    monkeypatch.setattr(orch, "_init_architect", spy)
    assert role_checks.check(orch, "architect", "openai")["ok"] is True and seen["git"] is True


def test_a_failed_call_is_a_result_and_bad_names_are_refused():
    result = role_checks.check(FakeOrch(fail="architect"), "architect", "antigravity")
    assert result["ok"] is False and "CLI exited 1" in result["detail"]
    assert role_checks.plan(["maker"], ["openai", "claude"]) == [("maker", "openai"), ("maker", "claude")]
    with pytest.raises(ValueError):
        role_checks.plan(["builder"], ["openai"])                                 # old role names are not accepted here
    assert role_checks.current_assignment({"architect": {"provider": "claude"}, "maker": {"provider": "codex"},
                                           "inspector": {"provider": "google"}}) == {"architect": "claude", "maker": "openai", "inspector": "antigravity"}


def test_the_diagnostics_tool_checks_the_current_assignment_and_writes_its_report(monkeypatch, tmp_path, capsys):
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    import cli_diagnostics
    import core.env_utils as env
    import core.orchestrator as orchestrator
    monkeypatch.setattr(cli_diagnostics, "REPORT", tmp_path / "report.json")
    monkeypatch.setattr(env, "resolve_cli", lambda name: None if name == "agy" else "/bin/" + name)
    monkeypatch.setattr(env, "probe_version", lambda exe, t: "1.0")
    monkeypatch.setattr(orchestrator, "Orchestrator", lambda config: FakeOrch())
    monkeypatch.setattr("director.load_config", lambda: {"architect": {"provider": "claude"}, "maker": {"provider": "codex"},
                                                         "inspector": {"provider": "antigravity"}})
    assert cli_diagnostics.main() == 1                                            # Antigravity is not installed here
    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert report["roles"] == {"architect": "claude", "maker": "openai", "inspector": "antigravity"}
    assert {c["role"]: c["ok"] for c in report["checks"]} == {"architect": True, "maker": True, "inspector": False}
    assert report["providers"]["antigravity"]["state"] == "MISSING" and report["providers"]["claude"]["state"] == "VERIFIED"


def test_the_smoke_tool_and_the_retry_tool_refuse_bad_input(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    import retry_transport_run
    import test_role_cli_smoke
    assert retry_transport_run.main([]) == 2 and retry_transport_run.main(["not-a-run"]) == 2
    with pytest.raises(ValueError):
        test_role_cli_smoke.main(["--providers", "gpt"])
    src = (ROOT / "scripts" / "test_role_cli_smoke.py").read_text(encoding="utf-8")
    assert "exec(" not in src and "exec(" not in (ROOT / "core" / "role_checks.py").read_text(encoding="utf-8")
