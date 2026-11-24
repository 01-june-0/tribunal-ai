"""core/run_preview.py: "실행해 보기" - how a finished result is started, and that only the plan shown is started.

Nothing here opens a terminal or a browser: the launcher is replaced in every test that starts something."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from core import run_preview as rp

PY = rp._python(Path('.no-venv-here'))          # what a bare Python is called here: python3, or python on Windows


def test_the_maker_run_field_is_kept_only_when_safe():
    ok = rp.clean_spec({"command": "npm run dev", "kind": "web", "url": "http://localhost:5173/", "open": ""})
    assert ok == {"command": "npm run dev", "kind": "web", "url": "http://localhost:5173/", "open": ""}
    assert rp.clean_spec({"command": "a\nrm -rf ~"}) is None                       # one line only
    assert rp.clean_spec({"command": "x" * 301}) is None
    assert rp.clean_spec({"command": "", "open": "../outside.html"}) is None        # nothing usable left
    assert rp.clean_spec({"open": "web/index.html"}) == {"command": "", "kind": "web", "url": "", "open": "web/index.html"}
    assert rp.clean_spec({"command": "python3 app.py", "url": "http://evil.example/"})["url"] == ""   # only local pages
    assert rp.clean_spec({"command": "python3 app.py", "kind": "rocket"})["kind"] == "terminal"
    assert rp.clean_spec({"open": "Tool.app"}) is None and rp.clean_spec("npm start") is None


def _write(root: Path, files: dict) -> Path:
    for rel, text in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text, encoding="utf-8")
    return root


def test_guessing_from_the_files(tmp_path):
    web = _write(tmp_path / "web", {"package.json": json.dumps({"scripts": {"dev": "vite", "test": "vitest"}})})
    assert rp.guess(web) == {"command": "npm install && npm run dev", "kind": "web", "url": "", "open": ""}
    (web / "node_modules").mkdir()
    assert rp.guess(web)["command"] == "npm run dev"
    app = _write(tmp_path / "app", {"package.json": json.dumps({"scripts": {"start": "electron ."}, "devDependencies": {"electron": "1"}})})
    assert rp.guess(app)["kind"] == "gui" and rp.guess(app)["command"].endswith("npm start")
    page = _write(tmp_path / "page", {"public/index.html": "<h1>hi</h1>"})
    assert rp.guess(page) == {"command": "", "kind": "web", "url": "", "open": "public/index.html"}
    gui = _write(tmp_path / "gui", {"src/mines.py": "import tkinter\nif __name__ == '__main__':\n    pass\n",
                                    "src/util.py": "x = 1\n", "tests/test_mines.py": "if __name__ == '__main__': pass\n"})
    assert rp.guess(gui) == {"command": f"{PY} -m src.mines", "kind": "gui", "url": "", "open": ""}
    cli = _write(tmp_path / "cli", {"main.py": "def main(): pass\nif __name__ == \"__main__\":\n    main()\n"})
    assert rp.guess(cli) == {"command": f"{PY} main.py", "kind": "terminal", "url": "", "open": ""}
    import os
    rel = (".venv", "Scripts", "python.exe") if os.name == "nt" else (".venv", "bin", "python")
    (cli.joinpath(*rel[:-1])).mkdir(parents=True); cli.joinpath(*rel).write_text("")
    sep = "\\" if os.name == "nt" else "/"
    assert rp.guess(cli)["command"] == sep.join(rel) + " main.py"                  # the project's own environment
    assert rp.guess(_write(tmp_path / "lib", {"src/calc.py": "def add(a, b):\n    return a + b\n"})) is None


class _RM:
    """Just enough of ResultManager for plan()."""
    def __init__(self, tmp, state="READY", run_state="PASS", worktree=True):
        self.base = tmp
        self.project = _write(tmp / "proj", {"README.md": "x"}); (self.project / ".git").mkdir(exist_ok=True)
        self.wt = self.project / ".director_worktrees" / "RUN-1"
        if worktree:
            _write(self.wt, {"main.py": "if __name__ == '__main__':\n    print('hi')\n"})
        self.state = state
        self.sm = SimpleNamespace(get_run=lambda rid: {"current_state": run_state, "project_path": str(self.project),
                                                        "worktree_path": str(self.wt)})
        self.runs = tmp / "runs"

    def result_state(self, run_id): return {"state": self.state}
    def builds_on(self, run_id): return ["RUN-0"]
    def run_dir(self, run_id): return self.runs / run_id
    def worktree_contained(self, project, wt): return str(wt).startswith(str(Path(project) / ".director_worktrees"))


def test_the_plan_runs_a_waiting_result_in_a_copy_and_an_applied_one_in_the_project(tmp_path):
    rm = _RM(tmp_path)
    p = rp.plan("RUN-1", rm=rm)
    assert p["found"] and p["where"] == "copy" and p["command"] == f"{PY} main.py" and p["source"] == "guess"
    _write(rm.runs / "RUN-0", {"maker.json": json.dumps({"run": {"command": "python3 main.py --big", "kind": "gui"}})})
    assert rp.plan("RUN-1", rm=rm)["command"] == "python3 main.py --big"           # an earlier step said how
    _write(rm.runs / "RUN-1", {"maker.json": json.dumps({"run": None})})
    assert rp.plan("RUN-1", rm=rm)["source"] == "maker"
    rm.state = "APPLIED"
    _write(rm.project, {"index.html": "<p>"})
    assert rp.plan("RUN-1", rm=rm)["where"] == "project"
    rm.state = "DISCARDED"
    assert rp.plan("RUN-1", rm=rm) == {"found": False, "reason": "discarded"}
    assert rp.plan("RUN-1", rm=_RM(tmp_path / "b", run_state="FAIL"))["found"] is False
    assert rp.plan("RUN-1", rm=_RM(tmp_path / "c", worktree=False))["reason"] == "worktree missing"


def test_a_static_page_is_served_on_a_free_local_port(tmp_path):
    rm = _RM(tmp_path)
    (rm.wt / "main.py").unlink(); _write(rm.wt, {"index.html": "<p>hi</p>"})
    p = rp.plan("RUN-1", rm=rm)
    assert p["command"] == f"{PY} -m http.server --bind 127.0.0.1 <port>" and p["open"] == "index.html"
    seen = []
    out = rp.start("RUN-1", p["command"], launcher=lambda rid, folder, command, page: seen.append((folder, command, page)) or True, rm=rm)
    folder, command, page = seen[0]
    port = command.rsplit(" ", 1)[1]
    assert out["status"] == "started" and port.isdigit() and page == f"http://127.0.0.1:{port}/index.html"
    assert folder != rm.wt and (folder / "index.html").is_file() and not (folder / ".git").exists()   # a copy


def test_only_the_plan_that_was_shown_starts(tmp_path):
    rm = _RM(tmp_path)
    started = []
    launcher = lambda *a: started.append(a) or True
    assert rp.start("RUN-1", "rm -rf ~", launcher=launcher, rm=rm)["status"] == "stale" and started == []
    out = rp.start("RUN-1", f"{PY} main.py", launcher=launcher, rm=rm)
    assert out["status"] == "started" and out["where"] == "copy"
    copy = Path(out["folder"])
    assert copy != rm.wt and (copy / "main.py").is_file()
    (copy / "save.dat").write_text("x")                                            # what the program writes
    assert not (rm.wt / "save.dat").exists()                                        # never reaches the result
    assert rp.start("RUN-1", f"{PY} main.py", launcher=lambda *a: False, rm=rm)["status"] == "manual"
    rm.state = "DISCARDED"
    assert rp.start("RUN-1", f"{PY} main.py", launcher=launcher, rm=rm)["status"] == "refused"


def test_the_terminal_script_runs_the_command_as_shown_and_waits(tmp_path):
    text = rp.posix_script(tmp_path / "my proj", "npm run dev", "http://127.0.0.1:5173/")
    lines = text.splitlines()
    assert lines[2] == f"cd '{tmp_path / 'my proj'}' || exit 1" and "npm run dev" in lines
    assert any(l.startswith("( sleep 3;") and "http://127.0.0.1:5173/" in l for l in lines) and lines[-1] == "read _"
    win = rp.windows_script(Path("C:/w/p"), "npm start", "")
    assert f'cd /d "{Path("C:/w/p")}"' in win and "npm start" in win and win.rstrip().endswith("pause")


def test_the_maker_reply_carries_the_run_field():
    src = (Path(__file__).resolve().parents[1] / "agents" / "proposal_maker.py").read_text(encoding="utf-8")
    assert '"run":{"command":"one shell line' in src and "run=clean_spec(proposal.get('run'))" in src


def test_guessing_stays_away_from_scripts_docs_and_odd_names(tmp_path):
    """critic: a scripts/ helper or a docs site must not be taken for the program; a broken package.json must not
    break the plan; a folder name a shell would read differently is never put into a command."""
    proj = _write(tmp_path / "p", {"scripts/reset_db.py": "if __name__ == '__main__':\n    drop()\n",
                                   "docs/index.html": "<p>docs</p>",
                                   "src/game_cli.py": "if __name__ == '__main__':\n    play()\n",
                                   "src/aaa_helper.py": "if __name__ == '__main__':\n    pass\n"})
    assert rp.guess(proj)["command"] == f"{PY} -m src.game_cli"                   # an entry-point name first
    assert rp.guess(_write(tmp_path / "d", {"docs/index.html": "<p>", "scripts/x.py": "if __name__ == '__main__': pass\n"})) is None
    assert rp.guess(_write(tmp_path / "j", {"package.json": "[]", "main.py": "if __name__ == '__main__': pass\n"}))["command"] == f"{PY} main.py"
    assert rp.guess(_write(tmp_path / "s", {"my app/run.py": "if __name__ == '__main__': pass\n"})) is None
    deep = _write(tmp_path / "n", {"node_modules/pkg/cli.py": "if __name__ == '__main__': pass\n",
                                   "a/b/c/main2.py": "if __name__ == '__main__': pass\n"})
    assert rp.guess(deep) is None                                                   # not inside dependencies, not deep down


def test_a_plan_that_moved_to_another_place_is_not_started(tmp_path):
    """Shown as "a temporary copy", applied meanwhile: it would run in the project now, so it is refused."""
    rm = _RM(tmp_path)
    p = rp.plan("RUN-1", rm=rm)
    shown = p["where"] + ":" + p["folder"]
    rm.state = "APPLIED"
    _write(rm.project, {"main.py": "if __name__ == '__main__':\n    print('hi')\n"})    # the same command works there
    assert rp.plan("RUN-1", rm=rm)["command"] == p["command"]
    started = []
    out = rp.start("RUN-1", p["command"], launcher=lambda *a: started.append(a) or True, rm=rm, expected_folder=shown)
    assert out["status"] == "stale" and started == []


def test_the_windows_script_shows_the_command_without_running_it_twice():
    win = rp.windows_script(Path("C:/w/100% p"), "npm install && npm run dev > log.txt", "http://127.0.0.1:5173/")
    lines = win.split("\r\n")
    assert lines[1] == f'cd /d "{Path("C:/w/100%% p")}"'
    assert lines[2] == "echo [Tribunal AI] npm install ^&^& npm run dev ^> log.txt"       # shown, not run
    assert "npm install && npm run dev > log.txt" in lines and not any(l.startswith('start ""') for l in lines)


def test_a_tkinter_app_gets_a_python_that_has_tkinter(tmp_path, monkeypatch):
    """Found on this Mac: Homebrew's python3 has no tkinter, so a windowed app only showed an import error. The plan
    names a Python that can open the window, and says so; nothing else is changed."""
    app = _write(tmp_path / "app", {"app.py": "import tkinter\nif __name__ == '__main__':\n    tkinter.Tk().mainloop()\n"})
    monkeypatch.setattr(rp, "_has_tk", lambda python: python == "/usr/bin/python3")
    monkeypatch.setattr(rp, "_version", lambda python: tuple(rp.sys.version_info[:2]))
    monkeypatch.setattr(rp.shutil, "which", lambda name: None)
    monkeypatch.setattr(rp.Path, "is_file", lambda self: True if self.as_posix() == "/usr/bin/python3" else Path.exists(self) and not Path.is_dir(self))
    assert rp._with_tk("python3 app.py", app) == ("/usr/bin/python3 app.py", {"tk": "switched", "from": "python3", "to": "/usr/bin/python3"})
    assert rp._with_tk("npm start", app) == ("npm start", None)                     # not a bare python
    assert rp._with_tk(".venv/bin/python app.py", app) == (".venv/bin/python app.py", None)
    plain = _write(tmp_path / "cli", {"main.py": "if __name__ == '__main__':\n    print(1)\n"})
    assert rp._with_tk("python3 main.py", plain) == ("python3 main.py", None)       # no tkinter in the project
    # Found running it: the only Python with tkinter was 3.9, the app was written for Tribunal's 3.13 (`float | None`
    # in a class body) and stopped at start. An older one is still offered, but with the reason and the fix.
    monkeypatch.setattr(rp, "_version", lambda python: (3, 9))
    monkeypatch.setattr(rp, "_tk_fix", lambda wanted: "brew install python-tk@%d.%d" % wanted)
    cmd, note = rp._with_tk("python3 app.py", app)
    want = "%d.%d" % tuple(rp.sys.version_info[:2])
    assert cmd == "/usr/bin/python3 app.py" and note == {"tk": "old", "from": "python3", "to": "/usr/bin/python3", "version": "3.9",
                                                         "wants": want, "fix": "brew install python-tk@" + want}
    monkeypatch.setattr(rp, "_has_tk", lambda python: False)
    assert rp._with_tk("python3 app.py", app) == ("python3 app.py", {"tk": "missing", "from": "python3", "fix": "brew install python-tk@" + want})
