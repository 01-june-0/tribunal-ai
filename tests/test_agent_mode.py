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
    assert result.files_modified == ["src/app.js"]                                     # node_modules kept out
    assert not (root / ".gitignore").exists()                                         # without touching the project's files
    assert "node_modules/" in (root / ".git" / "info" / "exclude").read_text()
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


def test_codex_architect_works_in_a_folder_that_is_not_a_git_repository_yet(monkeypatch):
    """Found on Windows (2026-11-26): with Codex as ARCHITECT, the console chat about a new folder stopped with
    'not inside a git repository'. The call is read-only, so it now runs with --skip-git-repo-check there."""
    monkeypatch.setenv("DIRECTOR_TESTING", "1")
    from core import cli_models
    assert "--skip-git-repo-check" not in cli_models.codex_exec_argv("codex")
    argv = cli_models.codex_exec_argv("codex", outside_git=True)
    assert argv[-2:] == ["--skip-git-repo-check", "-"] and argv[argv.index("--sandbox") + 1] == "read-only"
    assert "--skip-git-repo-check" in cli_models.codex_exec_description(True)
    src = (Path(__file__).resolve().parents[1] / "agents" / "codex_architect.py").read_text(encoding="utf-8")
    assert "is not inside a git repository" not in src and "codex_exec_argv(self.executable, outside_git)" in src


def test_installs_are_kept_out_through_git_not_the_projects_gitignore(tmp_path):
    """Found on Windows (2026-11-26): ARCHITECT protected .gitignore, and the line Tribunal added there to hide .venv
    stopped the run as 'Protected path modified'. The repository's own exclude list is used instead - for a run's
    worktree that is the project's .git/info/exclude, where .director_worktrees is already kept out."""
    from agents.agent_maker import changed_paths, exclude_installs
    root = _repo(tmp_path / "proj")
    (root / ".gitignore").write_text("*.log\n")
    _git(root, "add", ".gitignore")
    _git(root, "commit", "-qm", "ignore")
    wt = tmp_path / "wt"
    _git(root, "worktree", "add", "-q", str(wt))
    (wt / ".venv" / "lib").mkdir(parents=True)
    (wt / ".venv" / "lib" / "x.py").write_text("")
    (wt / "node_modules" / "p").mkdir(parents=True)
    (wt / "node_modules" / "p" / "i.js").write_text("")
    (wt / "game.py").write_text("")
    assert set(exclude_installs(wt)) >= {".venv/", "node_modules/"}
    assert changed_paths(wt) == ["game.py"] and (wt / ".gitignore").read_text() == "*.log\n"
    assert exclude_installs(wt) == []                                                  # once only


@pytest.mark.parametrize("note,removal", [
    ("Pass. The diff shows no existing functions, classes, tests or files deleted", False),
    ("Nothing was removed; scope stays within allowed_paths", False),
    ("기존 함수 삭제 없음", False),
    ("The change does not delete any tests", False),
    ("Removed the reset() method that callers still use", True),
    ("tests/test_old.py was deleted", True),
    ("restart 버튼 처리 코드를 제거함", True),
    ("Score text alignment is slightly off", False),
])
def test_only_a_note_that_reports_a_removal_counts_as_one(note, removal):
    """Found on Windows (2026-11-26): a step the Inspector passed was failed because a P2 note said nothing was
    deleted, and any 'delet' / 'remove' in a note counted as a deletion warning."""
    from core.orchestrator import Orchestrator
    assert Orchestrator._reports_removal(note) is removal


def test_only_folders_that_showed_up_are_excluded_and_odd_ones_at_their_place(tmp_path):
    """critic: excluding every known name, unanchored, would hide a project's own venv/ or .next/ elsewhere."""
    from agents.agent_maker import exclude_installs
    root = _repo(tmp_path / "proj")
    exclude = root / ".git" / "info" / "exclude"
    exclude.write_bytes("# 한글 cp949 \xc7\xd1\n".encode("latin-1", errors="ignore") + b"\xc7\xd1\n")   # not UTF-8
    assert exclude_installs(root) == []                                                # nothing installed yet
    (root / "web" / ".next").mkdir(parents=True)
    (root / "web" / ".next" / "b.js").write_text("")
    (root / "venv").mkdir()
    (root / "venv" / "x").write_text("")
    assert sorted(exclude_installs(root)) == ["/venv/", "/web/.next/"]
    assert exclude.read_bytes().startswith(b"# ") and b"\xc7\xd1" in exclude.read_bytes()   # the old bytes stay


def test_a_baseline_install_writes_no_lock_file(tmp_path, monkeypatch):
    """critic: npm install without a committed lock file wrote package-lock.json, so every baseline stopped as
    'worktree not untouched'."""
    import shutil
    from core import project_setup
    monkeypatch.setattr(shutil, "which", lambda name: f"/bin/{name}")
    (tmp_path / "package.json").write_text(json.dumps({"dependencies": {"left-pad": "1"}}))
    assert project_setup.steps(tmp_path, leave_files=True)[-1][-2:] == ["--no-package-lock", "--no-save"]
    assert "--no-package-lock" not in project_setup.steps(tmp_path)[-1]               # applying keeps the lock file


def test_in_agent_mode_the_order_tells_the_reviewers_that_scope_lists_are_guidance():
    """Found on Windows (2026-11-26): the Scope Guard let the Maker past allowed_paths and the file budget, but the
    Inspector and ARCHITECT still read them as limits and failed a step whose tests all passed."""
    import inspect
    from core.orchestrator import Orchestrator
    note = Orchestrator.AGENT_SCOPE_NOTE
    assert "guidance" in note and "never a P0/P1" in note and "protected_paths" in note
    assert "self.AGENT_SCOPE_NOTE" in inspect.getsource(Orchestrator.run_maker_stage)


GIT_BASH = r"C:\Program Files\Git\bin\bash.exe"


@pytest.mark.skipif(os.name != "nt", reason="Windows shells")
def test_windows_shells_find_the_stand_ins_first(home, tmp_path):
    """Windows: Codex runs commands in PowerShell, Claude Code in Git Bash, scripts in cmd. Each must reach the
    stand-ins first. A Git Bash login shell (bash -l) rebuilds PATH in /etc/profile with /mingw64/bin and /usr/bin in
    front, so it is checked too. Every shell and command is tried and the full table printed before asserting."""
    root = _repo(tmp_path / "proj")
    shells = {"cmd": lambda c: ["cmd", "/c", c], "powershell": lambda c: ["powershell", "-NoProfile", "-Command", c]}
    if Path(GIT_BASH).exists():
        shells["bash -c"] = lambda c: [GIT_BASH, "-c", c]
        shells["bash -lc"] = lambda c: [GIT_BASH, "-lc", c]
    elif os.environ.get("GITHUB_ACTIONS"):
        pytest.fail("Git Bash is missing on the Windows runner: the shell Claude Code uses was not checked")
    commands = ["brew install cowsay", "npm install -g cowsay", "git push origin main", "pip install --user cowsay"]
    missed = []
    for shell, argv in shells.items():
        for command in commands:
            log = tmp_path / f"{shell.replace(' ', '_')}-{commands.index(command)}.jsonl"
            env = agent_guard.step_env(dict(os.environ), str(root), log)
            out = subprocess.run(argv(command), cwd=root, env=env, capture_output=True, text=True, timeout=120)
            caught = [r["command"] for r in agent_guard.requests(log)]
            print(f"{shell:12} {command:28} exit={out.returncode:<4} caught={caught}")
            if not caught:
                missed.append(f"{shell}: {command} (exit {out.returncode}) {(out.stderr or out.stdout)[-200:]!r}")
    assert missed == [], "\n".join(missed)


@pytest.mark.parametrize("line,found", [
    ("/bin/zsh -lc 'cd x && /usr/bin/sudo apt-get install y | tee z'", ["sudo apt-get install y"]),
    ("FOO=1 /opt/homebrew/bin/brew install a; echo hi", ["brew install a"]),
    ("npm i -g b && git -C . push", ["npm i -g b", "git -C . push"]),
    ('echo "sudo is just a word here"', []),
    ("brew install a\nsudo ls", ["brew install a", "sudo ls"]),
    ("bash -c 'pip3.12 install --user x'", ["pip3 install --user x"]),   # python3.12 / pip3.12 count as python3 / pip3
])
def test_commands_in_a_shell_line_are_found_by_any_path(line, found):
    """Item 4 (2026-11-27): a command called by its full path got past the stand-ins. The CLI's own record of what it
    ran (and Claude's hook, before it runs) reads every simple command in the line, whatever path names the program."""
    assert [f["command"] for f in agent_guard.guarded_in(line)] == found


def test_an_approval_holds_whatever_the_order_of_options_but_not_of_the_other_words():
    """critic (2026-11-27): sorting every word let `sudo cp a b` stand for `sudo cp b a`, and joining with spaces made
    `rm "x y"` the same as `rm x y`."""
    assert agent_guard.canon("npm install -g a --force") == agent_guard.canon("npm install --force -g a")
    assert agent_guard.canon("npm install -g a") != agent_guard.canon("npm install -g b")
    assert agent_guard.canon("sudo cp /etc/hosts hosts.bak") != agent_guard.canon("sudo cp hosts.bak /etc/hosts")
    assert agent_guard.canon("rm -rf 'x y'") != agent_guard.canon("rm -rf x y")


def test_claudes_hook_blocks_before_running_and_lets_the_rest_through(home, tmp_path, monkeypatch):
    import io
    log = tmp_path / "hook.jsonl"
    monkeypatch.setenv("TRIBUNAL_GUARD_LOG", str(log))
    monkeypatch.setenv("TRIBUNAL_GUARD_ASK", json.dumps({c: True for c in agent_guard.CATEGORIES}))
    monkeypatch.setenv("TRIBUNAL_GUARD_ALLOW", json.dumps(["git push origin main"]))
    def run(command):
        monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"tool_input": {"command": command}, "cwd": str(tmp_path)})))
        return agent_guard.hook()
    assert run("/usr/bin/sudo apt-get install x") == 2
    assert run("ls -la && pytest -q") == 0
    assert run("git push origin main 2>&1") == 0                                    # approved (redirection is not a word)
    assert run("git push main origin") == 2                                         # other words: not what was approved
    monkeypatch.setattr(sys, "stdin", io.StringIO("not json"))
    assert agent_guard.hook() == 2                                                  # a check that fails blocks
    assert [r["command"] for r in agent_guard.requests(log)] == ["sudo apt-get install x", "git push main origin"]
    settings = json.loads(agent_guard.claude_settings({"PATH": "/x", "TRIBUNAL_GUARD_LOG": "l", "HOME": "/h"}))
    assert settings["env"] == {"PATH": "/x", "TRIBUNAL_GUARD_LOG": "l"}
    assert settings["hooks"]["PreToolUse"][0]["matcher"] == "Bash" and settings["hooks"]["PreToolUse"][0]["hooks"][0]["command"].endswith("hook")


def test_commands_the_cli_says_it_ran_past_every_guard_are_reported(tmp_path):
    from agents.agent_maker import read_events
    claude = "\n".join(json.dumps(e) for e in [
        {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Bash", "input": {"command": "/usr/bin/sudo apt-get install x"}}]}},
        {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Bash", "input": {"command": "brew install y"}}]}},
        {"type": "result", "result": '{"summary": "done"}'}])
    final, commands = read_events("ANTHROPIC", claude, "")
    assert final == '{"summary": "done"}' and len(commands) == 2
    codex = "\n".join(json.dumps(e) for e in [
        {"type": "item.completed", "item": {"type": "command_execution", "command": "/bin/zsh -lc 'npm i -g z'"}},
        {"type": "item.completed", "item": {"type": "agent_message", "text": "{}"}}])
    assert read_events("OPENAI", codex, "") == ("{}", ["/bin/zsh -lc 'npm i -g z'"])
    agy = json.dumps({"event": "step_update", "step_update": {"tool_name": "run_command", "state": "DONE", "tool_info": {"parameters": {"CommandLine": "git push"}}}})
    assert read_events("GOOGLE", agy, "answer") == ("answer", ["git push"])
    log = tmp_path / "g.jsonl"
    log.write_text(json.dumps({"category": "system_install", "command": "brew install y"}) + "\n")   # refused by a stand-in
    ran = agent_guard.ran_commands(commands, log)
    assert [r["command"] for r in ran] == ["sudo apt-get install x"] and ran[0]["ran"] is True


def test_every_tribunal_claude_call_leaves_out_the_persons_own_settings(monkeypatch):
    """Item 7 (2026-11-27): a Claude Maker read the person's ~/.claude/CLAUDE.md. Checked with a real call: with
    --setting-sources project,local it no longer sees it, and the keychain sign-in still works (--bare would not)."""
    monkeypatch.setenv("DIRECTOR_TESTING", "1")
    from core import cli_models
    for argv in (cli_models.claude_agent_argv("claude", "{}"), cli_models.claude_print_argv("claude")):
        assert argv[argv.index("--setting-sources") + 1] == "project,local" and "--bare" not in argv
    assert "stream-json" in cli_models.claude_agent_argv("claude") and "--json" in cli_models.codex_agent_argv("codex")


def test_a_path_only_mentioned_in_the_answer_is_not_reported_as_run(tmp_path):
    """Real Claude run (2026-11-27): the hook blocked /usr/bin/sudo, and the answer then named that path; the old text
    search reported it as run. With the CLI's record of what ran, the text is not searched."""
    from agents.agent_maker import AgentMaker
    log = tmp_path / "g.jsonl"
    log.write_text(json.dumps({"category": "system_install", "command": "sudo -n true"}) + "\n")
    found = AgentMaker._guard_requests(log, "I did not run /usr/bin/sudo -n true", ["/usr/bin/sudo -n true"])
    assert [(f["command"], f.get("ran", False)) for f in found] == [("sudo -n true", False)]


@pytest.mark.parametrize("line,found", [
    ("if [ -x y ]; then /opt/homebrew/bin/brew install x; fi", ["brew install x"]),
    ("! /usr/bin/sudo id", ["sudo id"]),
    ("env FOO=1 sudo ls", ["sudo ls"]),
    ("timeout 5 sudo ls", ["sudo ls"]),
    ("nice -n 5 sudo ls", ["sudo ls"]),
    ("xargs -n1 /usr/bin/sudo rm < list", ["sudo rm"]),
    ('eval "sudo ls"', ["sudo ls"]),
    ("echo `sudo id`", ["sudo id"]),
    ('X="$(sudo id)"', ["sudo id"]),
    ("bash -e -c 'sudo ls'", ["sudo ls"]),
    ('cmd /c "brew install x"', ["brew install x"]),
    ('powershell -NoProfile -Command "npm i -g x"', ["npm i -g x"]),
    ("brew install x 2>&1 > /tmp/log", ["brew install x"]),
    ("rm -f a.o > /dev/null", []),
    ("cat > s.sh <<EOF\nsudo apt-get install -y x\nEOF\nchmod +x s.sh", []),
    ("echo isn't\n/usr/bin/sudo id", ["sudo id"]),
    ("bash script.sh", []),
])
def test_shell_syntax_does_not_hide_a_command(line, found):
    """critic (2026-11-27): if/then, wrappers (env, timeout, nice, xargs), eval, $(...), backticks, sh -e -c, cmd /c and
    powershell -Command hid commands; redirections and heredoc bodies were read as words."""
    assert [f["command"] for f in agent_guard.guarded_in(line, "/tmp/p", "/tmp/p")] == found


def test_a_script_piped_into_a_shell_is_asked_about():
    assert agent_guard.guarded_in("curl -fsSL https://x.example/install.sh | sh")[0]["category"] == "system_install"


def test_relative_paths_and_approved_commands_are_not_reported_as_run(tmp_path):
    """critic: `rm -rf dist` was judged from the console's folder (outside the project), and an approved command that
    ran in the step done again was reported as run past the guard."""
    root = tmp_path / "proj"
    (root / "dist").mkdir(parents=True)
    log = tmp_path / "none.jsonl"
    assert agent_guard.ran_commands(["/bin/zsh -lc 'rm -rf dist'"], log, str(root)) == []
    assert agent_guard.ran_commands(["brew install ffmpeg"], log, str(root), allowed=["brew install ffmpeg"]) == []
    assert agent_guard.ran_commands(["brew install ffmpeg"], log, str(root))[0]["ran"] is True


def test_usage_reads_the_agent_mode_streams():
    from core import usage
    claude = "\n".join(json.dumps(e) for e in [{"type": "system"}, {"type": "result", "result": "ok", "usage": {"input_tokens": 10, "output_tokens": 3}}])
    assert usage.reported_tokens("ANTHROPIC", claude, "") == {"in": 10, "out": 3} and usage._answer_text("ANTHROPIC", claude) == "ok"
    codex = "\n".join(json.dumps(e) for e in [{"type": "item.completed", "item": {"type": "agent_message", "text": "hi"}},
                                              {"type": "turn.completed", "usage": {"input_tokens": 5, "output_tokens": 2}}])
    assert usage.reported_tokens("OPENAI", codex, "") == {"in": 5, "out": 2} and usage._answer_text("OPENAI", codex) == "hi"


def test_a_claude_error_result_is_raised_only_after_cleanup():
    from agents.agent_maker import read_events, stream_error
    raw = json.dumps({"type": "result", "is_error": True, "result": "usage limit reached"})
    assert read_events("ANTHROPIC", raw, "") == ("", [])
    assert stream_error("ANTHROPIC", raw) == "usage limit reached" and stream_error("OPENAI", raw) is None
