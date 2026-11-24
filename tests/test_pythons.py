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
