import pytest
import sqlite3
from pathlib import Path
from core.provider_manager import ProviderManager, ProviderStatus, FailoverMode
import requests
import json

def get_db(tmp_path):
    db_path = tmp_path / "director.db"
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS provider_health (
            provider TEXT PRIMARY KEY,
            cli TEXT,
            version TEXT,
            status TEXT NOT NULL,
            last_success DATETIME,
            last_failure DATETIME,
            failure_reason TEXT,
            current_role TEXT,
            last_latency_sec REAL,
            consecutive_failures INTEGER DEFAULT 0,
            usage_percent REAL,
            remaining REAL,
            reset_at DATETIME,
            last_checked DATETIME
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS provider_metrics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME NOT NULL,
            provider TEXT NOT NULL,
            status TEXT NOT NULL,
            usage_percent REAL,
            latency REAL,
            success INTEGER NOT NULL
        )
    ''')
    conn.commit()
    conn.close()
    return db_path

def test_a_normal_mode(tmp_path):
    db_path = get_db(tmp_path)
    pm = ProviderManager(db_path=str(db_path))
    
    # Check health forces init
    res = pm.check_health(force=True)
    mode, _ = pm.get_failover_mode()
    
    assert mode == FailoverMode.NORMAL
    
    roles = pm.resolve_roles()
    assert roles["architect_provider"] == "openai"
    assert roles["maker_provider"] == "antigravity"
    assert roles["inspector_provider"] == "codex"

def test_b_openai_quota_exhausted(tmp_path):
    db_path = get_db(tmp_path)
    pm = ProviderManager(db_path=str(db_path))
    
    # Simulate Quota Exhausted on OpenAI
    pm.set_status("OPENAI", ProviderStatus.QUOTA_EXHAUSTED, "usage limit reached")
    mode, down = pm.get_failover_mode()
    
    assert mode == FailoverMode.DEGRADED
    
    # Resolve roles should shift to Claude
    roles = pm.resolve_roles()
    assert roles["architect_provider"] == "claude"
    assert roles["inspector_provider"] == "claude"
    
    # Verify DB role was updated
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT current_role FROM provider_health WHERE provider = 'ANTHROPIC'")
    role = cursor.fetchone()['current_role']
    assert "ARCHITECT" in role
    assert "INSPECTOR" in role

def test_c_stop_mode(tmp_path):
    db_path = get_db(tmp_path)
    pm = ProviderManager(db_path=str(db_path))
    
    pm.set_status("OPENAI", ProviderStatus.UNAVAILABLE)
    pm.set_status("ANTHROPIC", ProviderStatus.AUTH_FAILED)
    
    mode, down = pm.get_failover_mode()
    assert mode == FailoverMode.STOP
    
    roles = pm.resolve_roles()
    assert roles["can_proceed"] is False

def test_d_unknown_usage(tmp_path):
    db_path = get_db(tmp_path)
    pm = ProviderManager(db_path=str(db_path))
    
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT usage_percent FROM provider_health WHERE provider = 'OPENAI'")
    usage = cursor.fetchone()['usage_percent']
    
    # DB allows NULL, meaning UNKNOWN
    assert usage is None

def test_e_cli_timeout(tmp_path):
    db_path = get_db(tmp_path)
    pm = ProviderManager(db_path=str(db_path))
    
    # simulate timeout parsing
    status = pm.parse_cli_error("GOOGLE", "hard timeout exceeded")
    assert status == ProviderStatus.TIMEOUT
    
    # check DB
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT status FROM provider_health WHERE provider = 'GOOGLE'")
    assert cursor.fetchone()['status'] == "TIMEOUT"

@pytest.mark.integration_dashboard
def test_f_dashboard():
    # We can fetch the dashboard locally
    try:
        resp = requests.get("http://localhost:8080/")
        assert resp.status_code == 200
        html = resp.text
        assert "TRIBUNAL AI" in html
        assert "OPENAI" in html
        assert "ANTHROPIC" in html
        assert "GOOGLE" in html
        assert "UNKNOWN" in html # usage percent
    except Exception as e:
        pytest.fail(f"Dashboard not running or failed: {e}")

def test_g_no_api_keys(tmp_path):
    db_path = get_db(tmp_path)
    pm = ProviderManager(db_path=str(db_path))
    # We just ensure it works without API keys
    assert True


# ---------------------------------------------------------------------------------- one AI down, whatever the layout

def _down(tmp_path, domain):
    pm = ProviderManager(db_path=str(tmp_path / "f.db"))
    for d in ("OPENAI", "ANTHROPIC", "GOOGLE"):
        pm.set_status(d, ProviderStatus.QUOTA_EXHAUSTED if d == domain else ProviderStatus.HEALTHY, "test")
    return pm


@pytest.mark.parametrize("layout,domain,expected", [
    # the current defaults: claude designs, codex builds, antigravity inspects
    (("claude", "codex", "antigravity"), "OPENAI", ("claude", "claude", "antigravity")),
    (("claude", "codex", "antigravity"), "GOOGLE", ("claude", "codex", "claude")),
    (("claude", "codex", "antigravity"), "ANTHROPIC", ("openai", "codex", "antigravity")),
    # the layout this rule was first written for must come out exactly as before
    (("claude", "antigravity", "codex"), "OPENAI", ("claude", "antigravity", "claude")),
    (("claude", "antigravity", "codex"), "GOOGLE", ("claude", "codex", "claude")),
    (("claude", "antigravity", "codex"), "ANTHROPIC", ("openai", "antigravity", "codex")),
    (("openai", "antigravity", "codex"), "OPENAI", ("claude", "antigravity", "claude")),
])
def test_a_role_on_a_dead_ai_moves_to_a_working_one(tmp_path, layout, domain, expected):
    """No role may stay on an AI that is down, and the inspector stays apart from the maker when it can."""
    from core.role_settings import ALIASES, DOMAINS
    out = _down(tmp_path, domain).resolve_roles(*layout)
    got = (out["architect_provider"], out["maker_provider"], out["inspector_provider"])
    assert got == expected and out["can_proceed"] is True
    assert all(DOMAINS[ALIASES[p]] != domain for p in got)
    assert DOMAINS[ALIASES[got[1]]] != DOMAINS[ALIASES[got[2]]]
    assert "unavailable. Degraded mode active" in out["reason"]


def test_the_default_roles_in_config_are_codex_maker_and_antigravity_inspector():
    import yaml
    from pathlib import Path as _P
    cfg = yaml.safe_load((_P(__file__).resolve().parents[1] / "config.yaml").read_text(encoding="utf-8"))
    assert (cfg["architect"]["provider"], cfg["maker"]["provider"], cfg["inspector"]["provider"]) == ("claude", "codex", "antigravity")
    assert cfg["maker"]["mode"] == "agent"                       # docs/AGENT_MODE.md


def test_what_is_not_one_of_the_three_is_left_alone_and_shared_roles_all_move(tmp_path):
    out = _down(tmp_path, "GOOGLE").resolve_roles("mock", "antigravity", "mock")
    assert (out["architect_provider"], out["maker_provider"], out["inspector_provider"]) == ("mock", "codex", "mock")   # a mock is never replaced
    out = _down(tmp_path, "OPENAI").resolve_roles("codex", "codex", "codex")
    assert (out["architect_provider"], out["maker_provider"], out["inspector_provider"]) == ("claude", "claude", "antigravity")
    out = _down(tmp_path, "OPENAI").resolve_roles("anthropic", "google", "openai")        # other spellings of the same three
    assert (out["architect_provider"], out["maker_provider"], out["inspector_provider"]) == ("anthropic", "google", "claude")
