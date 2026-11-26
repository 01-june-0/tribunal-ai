"""「새로 시작」 menu: a clean screen, a new project folder, the current project to the trash (core/workspace.py)."""
import json
import os
import sys
from pathlib import Path

import pytest

from core import workspace


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("TRIBUNAL_HOME", str(tmp_path / "th"))
    return tmp_path


def test_a_clean_screen_is_remembered(home):
    assert workspace.cleared_at() == ""
    stamp = workspace.clear_screen()
    assert workspace.cleared_at() == stamp


@pytest.mark.parametrize("name", ["brick-game", "벽돌깨기", "my game 2"])
def test_good_names(name):
    assert workspace.check_name(name) == name


@pytest.mark.parametrize("name", ["", "a/b", "a\\b", "..", ".", "con", "x:y", "trailing.", "a" * 81])
def test_bad_names(name):
    with pytest.raises(ValueError):
        workspace.check_name(name)


def test_a_new_folder_is_made_and_an_existing_one_is_never_reused(tmp_path):
    made = workspace.create_project_folder("game", str(tmp_path / "parent"))
    assert made.is_dir() and made == tmp_path / "parent" / "game"
    with pytest.raises(ValueError):
        workspace.create_project_folder("game", str(tmp_path / "parent"))
    with pytest.raises(ValueError):
        workspace.create_project_folder("game", "relative/place")


def test_the_default_place_is_documents(monkeypatch, tmp_path):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    (tmp_path / "Documents").mkdir()
    assert workspace.default_parent() == tmp_path / "Documents" / "Tribunal Projects"


def test_broad_and_own_folders_are_never_discarded(tmp_path):
    assert workspace.discardable(Path.home())
    assert workspace.discardable(Path.home() / "Documents")
    assert workspace.discardable(Path(__file__).resolve().parents[1])            # Tribunal's own code
    assert workspace.discardable(tmp_path / "missing")
    project = tmp_path / "a" / "b" / "proj"
    project.mkdir(parents=True)
    assert workspace.discardable(project) is None


@pytest.mark.skipif(sys.platform != "darwin", reason="the macOS trash is a folder this test can use safely")
def test_a_discarded_project_goes_to_the_trash_where_it_can_be_restored(tmp_path, monkeypatch):
    fake_home = tmp_path / "home"
    (fake_home / ".Trash").mkdir(parents=True)
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    project = tmp_path / "work" / "game"
    (project / "src").mkdir(parents=True)
    (project / "src" / "a.py").write_text("x = 1\n")
    out = workspace.move_to_trash(project)
    assert not project.exists() and Path(out["where"]) == fake_home / ".Trash" / "game"
    assert (Path(out["where"]) / "src" / "a.py").read_text() == "x = 1\n"
    (project / "src").mkdir(parents=True)                                              # the same name again: a new name in the trash
    assert Path(workspace.move_to_trash(project)["where"]).name == "game 2"


def test_the_stage_shows_only_tasks_after_a_clean_screen(home, monkeypatch):
    import dashboard_server as d
    missions = [{"mission_id": "M-old", "updated_at": "2026-11-26T01:00:00", "project_path": "/p"}]

    class Store:
        def all(self):
            return missions

    monkeypatch.setattr(d, "MissionStore", lambda: Store())
    monkeypatch.setattr(d, "mission_view", lambda m, sm: {"mission_id": m["mission_id"], "live": False, "steps": []})
    assert d.build_activity_payload()["focus_mission_id"] == "M-old"
    workspace.clear_screen()
    assert d.build_activity_payload()["focus_mission_id"] is None
    missions.insert(0, {"mission_id": "M-new", "updated_at": "2999-01-01T00:00:00", "project_path": "/p"})
    assert d.build_activity_payload()["focus_mission_id"] == "M-new"


def test_starting_over_is_refused_while_a_task_runs(home, monkeypatch):
    import dashboard_server as d
    monkeypatch.setattr(d, "_ACTIVE_PROJECTS", {"k": "M-1"})
    assert d.start_fresh()["status"] == "busy"
    assert d.create_new_project("x", str(home / "p"))["status"] == "busy" and not (home / "p" / "x").exists()
    assert d.discard_current_project("/anything")["status"] in ("busy", "rejected")        # refused either way


@pytest.mark.skipif(sys.platform != "darwin", reason="a case-insensitive disk")
def test_a_path_spelled_in_another_case_is_still_protected():
    """critic (2026-11-26): /users/edm/developer passed every check, so the whole Developer folder could be trashed."""
    home = Path.home()
    for spelled in (str(home).lower(), str(home / "Documents").upper(), str(Path(__file__).resolve().parents[1]).lower()):
        assert workspace.discardable(Path(spelled)), spelled


def test_a_folder_holding_another_project_is_not_discarded(tmp_path):
    outer = tmp_path / "a" / "b" / "outer"
    inner = outer / "inner-project"
    inner.mkdir(parents=True)
    assert "다른 프로젝트" in workspace.discardable(outer, [str(inner)])
    assert workspace.discardable(inner, [str(outer / "elsewhere")]) is None


def _session_with(d, project):
    from core.chat_manager import ChatManager
    sid = f"chat-test-{abs(hash(project)) % 10**8}"
    ChatManager().create_session(sid, project, "ANTHROPIC")
    return sid


def test_discarding_moves_the_folder_closes_its_tasks_and_starts_without_a_project(home, tmp_path, monkeypatch):
    import dashboard_server as d
    from core.chat_manager import ChatManager
    project = tmp_path / "x" / "y" / "game"
    project.mkdir(parents=True)
    _session_with(d, str(project.resolve()))
    monkeypatch.setattr(d, "active_session_id", lambda: f"chat-test-{abs(hash(str(project.resolve()))) % 10**8}")
    trashed = []
    monkeypatch.setattr(workspace, "move_to_trash", lambda p: trashed.append(p) or {"where": "/trash/game"})
    saved = []

    class Store:
        def all(self):
            return [{"mission_id": "M-1", "project_path": str(project.resolve())}, {"mission_id": "M-2", "project_path": "/other"}]

        def save(self, m, force=False):
            saved.append(m)

    monkeypatch.setattr(d, "MissionStore", lambda: Store())
    assert d.discard_current_project(str(tmp_path / "different"))["status"] == "rejected" and not trashed
    out = d.discard_current_project(str(project))
    assert out["status"] == "ok" and trashed == [project.resolve()]
    assert [m["mission_id"] for m in saved] == ["M-1"] and saved[0]["closed"] is True
    assert (ChatManager().get_session(out["session_id"]) or {}).get("project_path", "") == ""
    assert workspace.cleared_at() and "DISCARDING" not in d._ACTIVE_PROJECTS.values()


def test_a_new_project_that_cannot_be_selected_leaves_nothing_behind(home, tmp_path, monkeypatch):
    import dashboard_server as d
    def refuse(path):
        (Path(path) / ".git").mkdir()
        return "PROJECT_SELECTION_REJECTED: nope"
    monkeypatch.setattr(d, "set_project", refuse)
    out = d.create_new_project("game", str(tmp_path / "parent"))
    assert out["status"] == "rejected" and not (tmp_path / "parent" / "game").exists()
