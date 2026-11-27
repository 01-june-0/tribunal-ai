"""AI settings: per-CLI model/effort (core.cli_settings), plan and limits (core.cli_limits), duplicate roles."""
import json
from pathlib import Path
import os
import threading
import urllib.error
import urllib.request

import pytest

from core import cli_limits, cli_models, cli_settings, role_settings


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    cli_limits.clear_cache()
    monkeypatch.setattr(cli_models, "_user_skill_files", lambda: [])
    yield
    cli_limits.clear_cache()


# ---------------------------------------------------------------- settings
def test_settings_default_save_and_reload():
    blank = {"model": None, "effort": None, "plan": None, "warn_percent": 80}
    assert cli_settings.load() == {"claude": blank, "openai": blank, "antigravity": blank, "usage_poll_minutes": 5}
    saved = cli_settings.save({"claude": {"model": "sonnet", "effort": "medium", "warn_percent": 90}, "openai": {"effort": "ultra"},
                               "antigravity": {"model": "gemini-4-neon-high", "effort": ""}, "usage_poll_minutes": 10,
                               "claude_usage_lookup": True, "something_else": 1})
    assert saved["claude"] == {"model": "sonnet", "effort": "medium", "plan": None, "warn_percent": 90}
    assert saved["openai"] == {"model": None, "effort": "ultra", "plan": None, "warn_percent": 80}
    assert saved["antigravity"] == {"model": "gemini-4-neon", "effort": "high", "plan": None, "warn_percent": 80}   # full id -> base + level
    assert saved["usage_poll_minutes"] == 10
    assert "something_else" not in saved and "claude_usage_lookup" not in saved and cli_settings.load() == saved
    assert cli_settings.path().parent.name != "data" or "pytest" in str(cli_settings.path())   # next to the test database


@pytest.mark.parametrize("bad", [
    {"claude": {"model": "--dangerously-skip-permissions"}}, {"claude": {"effort": "turbo"}},
    {"openai": {"model": "x y"}}, {"antigravity": {"model": "a" * 200}}, {"claude": "sonnet"}, [],
    {"antigravity": {"effort": "ultra"}},                                    # valid for Codex only
])
def test_values_that_could_break_a_command_line_are_refused(bad):
    cli_settings.save({"claude": {"model": "opus"}})
    with pytest.raises(ValueError):
        cli_settings.save(bad)
    assert cli_settings.load()["claude"]["model"] == "opus"                 # the saved file is untouched


@pytest.mark.parametrize("bad", [{"claude": {"warn_percent": 0}}, {"claude": {"warn_percent": 101}}, {"openai": {"warn_percent": "80"}},
                                 {"antigravity": {"warn_percent": 79.5}}, {"claude": {"warn_percent": True}},
                                 {"usage_poll_minutes": 2}, {"usage_poll_minutes": "5"}, {"usage_poll_minutes": True}])
def test_threshold_and_interval_are_validated_on_save_and_forgiven_on_load(bad):
    with pytest.raises(ValueError):
        cli_settings.save(bad)
    cli_settings.path().write_text(json.dumps({**bad, "openai": {**bad.get("openai", {}), "model": "gpt-x"}}), encoding="utf-8")
    loaded = cli_settings.load()                                             # a hand-edited file: only the bad value is reset
    assert loaded["openai"]["model"] == "gpt-x" and loaded["usage_poll_minutes"] in cli_settings.POLL_MINUTES
    assert all(1 <= loaded[c]["warn_percent"] <= 100 for c in cli_settings.CLIS)


def test_damaged_file_falls_back_to_defaults():
    cli_settings.path().write_text("{not json", encoding="utf-8")
    assert cli_settings.load()["claude"] == {"model": None, "effort": None, "plan": None, "warn_percent": 80}


def test_parse_agy_models():
    text = "Fetching available models...\ngemini-4-neon-high\tGemini 4 Neon (High)\nbad id\tX\n--flag\tY\nclaude-opus-5-5-low\tClaude Opus 5.5 (Low)\n"
    assert cli_settings.parse_agy_models(text) == [{"id": "gemini-4-neon-high", "name": "Gemini 4 Neon (High)"},
                                                   {"id": "claude-opus-5-5-low", "name": "Claude Opus 5.5 (Low)"}]


def test_codex_model_list_comes_from_the_cli_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    (tmp_path / "models_cache.json").write_text(json.dumps({"models": [
        {"slug": "gpt-a", "display_name": "GPT A"}, {"slug": "hidden", "visibility": "hide"}, {"slug": "bad slug"}, "junk"]}))
    assert cli_settings.options()["openai"]["models"] == [{"id": "gpt-a", "name": "GPT A"}]
    (tmp_path / "models_cache.json").write_text("nope")
    assert cli_settings.options()["openai"]["models"] == []
    assert cli_settings.options()["antigravity"]["models"] == []            # never asked from the CLI under tests


# ---------------------------------------------------------------- settings reach the command lines
def test_unit_tests_keep_upstream_commands_even_with_settings_saved():
    cli_settings.save({"claude": {"model": "opus", "effort": "max"}, "antigravity": {"model": "m"}, "openai": {"model": "g"}})
    assert cli_models.claude_print_argv("claude") == ["claude", "--print", "--output-format", "json", *cli_models.CLAUDE_OWN_SETTINGS]
    assert cli_models.codex_exec_argv("codex") == ["codex", "exec", "--sandbox", "read-only", "-"]
    assert cli_models.agy_extra_args() == []


def test_console_choice_reaches_all_three_clis_and_wins_over_the_local_file(tmp_path, monkeypatch):
    local = tmp_path / "config.local.yaml"
    local.write_text("cli_models:\n  codex: from-file\ncli_options:\n  claude_model: haiku\n  claude_effort: low\n  codex_reasoning_effort: low\n")
    monkeypatch.setattr(cli_models, "LOCAL_CONFIG", local)
    monkeypatch.delenv("DIRECTOR_TESTING", raising=False)
    monkeypatch.setenv("TRIBUNAL_DB_PATH", str(tmp_path / "data" / "director.db"))
    (tmp_path / "data").mkdir()
    # nothing chosen in the console: the hand-edited file still applies
    claude = cli_models.claude_print_argv("claude")
    assert claude[claude.index("--model") + 1] == "haiku" and claude[claude.index("--effort") + 1] == "low"
    assert "from-file" in cli_models.codex_exec_argv("codex") and cli_models.agy_extra_args() == []
    cli_settings.save({"claude": {"model": "opus", "effort": "high"}, "openai": {"model": "gpt-x", "effort": "ultra"},
                       "antigravity": {"model": "gemini-4-neon-high", "effort": "medium"}})
    claude = cli_models.claude_print_argv("claude")
    assert claude[claude.index("--model") + 1] == "opus" and claude[claude.index("--effort") + 1] == "high"
    codex = cli_models.codex_exec_argv("codex")
    assert codex[codex.index("-m") + 1] == "gpt-x" and 'model_reasoning_effort="ultra"' in codex and "from-file" not in codex
    assert cli_models.agy_extra_args() == ["--model", "gemini-4-neon", "--effort", "medium"]       # never a full id plus --effort
    cli_settings.save({"antigravity": {"model": "gemini-pro-orchestrator-neon"}})
    assert cli_models.agy_extra_args() == ["--model", "gemini-pro-orchestrator-neon"]
    cli_settings.save({"antigravity": {"effort": "low"}})
    assert cli_models.agy_extra_args() == ["--effort", "low"]
    # a file written by hand with a full id AND a level: once the CLI's list is known, the level flag is left out
    cli_settings.path().write_text(json.dumps({"antigravity": {"model": "gemini-4-neon-high", "effort": "low"}}), encoding="utf-8")
    monkeypatch.setitem(cli_settings._AGY_MODELS, "models", [{"id": "gemini-4-neon-high", "name": "Gemini 4 Neon (High)"},
                                                              {"id": "gemini-pro-orchestrator-neon", "name": "Orchestrator (Neon)"}])
    assert cli_models.agy_extra_args() == ["--model", "gemini-4-neon-high"]
    # ... and a level the chosen base model does not come in is dropped too
    cli_settings.path().write_text(json.dumps({"antigravity": {"model": "gemini-4-neon", "effort": "max"}}), encoding="utf-8")
    assert cli_models.agy_extra_args() == ["--model", "gemini-4-neon"]
    cli_settings.path().write_text(json.dumps({"antigravity": {"model": "gemini-pro-orchestrator-neon", "effort": "high"}}), encoding="utf-8")
    assert cli_models.agy_extra_args() == ["--model", "gemini-pro-orchestrator-neon"]


# ---------------------------------------------------------------- limits
def test_codex_windows_are_told_apart_by_their_length():
    weekly_only = {"primary": {"used_percent": 97.0, "window_minutes": 10080, "resets_at": 1795199737}, "secondary": None, "plan_type": None}
    out = cli_limits.parse_codex_rate_limits(weekly_only)
    assert out["five_hour"] is None and out["weekly"]["used_percent"] == 97.0 and out["weekly"]["resets_at"].startswith("2026-11-20T")
    both = {"primary": {"used_percent": 12, "window_minutes": 300, "resets_at": 1}, "plan_type": "plus",
            "secondary": {"used_percent": 250, "window_minutes": 10080, "resets_at": None}}
    out = cli_limits.parse_codex_rate_limits(both)
    assert out["plan"] == "plus" and out["five_hour"]["used_percent"] == 12.0 and out["weekly"] == {"used_percent": 100.0, "resets_at": None}
    assert cli_limits.parse_codex_rate_limits("junk") == {"plan": None, "five_hour": None, "weekly": None}
    assert cli_limits.parse_codex_rate_limits({"primary": {"used_percent": True, "window_minutes": 300}})["five_hour"] is None


def test_codex_limits_come_from_the_newest_session_record(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    assert cli_limits.codex_limits()["state"] == "no_record"
    cli_limits.clear_cache()
    day = tmp_path / "sessions" / "2026" / "11" / "20"
    day.mkdir(parents=True)

    def rollout(name, used):
        lines = [{"timestamp": "2026-11-20T10:00:00Z", "type": "session_meta", "payload": {"cwd": "/SECRET"}},
                 {"timestamp": "2026-11-20T10:00:05Z", "type": "event_msg", "payload": {"type": "token_count", "rate_limits": {
                     "primary": {"used_percent": used, "window_minutes": 10080, "resets_at": 1795199737}}}},
                 {"timestamp": "2026-11-20T10:00:06Z", "type": "event_msg", "payload": {"type": "task_complete"}}]
        path = day / name
        path.write_text("\n".join(json.dumps(x) for x in lines) + "\n{half", encoding="utf-8")
        return path
    import os
    old, new = rollout("rollout-a.jsonl", 10), rollout("rollout-b.jsonl", 55)
    os.utime(old, (1, 1))
    out = cli_limits.codex_limits()
    assert out["state"] == "ok" and out["weekly"]["used_percent"] == 55.0 and out["as_of"].startswith("2026-11-20T10:00:05")
    assert "SECRET" not in json.dumps(out)


CLAUDE_USAGE_TEXT = """You are currently using your subscription to power your Claude Code usage

Current session: 4% used · resets Nov 21 at 5:50am (Asia/Seoul)
Current week (all models): 72% used · resets Nov 21 at 8am (Asia/Seoul)
Current week (Fable): 19% used · resets Nov 21 at 8am (Asia/Seoul)

What's contributing to your limits usage?
Last 24h · 1040 requests · 31 sessions
"""


def test_claude_usage_text_is_read_into_the_two_windows():
    from datetime import datetime, timezone
    now = datetime(2026, 11, 20, 16, 0, tzinfo=timezone.utc)
    out = cli_limits.parse_claude_usage_text(CLAUDE_USAGE_TEXT, now)
    assert out["five_hour"] == {"used_percent": 4.0, "resets_at": "2026-11-20T20:50:00+00:00"}
    assert out["weekly"] == {"used_percent": 72.0, "resets_at": "2026-11-20T23:00:00+00:00"}          # "all models", not a per-model line
    assert out["groups"] == [{"name": "Fable", "five_hour": None, "weekly": {"used_percent": 19.0, "resets_at": "2026-11-20T23:00:00+00:00"}}]
    # worded differently, partly or not at all: unknown rather than wrong
    assert cli_limits.parse_claude_usage_text("Current session: 12.5% used", now) == {"five_hour": {"used_percent": 12.5, "resets_at": None}, "weekly": None, "groups": []}
    assert cli_limits.parse_claude_usage_text("Usage is unavailable right now.", now) == {"five_hour": None, "weekly": None, "groups": []}
    assert cli_limits.parse_claude_usage_text(None) == {"five_hour": None, "weekly": None, "groups": []}


def test_claude_reset_times_without_a_year_or_a_date():
    from datetime import datetime, timezone
    now = datetime(2026, 12, 31, 20, 0, tzinfo=timezone.utc)
    assert cli_limits.parse_claude_reset("Jan 2 at 9am (UTC)", now) == "2027-01-02T09:00:00+00:00"       # next year
    assert cli_limits.parse_claude_reset("8am (UTC)", now) == "2027-01-01T08:00:00+00:00"                # no date: the next 8am
    assert cli_limits.parse_claude_reset("11:30pm (UTC)", now) == "2026-12-31T23:30:00+00:00"
    assert cli_limits.parse_claude_reset("12am (Asia/Seoul)", datetime(2026, 11, 20, 1, 0, tzinfo=timezone.utc)) == "2026-11-20T15:00:00+00:00"
    for junk in ("soon", "", None, "Nov 21 at 8am (Not/AZone)"):
        assert cli_limits.parse_claude_reset(junk, now) is None


def test_claude_is_asked_through_its_own_cli_and_no_login_token_is_read(monkeypatch):
    from types import SimpleNamespace
    assert cli_limits.claude_limits()["state"] == "unavailable"                 # unit tests never start the CLI
    monkeypatch.delenv("DIRECTOR_TESTING", raising=False)
    ran = []

    def fake_run(argv, **kw):
        ran.append(argv)
        if argv[1:3] == ["auth", "status"]:
            return SimpleNamespace(returncode=0, stdout=json.dumps({"loggedIn": True, "subscriptionType": "team", "email": "someone@example.com"}), stderr="")
        return SimpleNamespace(returncode=0, stdout=json.dumps({"local_command": True, "num_turns": 0, "result": CLAUDE_USAGE_TEXT}), stderr="")
    monkeypatch.setattr("core.env_utils.resolve_cli", lambda name: "/bin/claude")
    monkeypatch.setattr(cli_limits.subprocess, "run", fake_run)
    out = cli_limits.claude_limits(wait=True)
    assert out["plan"] == "team" and out["state"] == "ok" and out["five_hour"]["used_percent"] == 4.0 and out["weekly"]["used_percent"] == 72.0
    assert "example.com" not in json.dumps(out)
    usage_call = [a for a in ran if "/usage" in a][0]
    assert usage_call[:3] == ["/bin/claude", "-p", "/usage"] and "--no-session-persistence" in usage_call
    assert usage_call[usage_call.index("--tools") + 1] == "" and "--strict-mcp-config" in usage_call          # no tools, no MCP servers
    assert json.loads(usage_call[usage_call.index("--settings") + 1]) == {"disableAllHooks": True}             # and no hooks per poll
    assert Path(cli_limits._work_dir()).name == "limits-cwd" and Path(cli_limits._work_dir()).parent == cli_settings.path().parent
    assert all(a[0] == "/bin/claude" for a in ran)                               # nothing but the CLI itself: no keychain, no HTTP
    source = Path(cli_limits.__file__).read_text(encoding="utf-8")
    for forbidden in ("find-generic-password", ".credentials.json", "Authorization", "accessToken", "urllib"):
        assert forbidden not in source, forbidden


def test_a_claude_that_would_send_usage_to_the_model_is_never_asked_twice(monkeypatch):
    from types import SimpleNamespace
    monkeypatch.delenv("DIRECTOR_TESTING", raising=False)
    ran = []
    monkeypatch.setattr("core.env_utils.resolve_cli", lambda name: "/bin/claude")
    monkeypatch.setattr(cli_limits, "_claude_plan", lambda exe: None)
    answer = {"local_command": True, "num_turns": 1, "result": "I don't know that command."}       # a model turn, whatever else it says
    monkeypatch.setattr(cli_limits.subprocess, "run", lambda argv, **kw: ran.append(argv) or SimpleNamespace(
        returncode=0, stdout=json.dumps(answer), stderr=""))
    assert cli_limits.claude_limits(interval=0, wait=True)["state"] == "unavailable"
    cli_limits.claude_limits(interval=0, wait=True); cli_limits.claude_limits(interval=0, wait=True)
    assert len(ran) == 1


def test_a_claude_that_is_signed_out_or_errors_is_asked_again_later(monkeypatch):
    """No model turn happened, so nothing was spent: this is a failed look-up, not a reason to stop asking."""
    from types import SimpleNamespace
    monkeypatch.delenv("DIRECTOR_TESTING", raising=False)
    ran = []
    monkeypatch.setattr("core.env_utils.resolve_cli", lambda name: "/bin/claude")
    monkeypatch.setattr(cli_limits, "_claude_plan", lambda exe: "team")
    monkeypatch.setattr(cli_limits.subprocess, "run", lambda argv, **kw: ran.append(argv) or SimpleNamespace(
        returncode=0, stdout=json.dumps({"num_turns": 0, "is_error": True, "result": "Not logged in"}), stderr=""))
    out = cli_limits.claude_limits(interval=0, wait=True)
    assert out["state"] == "lookup_failed" and out["plan"] == "team" and out["five_hour"] is None
    cli_limits.claude_limits(interval=0, wait=True)
    assert len(ran) == 2


def test_snapshot_shape():
    snap = cli_limits.snapshot()
    assert set(snap) == {"claude", "openai", "antigravity"} and snap["antigravity"]["state"] == "unavailable" and snap["claude"]["state"] == "unavailable"
    for value in snap.values():
        assert {"plan", "five_hour", "weekly", "state"} <= set(value)


# ---------------------------------------------------------------- roles
def test_the_same_ai_may_hold_several_roles(tmp_path, monkeypatch):
    monkeypatch.setattr(role_settings, "PATH", tmp_path / "roles.json")
    all_claude = {"architect": "claude", "maker": "claude", "inspector": "claude"}
    assert role_settings.save(all_claude) == all_claude
    config = role_settings.apply({})
    assert role_settings.current(config) == all_claude and config["manual_roles"] is True
    assert role_settings.independence(all_claude) == "reduced"
    assert role_settings.independence({"architect": "claude", "maker": "claude", "inspector": "openai"}) == "full"
    assert role_settings.independence({"architect": "openai", "maker": "claude", "inspector": "openai"}) == "reduced"   # also for Codex
    assert role_settings.independence({"architect": "claude", "maker": "openai", "inspector": "openai"}) == "reduced"   # reviewing its own code
    with pytest.raises(ValueError):
        role_settings.save({"architect": "claude", "maker": "claude", "inspector": "gemini"})


def test_orchestrator_builds_agents_when_all_roles_share_one_ai(tmp_path, monkeypatch):
    from core.orchestrator import Orchestrator
    monkeypatch.setattr(role_settings, "PATH", tmp_path / "roles.json")
    role_settings.save({"architect": "claude", "maker": "claude", "inspector": "claude"})
    orch = Orchestrator(role_settings.apply({}))
    assert (orch.architect.provider, orch.maker.provider, orch.inspector.provider) == ("anthropic", "anthropic", "anthropic")
    assigned = orch.pm.resolve_roles("claude", "claude", "claude", strict=True)
    assert [assigned[r + "_provider"] for r in ("architect", "maker", "inspector")] == ["claude"] * 3
    with orch.pm._get_conn() as conn:
        row = conn.execute("SELECT current_role FROM provider_health WHERE provider='ANTHROPIC'").fetchone()
    assert row[0] == "ARCHITECT, MAKER, INSPECTOR"


# ---------------------------------------------------------------- the console endpoints
@pytest.fixture
def console(monkeypatch, tmp_path):
    import companion_server as cs
    from core.chat_manager import ChatManager
    from core.state_machine import StateMachine
    StateMachine(); ChatManager()
    monkeypatch.setattr(role_settings, "PATH", tmp_path / "roles.json")
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex-home"))      # not this machine's Codex session records
    server = cs.d.DashboardServer(("127.0.0.1", 0), cs.CompanionHandler)
    server.bridge_token = "tok"
    server.stopping = False
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield server
    server.shutdown(); server.server_close()


def _call(server, path, body=None, token="tok", origin=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["X-Tribunal-Token"] = token
    if origin:
        headers["Origin"] = origin
    request = urllib.request.Request(f"http://127.0.0.1:{server.server_address[1]}{path}",
                                     data=json.dumps(body).encode() if body is not None else None, headers=headers)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(request, timeout=10) as response:
            return response.status, json.loads(response.read().decode())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read().decode() or "null")


def test_ai_endpoint_reads_and_saves_settings(console):
    status, data = _call(console, "/ops/ai")
    assert status == 200 and set(data) == {"settings", "options", "limits", "accounts", "alerts", "permissions"} and data["alerts"] == []
    assert data["settings"]["usage_poll_minutes"] == 5 and data["options"]["poll_minutes"] == [1, 5, 10, 30]
    assert "tok" not in json.dumps(data)
    assert [p["id"] for p in data["options"]["antigravity"]["plans"]][-1] == "other"
    wanted = {**data["settings"], "claude": {"model": "opus", "effort": "high", "warn_percent": 70}, "usage_poll_minutes": 1}
    status, saved = _call(console, "/ops/ai", wanted)
    assert status == 200 and saved["settings"]["claude"] == {"model": "opus", "effort": "high", "plan": None, "warn_percent": 70}
    now = _call(console, "/ops/ai")[1]["settings"]
    assert now["claude"]["model"] == "opus" and now["usage_poll_minutes"] == 1
    assert _call(console, "/ops/ai", {"claude": {"effort": "turbo"}})[0] == 400
    assert _call(console, "/ops/ai", {"claude": {"warn_percent": 500}})[0] == 400
    assert _call(console, "/ops/ai", wanted, token=None)[0] == 403                    # needs the local token
    assert _call(console, "/ops/ai", wanted, origin="http://evil.example")[0] == 403    # and a local page
    assert _call(console, "/ops/ai/refresh", {}) == (200, {"refreshing": True}) and _call(console, "/ops/ai/refresh", {}, token=None)[0] == 403
    assert _call(console, "/ops/ai/refresh", {}) == (200, {"refreshing": False})
    assert cli_settings.load()["claude"]["model"] == "opus"


def test_roles_endpoint_accepts_duplicates_and_reports_independence(console):
    status, out = _call(console, "/ops/roles", {"architect": "claude", "maker": "claude", "inspector": "claude"})
    assert status == 200 and out["roles"] == {"architect": "claude", "maker": "claude", "inspector": "claude"}
    status, now = _call(console, "/ops/roles")
    assert now["roles"]["inspector"] == "claude" and now["independence"] == "reduced"


@pytest.mark.parametrize("roles,independent", [
    ({"architect": "openai", "maker": "antigravity", "inspector": "openai"}, False),     # Codex planning and reviewing
    ({"architect": "claude", "maker": "openai", "inspector": "openai"}, False),          # Codex reviewing its own code
    ({"architect": "claude", "maker": "claude", "inspector": "openai"}, True),
])
def test_orchestrator_judges_console_roles_the_way_the_console_warns(tmp_path, monkeypatch, roles, independent):
    """Without autonomy a PASS from a non-independent review must stop for a human; with it the PASS is kept and noted."""
    from types import SimpleNamespace
    from core.orchestrator import Orchestrator
    from core.state_machine import State
    monkeypatch.setattr(role_settings, "PATH", tmp_path / "roles.json")
    role_settings.save(roles)
    assert (role_settings.independence(roles) == "full") is independent
    import logging
    review = SimpleNamespace(verdict="pass", p0=[], p1=[], p2=[], summary="ok")
    for autonomy, expected in ((False, State.PASS if independent else State.HUMAN_REQUIRED), (True, State.PASS)):
        config = role_settings.apply({"autonomy": {"enabled": autonomy, "architect_proxy": autonomy}})
        orch = Orchestrator(config)
        assert orch._proxy() is autonomy
        decision = SimpleNamespace(decision=State.PASS, rationale="fine")
        assert orch.apply_final_pass_gate(decision, review, logging.getLogger("test")) == expected, (roles, autonomy)
        if autonomy and not independent:
            assert "REDUCED_INDEPENDENCE" in decision.rationale        # kept, but written down


def test_strict_roles_need_only_the_chosen_clis(tmp_path, monkeypatch):
    """One AI for everything: the other two being unavailable must not stop the run."""
    from core.orchestrator import Orchestrator
    from core.provider_manager import FailoverMode
    monkeypatch.setattr(role_settings, "PATH", tmp_path / "roles.json")
    role_settings.save({"architect": "claude", "maker": "claude", "inspector": "claude"})
    orch = Orchestrator(role_settings.apply({}))
    monkeypatch.setattr(orch.pm, "usable_domains", lambda: ["ANTHROPIC"])
    monkeypatch.setattr(orch.pm, "get_failover_mode", lambda: (FailoverMode.STOP, ["OPENAI(down)", "GOOGLE(down)"]))
    assert orch.pm.resolve_roles("claude", "claude", "claude", strict=True)["can_proceed"] is True
    assert orch.pm.resolve_roles("claude", "antigravity", "claude", strict=True)["can_proceed"] is False
    assert orch.pm.resolve_roles("claude", "claude", "claude", strict=False)["can_proceed"] is False   # automatic roles: unchanged


def test_alerts_list_every_window_at_or_over_its_threshold():
    limits = {"claude": {"five_hour": {"used_percent": 30.0, "resets_at": None}, "weekly": {"used_percent": 80.0, "resets_at": "x"}},
              "openai": {"five_hour": None, "weekly": {"used_percent": 97.0, "resets_at": None}},
              "antigravity": {"five_hour": {"used_percent": 79.9, "resets_at": None}, "weekly": None}}
    found = cli_limits.alerts(limits, {"claude": 80, "openai": 95, "antigravity": 80})
    assert [(a["cli"], a["window"], a["used_percent"], a["threshold"]) for a in found] == [("claude", "weekly", 80.0, 80), ("openai", "weekly", 97.0, 95)]
    # per-model and per-family limits count too (Claude's "Fable" week, Antigravity's other groups) — the headline group only once
    grouped = {"claude": {"five_hour": None, "weekly": {"used_percent": 10.0, "resets_at": None},
                          "groups": [{"name": "Fable", "five_hour": None, "weekly": {"used_percent": 91.0, "resets_at": None}}]},
               "antigravity": {"headline": "Gemini Models", "five_hour": {"used_percent": 85.0, "resets_at": None}, "weekly": None,
                               "groups": [{"name": "Gemini Models", "five_hour": {"used_percent": 85.0, "resets_at": None}, "weekly": None}]}}
    assert [(a["cli"], a["group"], a["window"]) for a in cli_limits.alerts(grouped, {"claude": 80, "antigravity": 80})] == [
        ("claude", "Fable", "weekly"), ("antigravity", None, "five_hour")]
    assert cli_limits.alerts(limits, {"claude": 81, "openai": 98, "antigravity": 80}) == []
    assert cli_limits.alerts(limits, {}) == [] and cli_limits.alerts({"claude": "junk"}, {"claude": 1}) == []
    # a window that has reset since it was read (an old Codex record, say) is not a warning any more
    stale = {"openai": {"five_hour": None, "weekly": {"used_percent": 97.0, "resets_at": "2020-01-01T00:00:00+00:00"}}}
    fresh = {"openai": {"five_hour": None, "weekly": {"used_percent": 97.0, "resets_at": "2999-01-01T00:00:00+00:00"}}}
    assert cli_limits.alerts(stale, {"openai": 80}) == [] and len(cli_limits.alerts(fresh, {"openai": 80})) == 1


def test_codex_models_carry_their_own_effort_list(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    (tmp_path / "models_cache.json").write_text(json.dumps({"models": [
        {"slug": "gpt-a", "supported_reasoning_levels": [{"effort": "low"}, {"effort": "high"}, {"effort": "made-up"}]},
        {"slug": "gpt-b"}]}))
    models = cli_settings.options()["openai"]["models"]
    assert models[0]["efforts"] == ["low", "high"] and "efforts" not in models[1]


# ---------------------------------------------------------------- plan chosen by the operator, Antigravity quota
def test_plan_is_a_choice_from_the_list_and_never_reaches_a_command_line(tmp_path, monkeypatch):
    saved = cli_settings.save({"antigravity": {"plan": "ai_pro"}, "openai": {"plan": "plus"}, "claude": {"plan": ""}})
    assert (saved["antigravity"]["plan"], saved["openai"]["plan"], saved["claude"]["plan"]) == ("ai_pro", "plus", None)
    for bad in ({"openai": {"plan": "ai_pro"}}, {"claude": {"plan": "--model x"}}, {"antigravity": {"plan": 3}}):
        with pytest.raises(ValueError):
            cli_settings.save(bad)
    for cli in cli_settings.CLIS:
        ids = [p["id"] for p in cli_settings.options()[cli]["plans"]]
        assert ids[0] == "free" and ids[-1] == "other" and len(set(ids)) == len(ids)
    monkeypatch.delenv("DIRECTOR_TESTING", raising=False)
    monkeypatch.setenv("TRIBUNAL_DB_PATH", str(tmp_path / "director.db"))
    monkeypatch.setattr(cli_models, "LOCAL_CONFIG", tmp_path / "none.yaml")
    cli_settings.save({"antigravity": {"plan": "ai_ultra"}, "openai": {"plan": "pro"}, "claude": {"plan": "max_20x"}})
    joined = " ".join(cli_models.claude_print_argv("claude") + cli_models.codex_exec_argv("codex") + cli_models.agy_extra_args())
    assert "ultra" not in joined and "max_20x" not in joined and "pro" not in joined.split()


def test_antigravity_usage_is_turned_from_remaining_into_used():
    data = {"status": "SUCCESS", "response": "TEXT", "command": {"name": "usage", "data": {"groups": [
        {"name": "Gemini Models", "buckets": [
            {"id": "gemini-weekly", "window": "weekly", "remaining_fraction": 0.995281994342804, "reset_time": "2026-11-27T06:45:13Z"},
            {"id": "gemini-5h", "window": "5h", "remaining_fraction": 0.25, "reset_time": "2026-11-20T16:45:13Z"}]},
        {"name": "Gemini 4 Argon", "buckets": [{"window": "weekly", "remaining_fraction": 1, "reset_time": None}]},
        {"name": "Broken", "buckets": [{"window": "weekly", "remaining_fraction": "lots"}, "junk", {"window": "monthly", "remaining_fraction": 0.5}]},
        "junk"]}}}
    out = cli_limits.parse_agy_usage(data)
    assert out["groups"][0]["five_hour"] == {"used_percent": 75.0, "resets_at": "2026-11-20T16:45:13+00:00"}
    assert out["groups"][0]["weekly"]["used_percent"] == 0.5 and [g["name"] for g in out["groups"]] == ["Gemini Models", "Gemini 4 Argon"]
    assert cli_limits._headline_group(out["groups"], "gemini-4-argon-high")["name"] == "Gemini 4 Argon"
    assert cli_limits._headline_group(out["groups"], None)["name"] == "Gemini Models" and cli_limits._headline_group([], "x") == {}
    assert out["groups"][1] == {"name": "Gemini 4 Argon", "five_hour": None, "weekly": {"used_percent": 0.0, "resets_at": None}}
    for junk in (None, {}, {"command": {"data": {"groups": "x"}}}, "text"):
        assert cli_limits.parse_agy_usage(junk) == {"five_hour": None, "weekly": None, "groups": []}


def test_antigravity_lookup_runs_the_usage_command_and_survives_failures(monkeypatch):
    from types import SimpleNamespace
    assert cli_limits.antigravity_limits()["state"] == "unavailable"            # unit tests never start the CLI
    monkeypatch.delenv("DIRECTOR_TESTING", raising=False)
    ran = []
    groups = [{"name": "Gemini Models", "buckets": [{"window": "5h", "remaining_fraction": 0.9, "reset_time": None}]},
              {"name": "Claude and GPT models", "buckets": [{"window": "5h", "remaining_fraction": 0.4, "reset_time": None}]}]

    def fake_run(argv, **kw):
        ran.append((argv, kw.get("stdin")))
        return SimpleNamespace(returncode=0, stdout="notice line\n" + json.dumps({"command": {"name": "usage", "data": {"groups": groups}}}), stderr="")
    monkeypatch.setattr("core.env_utils.resolve_cli", lambda name: "/bin/agy")
    monkeypatch.setattr(cli_limits.subprocess, "run", fake_run)
    out = cli_limits.antigravity_limits(wait=True)
    assert out["state"] == "ok" and out["five_hour"]["used_percent"] == 10.0 and out["plan"] is None and out["headline"] == "Gemini Models"
    assert ran == [(["/bin/agy", "-p", "/usage", "--output-format", "json"], cli_limits.subprocess.DEVNULL)]
    # the headline follows the model family chosen for Antigravity; nothing is asked again within the interval
    assert cli_limits.antigravity_limits("claude-opus-5-5", wait=True)["five_hour"]["used_percent"] == 60.0
    assert len(ran) == 1
    assert cli_limits.refresh_now() is True                                       # "check now" in the panel
    assert cli_limits.antigravity_limits(wait=True)["state"] == "ok" and len(ran) == 2
    assert cli_limits.refresh_now() is False                                      # pressed again at once: ignored
    cli_limits.antigravity_limits(wait=True)
    assert len(ran) == 2

    cli_limits.clear_cache()
    monkeypatch.setattr(cli_limits.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=2, stdout="", stderr="api key"))
    assert cli_limits.antigravity_limits(wait=True)["state"] == "unavailable"    # signed in with an API key
    cli_limits.clear_cache()
    monkeypatch.setattr(cli_limits.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(OSError("boom")))
    assert cli_limits.antigravity_limits(wait=True)["state"] == "lookup_failed"


def test_the_interval_chosen_in_the_panel_decides_how_often_a_cli_is_asked(monkeypatch):
    from types import SimpleNamespace
    monkeypatch.delenv("DIRECTOR_TESTING", raising=False)
    ran = []
    monkeypatch.setattr("core.env_utils.resolve_cli", lambda name: "/bin/agy")
    monkeypatch.setattr(cli_limits.subprocess, "run", lambda argv, **kw: ran.append(argv) or SimpleNamespace(
        returncode=0, stdout=json.dumps({"command": {"name": "usage", "data": {"groups": []}}}), stderr=""))
    clock = [1000.0]
    monkeypatch.setattr(cli_limits.time, "time", lambda: clock[0])
    for seconds, expected in ((0, 1), (30, 1), (59, 1), (60, 2), (119, 2), (120, 3)):
        clock[0] = 1000.0 + seconds
        cli_limits.antigravity_limits(interval=60, wait=True)
        assert len(ran) == expected, seconds


def test_an_agy_without_the_usage_command_is_never_asked_twice(monkeypatch):
    """Such a CLI would send "/usage" to the model as a prompt: one answer without the command marker switches the lookup off."""
    from types import SimpleNamespace
    monkeypatch.delenv("DIRECTOR_TESTING", raising=False)
    ran = []
    monkeypatch.setattr("core.env_utils.resolve_cli", lambda name: "/bin/agy")
    monkeypatch.setattr(cli_limits.subprocess, "run", lambda argv, **kw: ran.append(argv) or SimpleNamespace(
        returncode=0, stdout=json.dumps({"status": "SUCCESS", "response": "I do not know that command"}), stderr=""))
    assert cli_limits.antigravity_limits(interval=0, wait=True)["state"] == "unavailable"
    cli_limits.antigravity_limits(interval=0, wait=True); cli_limits.refresh_now(); cli_limits.antigravity_limits(interval=0, wait=True)
    assert len(ran) == 1                                                          # not even "check now" asks it again


def test_the_first_answer_does_not_wait_for_the_cli(monkeypatch):
    import threading
    from types import SimpleNamespace
    monkeypatch.delenv("DIRECTOR_TESTING", raising=False)
    release, started = threading.Event(), threading.Event()

    def slow_run(argv, **kw):
        started.set(); release.wait(5)
        return SimpleNamespace(returncode=0, stdout=json.dumps({"command": {"name": "usage", "data": {"groups": [
            {"name": "G", "buckets": [{"window": "weekly", "remaining_fraction": 0.5, "reset_time": None}]}]}}}), stderr="")
    monkeypatch.setattr("core.env_utils.resolve_cli", lambda name: "/bin/agy")
    monkeypatch.setattr(cli_limits.subprocess, "run", slow_run)
    assert cli_limits.antigravity_limits()["state"] == "loading"                 # answered at once
    assert started.wait(5) and cli_limits.antigravity_limits()["state"] == "loading"   # and no second CLI is started meanwhile
    release.set()
    for _ in range(100):
        if cli_limits.antigravity_limits()["state"] == "ok":
            break
        threading.Event().wait(0.05)
    assert cli_limits.antigravity_limits()["weekly"]["used_percent"] == 50.0


def test_a_plan_name_this_version_no_longer_lists_costs_only_itself():
    cli_settings.path().write_text(json.dumps({"claude": {"model": "opus", "effort": "high", "plan": "retired_plan", "warn_percent": 60},
                                               "openai": {"plan": ["x"]}, "usage_poll_minutes": 10}), encoding="utf-8")
    loaded = cli_settings.load()
    assert loaded["claude"] == {"model": "opus", "effort": "high", "plan": None, "warn_percent": 60} and loaded["usage_poll_minutes"] == 10


# ---------------------------------------------------------------- Antigravity: one model, several levels
def test_antigravity_models_are_grouped_by_base_with_their_levels():
    raw = cli_settings.parse_agy_models("Fetching...\ngemini-4-neon-high\tGemini 4 Neon (High)\ngemini-4-neon-xhigh\tGemini 4 Neon (XHigh)\n"
                                        "gemini-4-neon-low\tGemini 4 Neon (Low)\ngemini-pro-orchestrator-neon\tOrchestrator (Neon)\n"
                                        "gpt-oss-120b-medium\tGPT-OSS 120B (Medium)\n")
    assert cli_settings.group_agy_models(raw) == [
        {"id": "gemini-4-neon", "name": "Gemini 4 Neon", "efforts": ["low", "high", "xhigh"]},
        {"id": "gemini-pro-orchestrator-neon", "name": "Orchestrator (Neon)", "efforts": []},        # nothing to choose
        {"id": "gpt-oss-120b", "name": "GPT-OSS 120B", "efforts": ["medium"]}]
    assert cli_settings.split_agy_model("claude-opus-5-5-high") == ("claude-opus-5-5", "high")
    assert cli_settings.split_agy_model("gemini-pro-orchestrator-g1-pro") == ("gemini-pro-orchestrator-g1-pro", None)
    assert cli_settings.split_agy_model(None) == (None, None)
    saved = cli_settings.save({"antigravity": {"model": "gemini-4-neon-high", "effort": "low"}})
    assert saved["antigravity"]["model"] == "gemini-4-neon" and saved["antigravity"]["effort"] == "low"   # an explicit level wins


# ---------------------------------------------------------------- Codex: asked live, session record as the fallback
def test_codex_live_answer_is_preferred_and_reduced_to_plan_and_windows(monkeypatch):
    monkeypatch.delenv("DIRECTOR_TESTING", raising=False)
    asked = []

    def fake_rpc(requests, timeout=20.0):
        asked.append({k: v[0] for k, v in requests.items()})
        return {1: {"account": {"type": "chatgpt", "email": "someone@example.com", "planType": "pro"}, "userId": "user-SECRET"},
                2: {"rateLimits": {"planType": "pro", "primary": {"usedPercent": 97, "windowDurationMins": 10080, "resetsAt": 1795199737},
                                   "secondary": None, "credits": {"balance": "0"}}, "accountId": "ACCOUNT-SECRET"}}
    monkeypatch.setattr(cli_limits, "_codex_rpc", fake_rpc)
    out = cli_limits.codex_limits(wait=True)
    assert out["source"] == "live" and out["plan"] == "pro" and out["five_hour"] is None and out["weekly"]["used_percent"] == 97.0
    assert asked == [{1: "account/read", 2: "account/rateLimits/read"}]                 # read-only questions, nothing else
    dumped = json.dumps(out)
    assert "example.com" not in dumped and "SECRET" not in dumped
    cli_limits.codex_limits(wait=True)
    assert len(asked) == 1                                                              # not asked again within the refresh time


def test_codex_falls_back_to_the_session_record(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    monkeypatch.delenv("DIRECTOR_TESTING", raising=False)
    for broken in (lambda *a, **k: {}, lambda *a, **k: (_ for _ in ()).throw(OSError("no codex"))):
        cli_limits.clear_cache()
        monkeypatch.setattr(cli_limits, "_codex_rpc", broken)
        out = cli_limits.codex_limits(wait=True)
        assert out["source"] == "record" and out["state"] == "no_record"


def test_codex_app_server_camel_case_is_read_by_the_same_parser():
    snake = cli_limits._snake({"planType": "plus", "primary": {"usedPercent": 12, "windowDurationMins": 300, "resetsAt": 5},
                               "secondary": {"usedPercent": 40, "windowDurationMins": 10080, "resetsAt": None}})
    out = cli_limits.parse_codex_rate_limits(snake)
    assert out["plan"] == "plus" and out["five_hour"]["used_percent"] == 12.0 and out["weekly"]["used_percent"] == 40.0
    assert cli_limits.parse_codex_rate_limits(cli_limits._snake("junk")) == {"plan": None, "five_hour": None, "weekly": None}


def test_a_stored_base_name_is_never_split_again(monkeypatch):
    """'x-max-high' is saved as base 'x-max' + high; reading it back must not turn the base into 'x'."""
    monkeypatch.setitem(cli_settings._AGY_MODELS, "models", [])
    kept = {"model": "x-max", "effort": "high", "plan": None, "warn_percent": 80}
    assert cli_settings.save({"antigravity": {"model": "x-max-high"}})["antigravity"] == kept
    assert cli_settings.load()["antigravity"] == kept
    # with the CLI's list known, only ids the CLI really lists are split
    monkeypatch.setitem(cli_settings._AGY_MODELS, "models", [{"id": "gemini-4-neon-high", "name": "n"}])
    assert cli_settings.save({"antigravity": {"model": "gemini-ultra-max"}})["antigravity"]["model"] == "gemini-ultra-max"
    assert cli_settings.save({"antigravity": {"model": "gemini-4-neon-high"}})["antigravity"]["model"] == "gemini-4-neon"


def test_codex_rpc_talks_to_a_stand_in_app_server(tmp_path, monkeypatch):
    """The real _codex_rpc against a small script that speaks the same line protocol (one error reply included)."""
    import stat
    import sys
    if os.name == "nt":
        pytest.skip("stand-in executable needs a shebang")
    script = tmp_path / "codex"
    script.write_text(f"""#!{sys.executable}
import json, sys
assert sys.argv[1:] == ["app-server"]
for line in sys.stdin:
    m = json.loads(line)
    if m.get("method") == "initialize": print(json.dumps({{"id": m["id"], "result": {{}}}}), flush=True)
    elif m.get("method") == "account/read": print(json.dumps({{"id": m["id"], "error": {{"message": "nope"}}}}), flush=True)
    elif m.get("method") == "account/rateLimits/read":
        print("not json", flush=True)
        print(json.dumps({{"id": m["id"], "result": {{"rateLimits": {{"primary": {{"usedPercent": 5, "windowDurationMins": 300, "resetsAt": 9}}}}}}}}), flush=True)
""", encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setattr("core.env_utils.resolve_cli", lambda name: str(script))
    import time
    began = time.time()
    answers = cli_limits._codex_rpc({1: ("account/read", {"refreshToken": False}), 2: ("account/rateLimits/read", None)}, timeout=10)
    assert time.time() - began < 8                                             # an error reply does not make it wait out the timeout
    assert answers[1] is None and answers[2]["rateLimits"]["primary"]["usedPercent"] == 5
    monkeypatch.delenv("DIRECTOR_TESTING", raising=False)
    live = cli_limits._codex_live()
    assert live["five_hour"]["used_percent"] == 5.0 and live["plan"] is None and live["source"] == "live"


def test_an_empty_live_answer_does_not_hide_the_session_record(monkeypatch):
    monkeypatch.setattr(cli_limits, "_codex_rpc", lambda *a, **k: {1: {"account": {"planType": "pro"}}, 2: {"rateLimits": {"primary": None, "secondary": None}}})
    assert cli_limits._codex_live() is None


def test_the_endpoint_turns_saved_thresholds_into_alerts(console, tmp_path):
    """A Codex session record at 97% of the week: no warning at a threshold of 98, a warning at 80."""
    from datetime import datetime, timedelta, timezone
    day = tmp_path / "codex-home" / "sessions" / "2026" / "11" / "20"
    day.mkdir(parents=True)
    reset = int((datetime.now(timezone.utc) + timedelta(hours=3)).timestamp())
    (day / "rollout-a.jsonl").write_text(json.dumps({"timestamp": "2026-11-20T10:00:05Z", "type": "event_msg", "payload": {
        "type": "token_count", "rate_limits": {"primary": {"used_percent": 97.0, "window_minutes": 10080, "resets_at": reset}}}}) + "\n")
    cli_limits.clear_cache()
    data = _call(console, "/ops/ai")[1]
    assert [(a["cli"], a["window"], a["threshold"]) for a in data["alerts"]] == [("openai", "weekly", 80)]
    _call(console, "/ops/ai", {**data["settings"], "openai": {**data["settings"]["openai"], "warn_percent": 98}})
    assert _call(console, "/ops/ai")[1]["alerts"] == []


# ---------------------------------------------------------------- "AI 상태 새로고침" lives in the AI settings panel
def test_health_recheck_button_and_badge_are_wired_on_the_stage():
    import re
    root = Path(cli_limits.__file__).resolve().parents[1]
    html = (root / "console" / "index.html").read_text(encoding="utf-8")
    js = (root / "console" / "stage.js").read_text(encoding="utf-8")
    tools = html[html.index('id="ai-tools"'):html.index('id="ai-cards"')]
    assert 'id="ai-health"' in tools and 'id="ai-refresh"' in tools
    handler = js[js.index("$('ai-health').onclick"):]
    handler = handler[:handler.index("finally")]
    assert "fetch('/providers/refresh',{method:'POST'" in handler and "paintAI(true)" in handler
    assert "el('span',hs[0],'ai-health '+hs[1])" in js and "status.providers[p]" in js
    from core.provider_manager import ProviderStatus
    listed = set(re.findall(r"([A-Z_]+):\[T\('", js[js.index("const HEALTH={"):js.index("};", js.index("const HEALTH={"))]))
    assert listed == {s.value for s in ProviderStatus}                           # every status the server can report has a label


def test_providers_refresh_answers_what_the_button_reads(console, monkeypatch):
    import dashboard_server as ds
    cleared = []
    monkeypatch.setattr(ds, "invalidate_status_cache", lambda: cleared.append(1))

    class FakeManager:
        def check_health(self, force=False):
            from core.provider_manager import ProviderStatus
            cleared.append("probe")
            return {"OPENAI": ProviderStatus.HEALTHY, "ANTHROPIC": ProviderStatus.RECOVERING, "GOOGLE": ProviderStatus.UNAVAILABLE}
    monkeypatch.setattr(ds, "ProviderManager", FakeManager)
    request = urllib.request.Request(f"http://127.0.0.1:{console.server_address[1]}/providers/refresh", data=b"",
                                     headers={"Accept": "application/json", "X-Requested-With": "fetch"})
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request, timeout=10) as response:
        body = json.loads(response.read().decode())
    assert body == {"status": "ok", "providers": {"OPENAI": "HEALTHY", "ANTHROPIC": "RECOVERING", "GOOGLE": "UNAVAILABLE"}}
    assert cleared == [1, "probe", 1]                                            # the status cache is dropped again once the probes are done
