"""HEAD / BUILDER / REVIEWER became ARCHITECT / MAKER / INSPECTOR. What was written before must still be read."""
import json
import sqlite3

import pytest

from core import role_names as rn


def test_keys_and_role_codes_are_renamed_but_git_words_are_not():
    assert rn.rename_key("head_provider") == "architect_provider" and rn.rename_key("builder_attempts") == "maker_attempts"
    assert rn.rename_key("reviewer") == "inspector" and rn.rename_key("HEAD_EXCEPTION") == "ARCHITECT_EXCEPTION"
    assert rn.rename_key("MockHead") == "MockArchitect" and rn.rename_key("requested_head") == "requested_architect"
    for same in ("head_commit", "head_exists", "headers", "headline", "heading", "headless", "wt_head", "main_head", "overhead", "ahead"):
        assert rn.rename_key(same) == same, same
    assert rn.canon_role("HEAD") == "ARCHITECT" and rn.canon_role("HEAD, REVIEWER") == "ARCHITECT, INSPECTOR" and rn.canon_role("BACKUP") == "BACKUP"
    assert rn.canon_role("HEAD differs from the run's base commit") == "HEAD differs from the run's base commit"     # a sentence about git
    assert rn.canon_codes("REVIEWER_FAIL_CLOSED: x") == "INSPECTOR_FAIL_CLOSED: x" and rn.canon_codes("git diff HEAD") == "git diff HEAD"


def test_an_old_record_is_read_in_the_new_names():
    old = {"head": {"provider": "claude"}, "builder": {"mode": "proposal"}, "timeouts": {"head": 300, "reviewer": 300},
           "autonomy": {"head_proxy": True, "builder_attempts": 3}, "steps": [{"role": "BUILDER", "head_commit": "abc", "note": "HEAD moved"}]}
    assert rn.canon(old) == {"architect": {"provider": "claude"}, "maker": {"mode": "proposal"}, "timeouts": {"architect": 300, "inspector": 300},
                             "autonomy": {"architect_proxy": True, "maker_attempts": 3},
                             "steps": [{"role": "MAKER", "head_commit": "abc", "note": "HEAD moved"}]}
    assert rn.canon({"head": "claude", "architect": "openai"}) == {"architect": "openai"}       # both spellings: the new one wins
    assert rn.canon(rn.canon(old)) == rn.canon(old)


def test_paths_and_commands_in_a_config_are_never_rewritten():
    config = {"head": {"provider": "claude"}, "projects": {"/work/site-builder": {"test": ["git", "diff", "HEAD"]}, "/x/head/app": {}},
              "/srv/reviewer-tools": 1, "verify": ["HEAD"], "note with builder in it": 2}
    assert rn.canon(config) == {"architect": {"provider": "claude"}, "projects": {"/work/site-builder": {"test": ["git", "diff", "HEAD"]}, "/x/head/app": {}},
                                "/srv/reviewer-tools": 1, "verify": ["HEAD"], "note with builder in it": 2}
    assert rn.rename_key("/work/site-builder") == "/work/site-builder" and rn.rename_key("head-provider") == "architect-provider"


def test_old_wording_in_stored_reasons_still_finds_its_explanation():
    import dashboard_i18n as i
    assert i.reason_recommendation("REVIEWER_EXCEPTION") == i.reason_recommendation("INSPECTOR_EXCEPTION")
    assert i.retry_prompt("REVIEWER_FAIL_CLOSED") == i.retry_prompt("INSPECTOR_FAIL_CLOSED")
    assert i.reason_code("REVIEWER_EXCEPTION: boom") == i.reason_code("INSPECTOR_EXCEPTION: boom") != "UNKNOWN"


def test_a_database_from_before_the_rename_is_brought_up_to_date(tmp_path):
    path = tmp_path / "old.db"
    conn = sqlite3.connect(str(path))
    conn.executescript("""
        CREATE TABLE chat_sessions (id TEXT PRIMARY KEY, project_path TEXT, head_provider TEXT NOT NULL);
        CREATE TABLE chat_messages (id INTEGER PRIMARY KEY, session_id TEXT, role TEXT NOT NULL, content TEXT);
        CREATE TABLE result_state (run_id TEXT PRIMARY KEY, state TEXT, reviewer_state TEXT);
        CREATE TABLE ai_usage (id INTEGER PRIMARY KEY, role TEXT, provider TEXT);
        CREATE TABLE provider_health (provider TEXT PRIMARY KEY, current_role TEXT);
        INSERT INTO chat_sessions VALUES ('s', '/p', 'claude');
        INSERT INTO chat_messages (session_id, role, content) VALUES ('s', 'USER', 'hi'), ('s', 'HEAD', 'HEAD says the BUILDER is next'), ('s', 'SYSTEM', 'x');
        INSERT INTO result_state VALUES ('r', 'READY', 'PASS');
        INSERT INTO ai_usage (role, provider) VALUES ('HEAD', 'A'), ('BUILDER', 'G'), ('REVIEWER', 'O'), ('OTHER', 'O');
        INSERT INTO provider_health VALUES ('OPENAI', 'HEAD, REVIEWER'), ('GOOGLE', 'BUILDER'), ('ANTHROPIC', 'BACKUP');
    """)
    rn._DONE.clear()
    rn.migrate_db(conn)
    rn._DONE.clear()
    rn.migrate_db(conn)                                                     # twice for real: nothing left to do, nothing breaks
    assert conn.execute("SELECT architect_provider FROM chat_sessions").fetchone() == ("claude",)
    assert conn.execute("SELECT inspector_state FROM result_state").fetchone() == ("PASS",)
    assert [r[0] for r in conn.execute("SELECT role FROM ai_usage ORDER BY id")] == ["ARCHITECT", "MAKER", "INSPECTOR", "OTHER"]
    assert conn.execute("SELECT role, content FROM chat_messages ORDER BY id").fetchall() == [
        ("USER", "hi"), ("ARCHITECT", "HEAD says the BUILDER is next"), ("SYSTEM", "x")]      # what was said is history: not rewritten
    assert dict(conn.execute("SELECT provider, current_role FROM provider_health")) == {
        "OPENAI": "ARCHITECT, INSPECTOR", "GOOGLE": "MAKER", "ANTHROPIC": "BACKUP"}
    rn._DONE.clear()
    fresh = sqlite3.connect(str(tmp_path / "new.db"))
    rn.migrate_db(fresh)                                                    # an empty database is left alone
    assert fresh.execute("SELECT count(*) FROM sqlite_master").fetchone() == (0,)


def test_the_stores_open_an_old_database(tmp_path, monkeypatch):
    from core import db_path
    from core.chat_manager import ChatManager
    from core.state_machine import StateMachine
    path = tmp_path / "director.db"
    conn = sqlite3.connect(str(path))
    conn.executescript("""
        CREATE TABLE chat_sessions (id TEXT PRIMARY KEY, project_path TEXT, head_provider TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
        INSERT INTO chat_sessions VALUES ('main_session', NULL, 'claude', '2026-11-01T00:00:00', '2026-11-01T00:00:00');
    """)
    conn.commit(); conn.close()
    monkeypatch.setenv("TEST_DB_PATH", str(path))                           # still a temporary file, never the real database
    assert db_path.get_db_path() == path.resolve()
    rn._DONE.clear()
    StateMachine(); cm = ChatManager()
    assert cm.get_session("main_session")["architect_provider"] == "claude"


def test_role_settings_saved_before_the_rename_still_load(tmp_path, monkeypatch):
    from core import role_settings
    assert role_settings.validate({"head": "claude", "builder": "antigravity", "reviewer": "openai"}) == {
        "architect": "claude", "maker": "antigravity", "inspector": "openai"}
    monkeypatch.setattr(role_settings, "PATH", tmp_path / "role_settings.json")
    role_settings.PATH.write_text('{"head": "openai", "builder": "openai", "reviewer": "claude"}', encoding="utf-8")
    config = role_settings.apply({"architect": {}, "maker": {}, "inspector": {}})
    assert role_settings.current(config) == {"architect": "openai", "maker": "openai", "inspector": "claude"}
    with pytest.raises(ValueError):
        role_settings.validate({"head": "claude"})


def test_files_of_an_earlier_run_are_found_and_read(tmp_path, monkeypatch):
    from core.result_manager import ResultManager
    run = tmp_path / "RUN-OLD"
    run.mkdir()
    (run / "builder.json").write_text(json.dumps({"status": "DONE", "files_modified": ["a.py"], "builder_notes": "x"}), encoding="utf-8")
    rm = ResultManager.__new__(ResultManager)
    monkeypatch.setattr(ResultManager, "run_dir", staticmethod(lambda run_id: tmp_path / run_id))
    assert rm._load("RUN-OLD", "maker.json") == {"status": "DONE", "files_modified": ["a.py"], "maker_notes": "x"}
    assert rm._load("RUN-OLD", "order.json") is None and rn.old_file(run, "order.json") is None
    (run / "maker.json").write_text('{"status": "NEW"}', encoding="utf-8")
    assert rm._load("RUN-OLD", "maker.json") == {"status": "NEW"}            # a file in the new name is preferred


def test_old_reason_codes_and_the_old_command_line_flag(monkeypatch):
    import dashboard_i18n
    import director
    assert dashboard_i18n.reason_ko("REVIEWER_FAIL_CLOSED") == dashboard_i18n.reason_ko("INSPECTOR_FAIL_CLOSED") != dashboard_i18n.REASON_TEXT["UNKNOWN"]
    option = next(p for p in director.run.params if p.name == "architect_provider")
    assert set(option.opts) == {"--architect-provider", "--head-provider"}
