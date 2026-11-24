"""core/pythons.py: Tribunal's own helpers and the project's tests no longer share one interpreter by accident
(docs/PACKAGING.md 4절)."""
import sys
from pathlib import Path

from core import pythons


def _venv(root: Path) -> Path:
    py = root / ".venv" / ("Scripts" if sys.platform == "win32" else "bin") / ("python.exe" if sys.platform == "win32" else "python")
    py.parent.mkdir(parents=True)
    py.write_text("")
    return py


def test_a_projects_tests_run_in_its_own_environment_when_it_can(tmp_path, monkeypatch):
    assert pythons.project_python(tmp_path) == sys.executable                  # no environment: Tribunal's, as before
    py = _venv(tmp_path)
    assert pythons.project_venv_python(tmp_path) == str(py)
    monkeypatch.setattr(pythons, "has_module", lambda python, module: True)
    assert pythons.project_python(tmp_path, needs="pytest") == str(py)
    monkeypatch.setattr(pythons, "has_module", lambda python, module: False)    # its environment has no pytest
    assert pythons.project_python(tmp_path, needs="pytest") == sys.executable


def test_the_verifier_uses_the_projects_environment_for_python_commands(tmp_path, monkeypatch):
    from core.verifier import Verifier
    from core import process_runner
    seen = []

    def fake_run(argv, **kw):
        seen.append(argv)
        return process_runner.ProcessResult(exit_code=0, stdout="1 passed", stderr="", duration_sec=0.1, timed_out=False) \
            if hasattr(process_runner, "ProcessResult") else None
    monkeypatch.setattr(process_runner.ProcessTreeRunner, "run", staticmethod(fake_run))
    py = _venv(tmp_path)
    monkeypatch.setattr(pythons, "has_module", lambda python, module: module == "pytest")
    try:
        Verifier._execute_cmd("python -m pytest -q", tmp_path)
    except Exception:
        pass                                                                    # only the command line matters here
    assert seen and seen[0][0] == str(py) and seen[0][1:] == ["-m", "pytest", "-q"]


def test_the_maker_is_told_the_projects_python_not_tribunals():
    src = (Path(__file__).resolve().parents[1] / "agents" / "proposal_maker.py").read_text(encoding="utf-8")
    assert "\"The project's Python is \" + self._project_python_version(root)" in src
    assert "Tribunal host Python" not in src


def test_tribunals_own_helpers_use_its_interpreter():
    assert pythons.tribunal_python() == sys.executable
    for rel in ("companion_server.py", "core/role_checks.py", "agents/antigravity_maker.py"):
        src = (Path(__file__).resolve().parents[1] / rel).read_text(encoding="utf-8")
        assert "tribunal_python()" in src and "sys.executable" not in src.replace("tribunal_python", ""), rel


def test_every_check_of_a_run_uses_the_projects_environment(tmp_path, monkeypatch):
    """critic: the working copy has no .venv (git does not track it), so the rounds ran on Tribunal's Python and only
    the apply on the project's - a pass could turn into a rollback. The working copy now points at its project."""
    proj = tmp_path / "proj"
    py = _venv(proj)
    wt = proj / ".director_worktrees" / "RUN-1"
    wt.mkdir(parents=True)
    monkeypatch.setattr(pythons, "has_module", lambda python, module: True)
    assert pythons.original_project(wt / "src") == proj.resolve()
    assert pythons.project_python(wt, needs="pytest") == str(proj.resolve() / py.relative_to(proj))
    copy = tmp_path / "inspector-copy"                              # the inspector's throw-away copy: told where it came from
    copy.mkdir()
    assert pythons.project_python(copy) == sys.executable
    from core.verifier import Verifier
    from core import process_runner
    seen = []
    monkeypatch.setattr(process_runner.ProcessTreeRunner, "run", staticmethod(lambda argv, **kw: seen.append(argv)))
    for cmd in ("python -m pytest -q", "python -B -m pytest", "python3 -mpytest"):
        try:
            Verifier._execute_cmd(cmd, copy, python_root=str(wt))
        except Exception:
            pass
    assert [a[0] for a in seen] == [str(proj.resolve() / py.relative_to(proj))] * 3
    src = (Path(__file__).resolve().parents[1] / "core" / "inspector_tests.py").read_text(encoding="utf-8")
    assert "python_root=str(worktree_path or sandbox)" in src


def test_the_module_named_after_dash_m_is_the_one_checked(tmp_path, monkeypatch):
    from core.verifier import Verifier
    from core import process_runner
    _venv(tmp_path)
    asked = []
    monkeypatch.setattr(pythons, "has_module", lambda python, module: asked.append(module) or False)
    monkeypatch.setattr(process_runner.ProcessTreeRunner, "run", staticmethod(lambda argv, **kw: None))
    for cmd in ("python -u -m pytest", "python -mpytest -q", "python run.py -m x"):
        try:
            Verifier._execute_cmd(cmd, tmp_path)
        except Exception:
            pass
    assert asked == ["pytest", "pytest"]                            # a script's own -m is not Python's


def test_a_missing_module_is_asked_again(monkeypatch):
    calls = []
    import subprocess
    monkeypatch.setattr(pythons.subprocess, "run", lambda *a, **k: calls.append(1) or subprocess.CompletedProcess(a, 1))
    pythons._MODULE.pop(("/x/python", "pytest"), None)
    assert not pythons.has_module("/x/python", "pytest") and not pythons.has_module("/x/python", "pytest")
    assert len(calls) == 2                                          # installed later: seen without a restart
