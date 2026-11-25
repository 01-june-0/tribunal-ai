"""Node tests run by the verifier, and no role asks for records of a process (a mission once failed six steps that
way although every test passed)."""
import inspect
import json
import shutil
import sys
from pathlib import Path

import pytest

from core.verifier import Verifier
from core import evidence_rules

NODE = shutil.which("node")
NODE_TEST = "const test = require('node:test');\nconst assert = require('node:assert');\n"


def _write(root: Path, rel: str, text: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def test_finds_only_files_written_for_the_node_runner(tmp_path):
    _write(tmp_path, "tests/game.test.js", NODE_TEST + "test('x', () => assert.ok(true));\n")
    _write(tmp_path, "tests/jest_style.test.js", "describe('x', () => { it('y', () => expect(1).toBe(1)); });\n")
    _write(tmp_path, "src/game.js", NODE_TEST)                                   # not a test file name
    _write(tmp_path, "node_modules/lib/a.test.js", NODE_TEST)
    _write(tmp_path, ".hidden/b.test.js", NODE_TEST)
    _write(tmp_path, "test-esm.mjs", "import test from 'node:test';\n")
    assert Verifier._node_test_files(tmp_path) == ["test-esm.mjs", "tests/game.test.js"]


def test_no_node_files_means_no_command(tmp_path):
    _write(tmp_path, "tests/test_x.py", "def test_x():\n    assert True\n")
    assert Verifier.node_test_command(tmp_path) == (None, None)


def test_package_test_script_is_used_and_placeholder_ignored(tmp_path, monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name: f"/bin/{name}")
    _write(tmp_path, "package.json", json.dumps({"scripts": {"test": "echo \"Error: no test specified\" && exit 1"}}))
    assert Verifier.node_test_command(tmp_path) == (None, None)
    _write(tmp_path, "package.json", json.dumps({"scripts": {"test": "node --test"}}))
    assert Verifier.node_test_command(tmp_path) == (["/bin/npm", "test"], None)


def test_a_test_script_needing_packages_never_runs(tmp_path, monkeypatch):
    # Tribunal's copies have no node_modules; running it only when applying (where they exist) could undo a pass
    monkeypatch.setattr(shutil, "which", lambda name: f"/bin/{name}")
    _write(tmp_path, "package.json", json.dumps({"scripts": {"test": "jest"}, "devDependencies": {"jest": "^29"}}))
    (tmp_path / "node_modules").mkdir()
    cmd, note = Verifier.node_test_command(tmp_path)
    assert cmd is None and "dependencies" in note


@pytest.mark.parametrize("cmd, already", [
    ("python -m pytest tests/", False), (["python", "-m", "pytest"], False), (None, False),
    ("npm test", True), (["C:/Program Files/nodejs/npm.cmd", "test"], True), ("node --test tests", True),
    ("npx jest", True),
])
def test_a_node_test_command_is_not_run_twice(cmd, already):
    assert Verifier._runs_node_already(cmd) is already


def test_a_failing_node_run_is_never_an_unchanged_preexisting_failure():
    from core import autopilot
    base = {"passed": False, "test": {"output": "FAILED tests/test_a.py::test_x"}}
    post = {"passed": False, "test": {"output": "FAILED tests/test_a.py::test_x"}, "build": {}, "lint": {}}
    assert autopilot.only_preexisting_failures(base, post) == {"tests/test_a.py::test_x"}
    post["node_tests"] = {"passed": False}
    assert autopilot.only_preexisting_failures(base, post) is None


def test_node_runner_files_run_even_with_a_test_script(tmp_path, monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name: f"/bin/{name}")
    _write(tmp_path, "package.json", json.dumps({"scripts": {"test": "echo 99 passed"}}))
    _write(tmp_path, "tests/stage.test.js", NODE_TEST)
    assert Verifier.node_test_command(tmp_path) == (["/bin/node", "--test", "tests/stage.test.js"], None)


def test_missing_node_is_reported(tmp_path, monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name: None)
    _write(tmp_path, "a.test.js", NODE_TEST)
    cmd, note = Verifier.node_test_command(tmp_path)
    assert cmd is None and "node is not installed" in note
    out = Verifier.verify(str(tmp_path), test_cmd=None, git_checks=False)
    assert "Node tests not run" in out["summary"] and out["passed"] is True


@pytest.mark.parametrize("output, expected", [
    ("ℹ tests 18\nℹ suites 0\nℹ pass 18\nℹ fail 0\n", (18, 0)),
    ("# tests 5\n# pass 3\n# fail 2\n", (3, 2)),
    ("Test Suites: 1 passed, 1 total\nTests:       1 failed, 17 passed, 18 total\n", (17, 1)),
    (" Test Files  2 passed (2)\n      Tests  9 passed (9)\n", (9, 0)),
    ("ℹ pass 2\nℹ fail 0\nℹ pass 3\nℹ fail 1\n", (5, 1)),
    ("  12 passing (20ms)\n  1 failing\n", (12, 1)),
    ("", (0, 0)),
])
def test_node_counts(output, expected):
    counts = Verifier._parse_node_counts(output)
    assert (counts["passed"], counts["failed"]) == expected and counts["total"] == sum(expected)


@pytest.mark.skipif(not NODE, reason="node is not installed")
def test_verify_runs_node_tests_after_pytest_and_adds_the_counts(tmp_path):
    _write(tmp_path, "tests/test_smoke.py", "def test_smoke():\n    assert True\n")
    _write(tmp_path, "tests/stage.test.js", NODE_TEST + "test('a', () => assert.equal(1, 1));\ntest('b', () => assert.ok(1));\n")
    cmd = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests"]
    out = Verifier.verify(str(tmp_path), test_cmd=cmd, git_checks=False)
    assert out["passed"] is True, out["test"]["output"][-2000:]
    assert out["test_counts"]["passed"] == 3 and out["test_counts"]["failed"] == 0
    assert out["node_tests"]["passed"] is True and "Node tests: PASS" in out["summary"]
    assert "===== Node tests:" in out["test"]["output"]


@pytest.mark.skipif(not NODE, reason="node is not installed")
def test_a_failing_node_test_fails_verification(tmp_path):
    _write(tmp_path, "stage.test.js", NODE_TEST + "test('broken', () => assert.equal(1, 2));\n")
    out = Verifier.verify(str(tmp_path), test_cmd=None, git_checks=False)
    assert out["passed"] is False and out["test_counts"]["failed"] == 1
    assert "Node tests: FAIL" in out["summary"]


def test_every_order_writer_and_judge_carries_the_evidence_rules():
    from agents import architect, claude_architect, codex_architect, claude_inspector, codex_inspector, google_roles
    assert "CRITERIA_RULE" in inspect.getsource(architect.BaseArchitect.plan_next)
    for cls in (claude_architect.ClaudeArchitect, codex_architect.CodexArchitect):
        assert "CRITERIA_RULE" in inspect.getsource(cls.create_order)
        assert "CRITERIA_RULE" in inspect.getsource(cls.chat)
        assert "DECIDE_RULE" in inspect.getsource(cls.decide)
    for cls in (claude_inspector.ClaudeInspector, codex_inspector.CodexInspector, google_roles.GoogleInspector):
        assert "INSPECTOR_RULE" in inspect.getsource(cls)
    for rule in (evidence_rules.CRITERIA_RULE, evidence_rules.INSPECTOR_RULE, evidence_rules.DECIDE_RULE):
        assert "browser play-throughs" in rule and "baseline" in rule


def test_plan_next_prompt_contains_the_criteria_rule(tmp_path):
    from agents.architect import BaseArchitect
    seen = {}

    class Stub(BaseArchitect):
        def create_order(self, *a, **k): ...
        def decide(self, *a, **k): ...
        def chat(self, *a, **k): ...
        def get_provenance(self, *a, **k): ...
        def _invoke_cli(self, prompt, cwd=None):
            seen["prompt"] = prompt
            return '{"status": "BLOCKED", "reason": "x"}'
        def _extract_json(self, text):
            return json.loads(text)

    Stub().plan_next("make a game", [], {"project_path": str(tmp_path)}, cwd=str(tmp_path))
    assert evidence_rules.CRITERIA_RULE in seen["prompt"]
