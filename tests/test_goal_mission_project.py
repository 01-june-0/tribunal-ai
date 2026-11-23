"""A goal sent from outside the console (director do, the bridge) moves the chat session to that goal's project."""
import dashboard_server
from core.chat_manager import ChatManager
from core.orchestrator import Orchestrator
from tests.test_v0231_chat_stabilization import make_git_project
from tests.test_v0238_dashboard_ux import env  # noqa: F401


def _ask_back(monkeypatch):
    monkeypatch.setattr(Orchestrator, "architect_chat", lambda self, *a, **k: ({"type": "QUESTION", "message": "어느 파일인가요?"}, []))


def _messages(sid):
    return [(m["role"], m["content"]) for m in ChatManager().get_messages(sid)]


def test_goal_for_another_project_selects_it(env, monkeypatch):
    _ask_back(monkeypatch)
    with make_git_project() as first, make_git_project() as second:
        dashboard_server.set_project(first)
        sid = dashboard_server.active_session_id()
        out = dashboard_server.start_goal_mission(second, "add a function", source="cli")
        assert out["status"] == "question"
        session = ChatManager().get_session(sid)
        assert dashboard_server._project_key(session["project_path"]) == dashboard_server._project_key(second)
        msgs = _messages(sid)
        selected = [i for i, (role, text) in enumerate(msgs) if role == "SYSTEM" and text.startswith("PROJECT_SELECTED:")]
        goal_at = next(i for i, (role, text) in enumerate(msgs) if role == "USER" and "add a function" in text)
        assert len(selected) == 2 and selected[-1] < goal_at          # chosen before the goal is written into the chat


def test_goal_for_the_selected_project_adds_no_selection_line(env, monkeypatch):
    _ask_back(monkeypatch)
    with make_git_project() as proj:
        dashboard_server.set_project(proj)
        sid = dashboard_server.active_session_id()
        before = sum(1 for role, text in _messages(sid) if text.startswith("PROJECT_SELECTED:"))
        dashboard_server.start_goal_mission(proj, "add a function", source="cli")
        assert sum(1 for role, text in _messages(sid) if text.startswith("PROJECT_SELECTED:")) == before == 1


def test_rejected_path_leaves_the_session_alone(env, monkeypatch, tmp_path):
    _ask_back(monkeypatch)
    with make_git_project() as proj:
        dashboard_server.set_project(proj)
        sid = dashboard_server.active_session_id()
        out = dashboard_server.start_goal_mission(str(tmp_path / "nope"), "add a function", source="cli")
        assert out["status"] == "rejected"
        assert dashboard_server._project_key(ChatManager().get_session(sid)["project_path"]) == dashboard_server._project_key(proj)


def test_no_switch_while_a_console_chat_is_in_flight(env, monkeypatch):
    _ask_back(monkeypatch)
    with make_git_project() as first, make_git_project() as second:
        dashboard_server.set_project(first)
        sid = dashboard_server.active_session_id()
        monkeypatch.setattr(dashboard_server, "chat_in_flight", lambda: True)
        dashboard_server.start_goal_mission(second, "add a function", source="cli")
        assert dashboard_server._project_key(ChatManager().get_session(sid)["project_path"]) == dashboard_server._project_key(first)
