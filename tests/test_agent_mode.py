"""Agent mode: the Maker CLI works in the worktree itself; a few kinds of command wait for the person."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from core import agent_guard
from core.safety import SafetyPolicy
from schemas.order import OrderSchema

posix_only = pytest.mark.skipif(os.name == "nt", reason="the fake CLI is a shell script")


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("TRIBUNAL_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("DIRECTOR_TESTING", "1")
    from core import setup
    setup.acknowledge("agent")
    return tmp_path / "home"


def test_nothing_runs_before_the_person_agrees(tmp_path, monkeypatch):
    monkeypatch.setenv("TRIBUNAL_HOME", str(tmp_path / "home"))
    from agents.agent_maker import AgentMaker
    from core import setup
    assert not setup.agent_consented()
    out = AgentMaker(provider="codex", executable=str(tmp_path / "never")).run(_order(), str(tmp_path))
    assert out.status == "FAILED" and out.error.startswith("PERMISSION_CONSENT_MISSING")
    setup.acknowledge("agent")
    assert setup.agent_consented() and setup.acknowledged()["agent_terms"] == setup.AGENT_TERMS


def _git(root, *args):
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


def _repo(path: Path) -> Path:
    path.mkdir(parents=True)
    _git(path, "init", "-q")
    _git(path, "config", "user.email", "t@example.invalid")
    _git(path, "config", "user.name", "t")
    (path / "README.md").write_text("x\n")
    _git(path, "add", ".")
    _git(path, "commit", "-qm", "init")
    return path


def _order(**kw):
    base = dict(goal="make a thing", context="", allowed_paths=["src/"], protected_paths=[], acceptance_criteria=["works"],
                max_files_changed=2, max_diff_lines=10)
    base.update(kw)
    return OrderSchema(**base)


@pytest.mark.parametrize("name,args,expected", [
    ("brew", ["install", "ffmpeg"], "system_install"),
    ("sudo", ["apt-get", "install", "x"], "system_install"),
    ("npm", ["install", "react"], None),
    ("npm", ["i", "-g", "typescript"], "system_install"),
    ("yarn", ["global", "add", "x"], "system_install"),
    ("npm", ["publish"], "irreversible"),
    ("pip", ["install", "--user", "x"], "system_install"),
    ("pip", ["install", "--target", "lib", "x"], None),
    ("python3", ["-m", "pip", "install", "x"], "system_install"),
    ("python3", ["-m", "pytest"], None),
    ("git", ["status"], None),
    ("git", ["-C", "x", "push", "origin"], "irreversible"),
    ("gh", ["pr", "create"], "irreversible"),
    ("gh", ["pr", "view"], None),
    ("gh", ["api", "repos/x/y"], None),
    ("gh", ["api", "-X", "POST", "repos/x/y"], "irreversible"),
    ("gh", ["auth", "token"], "money_credentials"),
    ("vercel", ["--prod"], "irreversible"),
    ("vercel", ["dev"], None),
    ("docker", ["build", "."], None),
    ("docker", ["push", "x"], "irreversible"),
    ("aws", ["s3", "ls"], "irreversible"),
    ("stripe", ["listen"], "money_credentials"),
    ("security", ["find-generic-password", "-s", "x"], None),   # Claude Code reads its own sign-in this way
    ("cargo", ["install", "ripgrep"], "system_install"),
    ("cargo", ["build"], None),
    ("brew.exe", ["install", "x"], "system_install"),
])
def test_what_waits_for_the_person(name, args, expected):
    assert agent_guard.classify(name, args) == expected


def test_pip_inside_a_virtual_environment_is_fine(tmp_path):
    venv = tmp_path / ".venv" / "bin"
    venv.mkdir(parents=True)
    (tmp_path / ".venv" / "pyvenv.cfg").write_text("home = x\n")
    assert agent_guard.classify("pip", ["install", "x"], real=str(venv / "pip")) is None
    assert agent_guard.classify("pip", ["install", "x"], real="/usr/bin/pip") == "system_install"


def test_deleting_outside_the_project_waits(tmp_path):
    root = tmp_path / "p"
    root.mkdir()
    assert agent_guard.classify("rm", ["-rf", "build"], root=str(root), cwd=str(root)) is None
    assert agent_guard.classify("rm", [str(Path.home() / "Documents")], root=str(root), cwd=str(root)) == "irreversible"
    assert agent_guard.classify("rm", [str(tmp_path / "scratch")], root=str(root), cwd=str(root)) is None   # the temp folder


def test_settings_default_to_asking_and_switch(home):
    assert agent_guard.permissions() == {c: True for c in agent_guard.CATEGORIES}
    agent_guard.set_permission("system_install", False)
    assert agent_guard.permissions()["system_install"] is False
    assert agent_guard.permissions()["irreversible"] is True
    with pytest.raises(ValueError):
        agent_guard.set_permission("everything", False)


def test_full_path_calls_are_found_in_the_output():
    out = "running /usr/bin/sudo apt-get install x\nand /opt/homebrew/bin/brew install y\nbrew is fine here"
    assert agent_guard.full_path_calls(out) == ["/opt/homebrew/bin/brew", "/usr/bin/sudo"]


@posix_only
def test_a_stand_in_refuses_records_and_passes_the_rest_through(home, tmp_path):
    root = _repo(tmp_path / "proj")
    log = tmp_path / "guard.jsonl"
    env = agent_guard.step_env(dict(os.environ), str(root), log)
    refused = subprocess.run(["sh", "-c", "brew install ffmpeg"], cwd=root, env=env, capture_output=True, text=True)
    assert refused.returncode == agent_guard.REFUSED_EXIT and "NOT run" in refused.stderr
    passed = subprocess.run(["sh", "-c", "git status --porcelain"], cwd=root, env=env, capture_output=True, text=True)
    assert passed.returncode == 0                                       # an ordinary command reaches the real git
    assert [r["command"] for r in agent_guard.requests(log)] == ["brew install ffmpeg"]
    allowed = agent_guard.step_env(dict(os.environ), str(root), log, allowed=["git push origin"])
    out = subprocess.run(["sh", "-c", "git push origin"], cwd=root, env=allowed, capture_output=True, text=True)
    assert "NOT run" not in out.stderr                                   # allowed: the real git ran (and failed: no remote)
    off = agent_guard.step_env(dict(os.environ), str(root), log, ask={c: False for c in agent_guard.CATEGORIES})
    out = subprocess.run(["sh", "-c", "git push origin"], cwd=root, env=off, capture_output=True, text=True)
    assert "NOT run" not in out.stderr


def test_agent_mode_scope_has_no_budgets_or_path_lists():
    order = _order()
    numstat = [(5, 0, "package.json"), (300, 0, "src/app.js"), (20, 0, "vite.config.js")]
    ok, violations = SafetyPolicy.validate_scope_post_build(order, numstat, ["index.html", "package-lock.json"])
    assert not ok and any("outside allowed_paths" in v for v in violations) and any("Dependency" in v for v in violations)
    ok, violations = SafetyPolicy.validate_scope_post_build(order, numstat, ["index.html", "package-lock.json"], agent_mode=True)
    assert ok, violations
    ok, violations = SafetyPolicy.validate_scope_post_build(_order(protected_paths=["tests/test_smoke.py"]),
                                                            [(1, 1, "tests/test_smoke.py"), (1, 0, ".git/config")], [], agent_mode=True)
    assert any("Protected path" in v for v in violations) and any("Control plane" in v for v in violations)


FAKE_CLI = """#!/bin/sh
case "$1" in --version) echo "fake 1.0"; exit 0;; esac
cat > /dev/null
mkdir -p src node_modules/left-pad
echo "module.exports = 1" > src/app.js
echo "x" > node_modules/left-pad/index.js
brew install ffmpeg 2>/dev/null
echo '{"summary":"made src/app.js","tests":"node --test","setup":"npm install","run":{"command":"","kind":"web","url":"","open":"index.html"}}'
"""


@posix_only
def test_the_agent_maker_works_in_the_worktree_and_reports_caught_commands(home, tmp_path):
    from agents.agent_maker import AgentMaker
    root = _repo(tmp_path / "proj")
    fake = tmp_path / "bin" / "fakecli"
    fake.parent.mkdir()
    fake.write_text(FAKE_CLI)
    fake.chmod(0o755)
    maker = AgentMaker(provider="codex", executable=str(fake), timeout=60, no_progress_timeout=60)
    maker.guard_log = str(tmp_path / "guard.jsonl")
    result = maker.run(_order(), str(root))
    assert result.status == "COMPLETED", result.error
    assert "src/app.js" in result.files_modified and ".gitignore" in result.files_modified
    assert not any(p.startswith("node_modules") for p in result.files_modified)       # kept out by .gitignore
    assert "node_modules/" in (root / ".gitignore").read_text()
    assert [r["command"] for r in maker.last_guard_requests] == ["brew install ffmpeg"]
    assert maker.last_execution_info["setup"] == "npm install" and maker.last_execution_info["mode"] == "agent"
    assert "--dangerously-bypass-approvals-and-sandbox" in maker.last_execution_info["invocation_command"]


@posix_only
def test_a_maker_that_changes_nothing_fails(home, tmp_path):
    from agents.agent_maker import AgentMaker
    root = _repo(tmp_path / "proj")
    fake = tmp_path / "fakecli"
    fake.write_text('#!/bin/sh\ncase "$1" in --version) echo 1; exit 0;; esac\ncat >/dev/null\necho \'{"summary":"nothing"}\'\n')
    fake.chmod(0o755)
    result = AgentMaker(provider="codex", executable=str(fake), timeout=60, no_progress_timeout=60).run(_order(), str(root))
    assert result.status == "FAILED" and result.error.startswith("MAKER_NO_CHANGES")


def test_the_report_is_read_from_a_claude_envelope():
    from agents.agent_maker import AgentMaker
    maker = AgentMaker.__new__(AgentMaker)
    inner = json.dumps({"summary": "done", "setup": ""})
    assert maker._report(json.dumps({"type": "result", "result": "```json\n" + inner + "\n```"}))["summary"] == "done"
    assert maker._report("I could not produce JSON")["summary"] == "I could not produce JSON"


def test_agent_cli_arguments_open_the_permissions(monkeypatch):
    monkeypatch.setenv("DIRECTOR_TESTING", "1")
    from core import cli_models
    assert "--dangerously-bypass-approvals-and-sandbox" in cli_models.codex_agent_argv("codex")
    assert "--sandbox" not in cli_models.codex_agent_argv("codex")
    claude = cli_models.claude_agent_argv("claude", '{"env":{}}')
    assert claude[claude.index("--permission-mode") + 1] == "bypassPermissions" and "--tools" not in claude
    assert "--dangerously-skip-permissions" in cli_models.agy_agent_argv("agy") and "--sandbox" not in cli_models.agy_agent_argv("agy")


def test_project_setup_installs_inside_the_project(tmp_path):
    from core import project_setup
    root = tmp_path / "p"
    (root / "tests").mkdir(parents=True)
    (root / "requirements.txt").write_text("requests\n")
    (root / "tests" / "test_a.py").write_text("def test_a(): pass\n")
    (root / "package.json").write_text(json.dumps({"dependencies": {"left-pad": "1"}}))
    (root / "package-lock.json").write_text("{}")
    steps = project_setup.steps(root)
    assert steps[0][1:] == ["-m", "venv", ".venv"]
    assert steps[1][-2:] == ["-r", "requirements.txt"] and steps[2][-1] == "pytest"
    assert any(Path(s[0]).name.startswith("npm") and s[1] == "ci" for s in steps) or not __import__("shutil").which("npm")
    (root / "node_modules").mkdir()
    assert not any(len(s) > 1 and s[1] in ("ci", "install") and Path(s[0]).name.startswith("npm") for s in project_setup.steps(root))
    assert project_setup.steps(tmp_path / "empty") == []


def test_the_working_copy_environment_comes_first(tmp_path):
    from core import pythons
    project = tmp_path / "proj"
    wt = project / ".director_worktrees" / "RUN-1"
    names = ("Scripts", "python.exe") if os.name == "nt" else ("bin", "python")
    for where in (project, wt):
        exe = where / ".venv" / names[0] / names[1]
        exe.parent.mkdir(parents=True)
        exe.write_text("")
    assert pythons.project_python(wt) == str(wt / ".venv" / names[0] / names[1])
    assert pythons.project_python(project) == str(project / ".venv" / names[0] / names[1])


@pytest.mark.parametrize("name,args,expected", [
    ("pip", ["install", "--prefix", "/opt/homebrew", "x"], "system_install"),
    ("pip", ["install", "--prefix", "vendor", "x"], None),
    ("npm", ["install", "--location", "global", "x"], "system_install"),
    ("npm", ["link"], "system_install"),
    ("python3", ["-mpip", "install", "x"], "system_install"),
    ("python3.12", ["-m", "pip", "install", "x"], "system_install"),
    ("pip3.12", ["install", "x"], "system_install"),
    ("gh", ["auth", "status", "--show-token"], "money_credentials"),
    ("uv", ["tool", "install", "ruff"], "system_install"),
    ("uv", ["pip", "install", "x"], None),
    ("uv", ["pip", "install", "--system", "x"], "system_install"),
    ("brew", ["list"], None),
    ("brew", ["--prefix"], None),
])
def test_critic_found_ways_around_the_guard(name, args, expected, tmp_path):
    """critic (2026-11-26): each of these got past classify, or stopped a read-only command."""
    assert agent_guard.classify(name, args, root=str(tmp_path), cwd=str(tmp_path)) == expected


@posix_only
@pytest.mark.skipif(not __import__("shutil").which("zsh"), reason="no zsh")
def test_a_login_shell_still_finds_the_stand_ins_first(home, tmp_path):
    """critic: zsh -lc reads the profile, where path_helper and brew shellenv put /usr/bin back in front."""
    root = _repo(tmp_path / "proj")
    env = agent_guard.step_env(dict(os.environ), str(root), tmp_path / "g.jsonl")
    for shell in (["zsh", "-lc"], ["bash", "-lc"]):
        out = subprocess.run(shell + ["command -v git"], cwd=root, env=env, capture_output=True, text=True)
        assert out.stdout.strip() == str(Path(env["TRIBUNAL_GUARD_BIN"]) / "git"), shell


def test_a_commit_made_by_the_maker_is_undone_but_its_files_stay(tmp_path):
    """critic: committed changes would pass every check (they compare with HEAD) while apply still copied them."""
    from agents.agent_maker import changed_paths, head_of, undo_commits
    root = _repo(tmp_path / "proj")
    before = head_of(root)
    (root / "a.py").write_text("x = 1\n")
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "sneaky")
    assert changed_paths(root) == [] and undo_commits(root, before)
    assert head_of(root) == before and changed_paths(root) == ["a.py"] and (root / "a.py").read_text() == "x = 1\n"
    assert not undo_commits(root, before)


def test_applying_does_not_run_node_tests_the_run_never_ran(tmp_path, monkeypatch):
    import shutil
    from core.verifier import Verifier
    monkeypatch.setattr(shutil, "which", lambda name: f"/bin/{name}")
    (tmp_path / "package.json").write_text(json.dumps({"scripts": {"test": "jest"}, "devDependencies": {"jest": "1"}}))
    (tmp_path / "node_modules").mkdir()
    out = Verifier.verify(str(tmp_path), test_cmd=None, git_checks=False, node_tests=False)
    assert (out.get("node_tests") or {}).get("command") is None
