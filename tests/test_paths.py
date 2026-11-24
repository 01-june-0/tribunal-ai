"""core/paths.py: one place decides where Tribunal's code is and where it keeps what it writes (docs/PACKAGING.md 4절).

Run from the checkout, nothing moves (data/ and runs/ stay where they always were). Installed, the records go to the
platform's per-user data folder; TRIBUNAL_HOME picks another folder."""
from pathlib import Path

import pytest

from core import paths


def test_a_checkout_keeps_its_records_where_they_always_were(monkeypatch):
    monkeypatch.delenv("TRIBUNAL_HOME", raising=False)
    monkeypatch.delenv("TRIBUNAL_RUNS_DIR", raising=False)
    assert not paths.installed()
    assert paths.home() == paths.CODE_ROOT and paths.data_dir() == paths.CODE_ROOT / "data"
    assert paths.runs_dir() == paths.CODE_ROOT / "runs"


def test_an_installed_copy_uses_the_platforms_data_folder(monkeypatch, tmp_path):
    monkeypatch.delenv("TRIBUNAL_HOME", raising=False)
    monkeypatch.setattr(paths, "CODE_ROOT", tmp_path / "venv" / "lib" / "python3.13" / "site-packages")
    assert paths.installed()
    monkeypatch.setattr(paths.Path, "home", staticmethod(lambda: tmp_path / "me"))
    monkeypatch.setattr(paths.sys, "platform", "darwin")
    assert paths.home() == tmp_path / "me" / "Library" / "Application Support" / "Tribunal AI"
    monkeypatch.setattr(paths.sys, "platform", "linux")
    monkeypatch.setattr(paths.os, "name", "posix")
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    assert paths.home() == tmp_path / "me" / ".local" / "share" / "tribunal-ai"
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    assert paths.home() == tmp_path / "xdg" / "tribunal-ai"


def test_tribunal_home_chooses_another_folder_and_must_be_absolute(monkeypatch, tmp_path):
    monkeypatch.setenv("TRIBUNAL_HOME", str(tmp_path))
    monkeypatch.delenv("TRIBUNAL_RUNS_DIR", raising=False)
    assert paths.home() == tmp_path and paths.runs_dir() == tmp_path / "runs"
    monkeypatch.setenv("TRIBUNAL_RUNS_DIR", str(tmp_path / "demo-runs"))     # the demo console's own set wins
    assert paths.runs_dir() == tmp_path / "demo-runs"
    monkeypatch.setenv("TRIBUNAL_HOME", "relative/place")
    with pytest.raises(ValueError):
        paths.home()


def test_the_config_of_an_installed_copy_is_the_shipped_one_with_the_persons_keys_on_top(monkeypatch, tmp_path):
    import director
    monkeypatch.setenv("TRIBUNAL_HOME", str(tmp_path))
    (tmp_path / "config.yaml").write_text("autonomy:\n  auto_apply: off\ntimeouts:\n  maker: 900\n", encoding="utf-8")
    cfg = director.load_config()
    assert cfg["autonomy"]["auto_apply"] is False or cfg["autonomy"]["auto_apply"] == "off"
    assert cfg["timeouts"]["maker"] == 900 and cfg["timeouts"]["architect"] == 300        # the rest stays the default
    assert cfg["autonomy"]["maker_attempts"] == 3


def test_the_console_defaults_ship_with_the_code(monkeypatch, tmp_path):
    from core import companion_config as cc
    (tmp_path / "companion.local.json").write_text('{"port": 8199}', encoding="utf-8")
    assert cc.load_companion_config(tmp_path)["port"] == 8199                  # the person's own value
    (tmp_path / "companion.local.json").unlink()
    import json
    shipped = json.loads((paths.CODE_ROOT / "companion.json").read_text(encoding="utf-8"))
    assert cc.load_companion_config(tmp_path) == shipped                       # falls back to the shipped companion.json
    assert cc.bridge_token_path(tmp_path) == tmp_path / "data" / "bridge.token"


def test_tribunals_own_records_are_never_a_project(monkeypatch, tmp_path):
    from core import bootstrap
    monkeypatch.setenv("TRIBUNAL_HOME", str(tmp_path / "home"))
    (tmp_path / "home" / "data").mkdir(parents=True)
    with pytest.raises(ValueError):
        bootstrap.prepare_project(str(tmp_path / "home" / "data"))
    with pytest.raises(ValueError):
        bootstrap.prepare_project(str(paths.CODE_ROOT))
