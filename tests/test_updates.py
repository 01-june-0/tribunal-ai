"""Phase 5 of docs/PACKAGING.md: the new-version notice (core/updates.py). GitHub is never asked here."""
import json

import pytest

from core import updates


@pytest.fixture
def home(monkeypatch, tmp_path):
    monkeypatch.setenv("TRIBUNAL_HOME", str(tmp_path))
    monkeypatch.delenv("TRIBUNAL_NO_UPDATE_CHECK", raising=False)
    monkeypatch.setattr(updates, "current", lambda: "3.2.0")
    return tmp_path


def test_version_order():
    assert updates.newer("v3.2.1", "3.2.0") and updates.newer("3.3", "3.2.9")
    assert updates.newer("v3.2.0", "3.2.0.dev0") and updates.newer("3.2.0", "3.2.0rc1")
    assert not updates.newer("v3.2.0", "3.2.0") and not updates.newer("3.1.9", "3.2.0")
    assert not updates.newer("nightly", "3.2.0") and not updates.newer("", "3.2.0")


def test_asks_once_a_day_and_remembers(home, monkeypatch):
    calls = []
    monkeypatch.setattr(updates, "_fetch", lambda timeout: calls.append(timeout) or
                        {"latest": "v3.3.0", "url": "https://github.com/01-june-0/tribunal-ai/releases/tag/v3.3.0"})
    first = updates.check(now=1000.0)
    assert first["newer"] is True and first["latest"] == "v3.3.0" and first["url"].endswith("/v3.3.0")
    assert updates.check(now=1000.0 + 3600)["newer"] is True and len(calls) == 1          # from the remembered answer
    updates.check(now=1000.0 + updates.DAY + 1)
    assert len(calls) == 2
    assert json.loads((home / "data" / "update-check.json").read_text(encoding="utf-8"))["latest"] == "v3.3.0"


def test_offline_or_no_release_says_nothing_and_waits_a_day(home, monkeypatch):
    def down(timeout):
        raise OSError("no network")
    monkeypatch.setattr(updates, "_fetch", down)
    result = updates.check(now=50.0)
    assert result["latest"] is None and result["newer"] is False and result["url"] == updates.RELEASES
    monkeypatch.setattr(updates, "_fetch", lambda timeout: pytest.fail("asked again the same day"))
    updates.check(now=60.0)


def test_switched_off_never_asks(home, monkeypatch):
    monkeypatch.setenv("TRIBUNAL_NO_UPDATE_CHECK", "1")
    monkeypatch.setattr(updates, "_fetch", lambda timeout: pytest.fail("must not ask"))
    assert updates.check()["latest"] is None


def test_only_this_repositorys_release_pages_are_linked(monkeypatch):
    class Reply:
        def __init__(self, data): self.data = json.dumps(data).encode()
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return self.data
    monkeypatch.setattr(updates.urllib.request, "urlopen", lambda req, timeout: Reply(
        {"tag_name": "v9", "html_url": "https://evil.example/download"}))
    assert updates._fetch(1) is None
    monkeypatch.setattr(updates.urllib.request, "urlopen", lambda req, timeout: Reply(
        {"tag_name": "v9", "html_url": "https://github.com/01-june-0/tribunal-ai/releases/tag/v9"}))
    assert updates._fetch(1)["latest"] == "v9"


def test_the_console_and_doctor_report_it(home, monkeypatch):
    import companion_server
    import tribunal_cli
    from click.testing import CliRunner
    monkeypatch.setattr(updates, "check", lambda timeout=4.0, now=None: {
        "current": "3.2.0", "latest": "v3.3.0", "newer": True, "url": "https://github.com/x", "checked_at": 1})
    assert "/ops/version" in open(companion_server.__file__, encoding="utf-8").read()
    out = CliRunner().invoke(tribunal_cli.cli, ["doctor"]).output
    assert "Tribunal AI 3.2.0" in out and "v3.3.0" in out


def test_a_damaged_record_or_a_failed_check_never_loses_or_breaks(home, monkeypatch):
    (home / "data").mkdir(exist_ok=True)
    (home / "data" / "update-check.json").write_text('{"checked_at": "garbage"}', encoding="utf-8")
    monkeypatch.setattr(updates, "_fetch", lambda timeout: {"latest": "v3.4.0",
                                                            "url": "https://github.com/01-june-0/tribunal-ai/releases/tag/v3.4.0"})
    assert updates.check(now=10.0)["latest"] == "v3.4.0"                     # damaged: asked again, no error

    def down(timeout):
        raise OSError("offline")
    monkeypatch.setattr(updates, "_fetch", down)
    later = updates.check(now=10.0 + updates.DAY + 5)
    assert later["latest"] == "v3.4.0" and later["newer"] is True              # what was known stays
