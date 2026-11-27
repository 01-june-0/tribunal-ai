"""The read-only CLI runner (core/cli_runner.py): one bounded retry for transient transport failures only, never
for quota, authentication or content failures; official subscription commands only."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from core.process_runner import ProcessResult, ProcessTreeRunner
from core.cli_runner import ProviderCallError, ReadOnlyCliRunner


def _git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "workspace"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True, capture_output=True)
    return repo


def _google_stream(status: str, response: str = "") -> str:
    return json.dumps({"event": "result", "result": {"status": status, "response": response}}) + "\n"


# ---------------------------------------------------------------------------------- 1-4, 9: runner-level

def test_1_empty_response_then_valid_response_succeeds_on_retry(tmp_path, monkeypatch):
    """empty response -> 1 retry -> normal response -> stage succeeds."""
    repo = _git_repo(tmp_path)
    calls = {"n": 0}

    def fake_run(argv, **kwargs):
        if "--version" in argv:
            return ProcessResult(exit_code=0, stdout="test-1", stderr="", timed_out=False, duration_sec=0.05, pid=1)
        calls["n"] += 1
        if calls["n"] == 1:
            return ProcessResult(exit_code=0, stdout=_google_stream("SUCCESS", ""), stderr="", timed_out=False,
                                  duration_sec=0.5, pid=1)
        return ProcessResult(exit_code=0, stdout=_google_stream("SUCCESS", "a real proposal"), stderr="",
                              timed_out=False, duration_sec=0.5, pid=1)

    monkeypatch.setattr(ProcessTreeRunner, "run", staticmethod(fake_run))
    runner = ReadOnlyCliRunner(executables={"GOOGLE": sys.executable})
    result = runner.invoke("GOOGLE", "the original prompt", str(repo), "REVIEWING")
    assert result["output"] == "a real proposal"
    assert result["attempt_number"] == 2
    assert calls["n"] == 2
    assert len(result["attempts"]) == 1
    assert result["attempts"][0]["outcome"] == "FAILED"
    assert result["attempts"][0]["error"] == "GOOGLE_STREAM_EMPTY_RESPONSE"
    assert result["attempts"][0]["retryable"] is True


def test_2_empty_response_on_both_attempts_is_human_required(tmp_path, monkeypatch):
    """empty response -> retry also empty -> HUMAN_REQUIRED (raised, no third attempt)."""
    repo = _git_repo(tmp_path)
    calls = {"n": 0}

    def fake_run(argv, **kwargs):
        calls["n"] += 1
        return ProcessResult(exit_code=0, stdout=_google_stream("SUCCESS", ""), stderr="", timed_out=False,
                              duration_sec=0.5, pid=1)

    monkeypatch.setattr(ProcessTreeRunner, "run", staticmethod(fake_run))
    runner = ReadOnlyCliRunner(executables={"GOOGLE": sys.executable})
    with pytest.raises(ProviderCallError) as excinfo:
        runner.invoke("GOOGLE", "the original prompt", str(repo), "REVIEWING")
    assert calls["n"] == 2   # exactly MAX_ATTEMPTS, never more (no infinite retry)
    assert "GOOGLE_STREAM_EMPTY_RESPONSE" in str(excinfo.value)
    attempts = excinfo.value.attempts
    assert len(attempts) == 2 and all(a["outcome"] == "FAILED" for a in attempts)
    assert attempts[0]["attempt_number"] == 1 and attempts[1]["attempt_number"] == 2
    assert attempts[1]["retry_reason"] == attempts[0]["error"]


def test_3_quota_error_is_never_retried(tmp_path, monkeypatch):
    """quota error -> retry 0 -> HUMAN_REQUIRED on the first attempt."""
    repo = _git_repo(tmp_path)
    calls = {"n": 0}

    def fake_run(argv, **kwargs):
        calls["n"] += 1
        return ProcessResult(exit_code=1, stdout="", stderr="Error: usage limit reached for this session",
                              timed_out=False, duration_sec=0.2, pid=1)

    monkeypatch.setattr(ProcessTreeRunner, "run", staticmethod(fake_run))
    runner = ReadOnlyCliRunner(executables={"OPENAI": sys.executable})
    with pytest.raises(ProviderCallError) as excinfo:
        runner.invoke("OPENAI", "prompt", str(repo), "REVIEWING")
    assert calls["n"] == 1   # no retry attempted
    assert len(excinfo.value.attempts) == 1
    assert excinfo.value.attempts[0]["retryable"] is False


def test_4_auth_error_is_never_retried(tmp_path, monkeypatch):
    """auth failure -> retry 0."""
    repo = _git_repo(tmp_path)
    calls = {"n": 0}

    def fake_run(argv, **kwargs):
        calls["n"] += 1
        return ProcessResult(exit_code=1, stdout="", stderr="Error: authentication failed, please log in again",
                              timed_out=False, duration_sec=0.2, pid=1)

    monkeypatch.setattr(ProcessTreeRunner, "run", staticmethod(fake_run))
    runner = ReadOnlyCliRunner(executables={"ANTHROPIC": sys.executable})
    with pytest.raises(ProviderCallError):
        runner.invoke("ANTHROPIC", "prompt", str(repo), "REVIEWING")
    assert calls["n"] == 1


def test_4b_genuine_timeout_is_retried_and_provider_unavailable_is_not(tmp_path, monkeypatch):
    """Positive control (timeout retried) alongside a negative control (explicitly-named non-retryable
    category) in one test to pin both ends of the classifier."""
    repo = _git_repo(tmp_path)
    calls = {"n": 0}

    def fake_timeout(argv, **kwargs):
        if "--version" in argv:
            return ProcessResult(exit_code=0, stdout="test-1", stderr="", timed_out=False, duration_sec=0.05, pid=1)
        calls["n"] += 1
        if calls["n"] == 1:
            return ProcessResult(exit_code=None, stdout="", stderr="", timed_out=True, duration_sec=300.0,
                                  pid=1, timeout_reason="hard timeout exceeded")
        return ProcessResult(exit_code=0, stdout=json.dumps({"result": "ok"}), stderr="", timed_out=False,
                              duration_sec=0.5, pid=1)

    monkeypatch.setattr(ProcessTreeRunner, "run", staticmethod(fake_timeout))
    runner = ReadOnlyCliRunner(executables={"ANTHROPIC": sys.executable})
    result = runner.invoke("ANTHROPIC", "prompt", str(repo), "SYNTHESIS")
    assert result["attempt_number"] == 2 and calls["n"] == 2   # timeout is retried once, then succeeds

    calls2 = {"n": 0}

    def fake_unavailable(argv, **kwargs):
        calls2["n"] += 1
        return ProcessResult(exit_code=1, stdout="", stderr="503 Service Unavailable", timed_out=False,
                              duration_sec=0.2, pid=1)

    monkeypatch.setattr(ProcessTreeRunner, "run", staticmethod(fake_unavailable))
    runner2 = ReadOnlyCliRunner(executables={"OPENAI": sys.executable})
    with pytest.raises(ProviderCallError):
        runner2.invoke("OPENAI", "prompt", str(repo), "SYNTHESIS")
    assert calls2["n"] == 1   # "provider unavailable/blocked" is on the never-retry list, not just TIMEOUT


def test_9_retry_never_bypasses_the_real_cli_guard_in_default_regression(tmp_path):
    """Every attempt - including a retry - must still funnel through the REAL ProcessTreeRunner.run() (not
    mocked in this one test), so the existing REAL_CLI_CALL_DURING_UNIT_TEST guard (DIRECTOR_TESTING=1)
    blocks it exactly as before; the retry loop introduces no second code path that could reach a real
    subscription CLI in a unit test."""
    repo = _git_repo(tmp_path)
    # a real file whose basename ("codex") matches REAL_CLI_BASENAMES, so the guard's argv[0] check fires -
    # unlike sys.executable, this exercises the actual, unmocked ProcessTreeRunner.run guard path.
    fake_codex = tmp_path / "codex"
    fake_codex.write_text("", encoding="utf-8")
    before = len(ProcessTreeRunner.blocked_real_cli_calls)
    runner = ReadOnlyCliRunner(executables={"OPENAI": str(fake_codex)})
    with pytest.raises(Exception):
        runner.invoke("OPENAI", "prompt", str(repo), "REVIEWING")
    blocked = ProcessTreeRunner.blocked_real_cli_calls[before:]
    assert len(blocked) == 1   # the guard fired on the very first attempt; no attempt ever got past it -
    # MAX_ATTEMPTS=2 exists for genuinely transient failures, but "refusing to launch a real CLI under
    # DIRECTOR_TESTING=1" is not retryable by construction (RealCliCallDuringUnitTest, not
    # ProviderCallError, so _is_retryable is never even consulted).
    del ProcessTreeRunner.blocked_real_cli_calls[before:]   # this test provoked it deliberately


def test_official_cli_commands_are_read_only_and_subscription_only():
    runner = ReadOnlyCliRunner(executables={"OPENAI": "codex", "ANTHROPIC": "claude", "GOOGLE": "agy"})
    codex, codex_stdin, _ = runner._command("OPENAI", "codex", "p")
    claude, claude_stdin, _ = runner._command("ANTHROPIC", "claude", "p")
    google, google_stdin, _ = runner._command("GOOGLE", "agy", "p")
    assert codex == ["codex", "exec", "--sandbox", "read-only", "-"] and codex_stdin == "p"
    assert claude == ["claude", "--print", "--output-format", "json", "--setting-sources", "project,local"] and claude_stdin == "p"
    assert google == ["agy", "--input-format", "stream-json", "--output-format", "stream-json", "--sandbox"]
    google_message = json.loads(google_stdin)
    assert google_message["event"] == "user"
    assert google_message["message"]["content"][0]["text"] == "p"
    assert "accept-edits" not in google


def test_the_triad_research_mode_is_gone():
    """Removed on 2026-11-22: nothing may import it back by accident."""
    root = Path(__file__).resolve().parents[1]
    for gone in ("core/research_orchestrator.py", "core/research_state.py", "core/research_prompts.py", "core/research_experiment.py",
                 "core/research_runner.py", "core/triad_provider.py", "core/greenfield.py", "schemas/research.py"):
        assert not (root / gone).exists(), gone
    for path in list((root / "core").glob("*.py")) + list((root / "agents").glob("*.py")) + [root / "dashboard_server.py", root / "companion_server.py"]:
        text = path.read_text(encoding="utf-8").lower()
        assert "triad" not in text and "research_" not in text, path.name


# ---------------------------------------------------------------------------------- the bootstrap's file inventory

def test_the_inventory_sorts_what_a_project_holds(tmp_path):
    """core/project_inventory.py was carved out of the removed research code; the bootstrap depends on it."""
    from core.project_inventory import _inventory
    project = tmp_path / "p"
    for rel in ("src/app.py", "package.json", "tests/test_app.py", "README.md", ".venv/lib/x.py", "notes.txt"):
        target = project / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("x", encoding="utf-8")
    found = _inventory(project)
    assert sorted(found["meaningful_source_files"]) == ["package.json", "src/app.py"]
    assert found["test_files"] == ["tests/test_app.py"] and found["unsafe_entries"] == []
    assert not any("README" in p or ".venv" in p for kind in found.values() for p in kind)   # benign and ignored entries appear nowhere


def test_a_link_out_of_the_project_is_reported_not_followed(tmp_path):
    from core.project_inventory import _inventory
    project, outside = tmp_path / "p", tmp_path / "outside"
    (project / "src").mkdir(parents=True)
    outside.mkdir()
    (outside / "secret.py").write_text("x", encoding="utf-8")
    (project / "src" / "real.py").write_text("x", encoding="utf-8")
    try:
        (project / "inside_link.py").symlink_to(project / "src" / "real.py")
        (project / "escape").symlink_to(outside)
    except OSError:
        pytest.skip("symlinks are not available here")
    found = _inventory(project)                         # must not raise: a missing import once made this a NameError
    assert "escape" in found["unsafe_entries"] and "inside_link.py" not in found["unsafe_entries"]
    assert not any("secret" in p for kind in found.values() for p in kind)
