"""config.local.yaml cli_options -> extra CLI flags (core/cli_models.py)."""
import os

import pytest

from core import cli_models


@pytest.fixture
def local_config(tmp_path, monkeypatch):
    """Point the module at a temp config.local.yaml and lift the unit-test bypass."""
    monkeypatch.setattr(cli_models, "_user_skill_files", lambda: [])       # the machine's own skills are not part of the test
    path = tmp_path / "config.local.yaml"
    monkeypatch.setattr(cli_models, "LOCAL_CONFIG", path)
    monkeypatch.setenv("TRIBUNAL_DB_PATH", str(tmp_path / "director.db"))   # console AI settings: an empty set of its own
    monkeypatch.delenv("DIRECTOR_TESTING", raising=False)
    return path


def test_unit_tests_get_upstream_argv():
    assert cli_models.claude_print_argv("claude") == ["claude", "--print", "--output-format", "json", *cli_models.CLAUDE_OWN_SETTINGS]
    assert cli_models.codex_exec_argv("codex") == ["codex", "exec", "--sandbox", "read-only", "-"]


def test_claude_is_light_by_default_even_without_a_file(local_config):
    argv = cli_models.claude_print_argv("claude", json_output=False)
    assert argv == ["claude", "--print", *cli_models.CLAUDE_OWN_SETTINGS, *cli_models.CLAUDE_LIGHT_ARGS]
    # --tools without --strict-mcp-config inlines every MCP schema; they must travel together.
    assert "--strict-mcp-config" in argv and "--tools" in argv


def test_claude_light_off_model_and_effort(local_config):
    local_config.write_text("cli_options:\n  claude_light: false\n  claude_model: sonnet\n  claude_effort: medium\n")
    assert cli_models.claude_extra_args() == ["--model", "sonnet", "--effort", "medium"]


def test_invalid_values_never_reach_the_command_line(local_config):
    local_config.write_text(
        "cli_options:\n  claude_model: '--dangerously-skip-permissions'\n  claude_effort: turbo\n"
        "  codex_reasoning_effort: 'high\" --sandbox danger-full-access'\n")
    assert cli_models.claude_extra_args() == list(cli_models.CLAUDE_LIGHT_ARGS)
    assert cli_models.codex_exec_argv("codex") == ["codex", "exec", *[x for f in cli_models.CODEX_LIGHT_FEATURES for x in ("--disable", f)], "--sandbox", "read-only", "-"]


def test_codex_model_and_effort(local_config):
    local_config.write_text("cli_models:\n  codex: gpt-x\ncli_options:\n  codex_reasoning_effort: high\n")
    assert cli_models.codex_exec_argv("codex") == [
        "codex", "exec", "-m", "gpt-x", *[x for f in cli_models.CODEX_LIGHT_FEATURES for x in ("--disable", f)], "-c", 'model_reasoning_effort="high"', "--sandbox", "read-only", "-"]


def test_broken_yaml_falls_back(local_config):
    local_config.write_text("cli_options: [unclosed\n")
    assert cli_models.claude_extra_args() == list(cli_models.CLAUDE_LIGHT_ARGS)
    assert cli_models.codex_model_args() == [x for f in cli_models.CODEX_LIGHT_FEATURES for x in ("--disable", f)]


@pytest.mark.parametrize("value", ["false", '"false"', "'off'", "0", "no"])
def test_claude_light_off_spellings(local_config, value):
    local_config.write_text(f"cli_options:\n  claude_light: {value}\n")
    assert cli_models.claude_extra_args() == []


def test_codex_light_can_be_turned_off(local_config):
    local_config.write_text("cli_options:\n  codex_light: false\n")
    assert cli_models.codex_exec_argv("codex") == ["codex", "exec", "--sandbox", "read-only", "-"]
    assert cli_models.codex_exec_description() == "codex exec --sandbox read-only - <stdin>"


def test_personal_skills_are_switched_off_by_path_and_hidden_in_records(local_config, monkeypatch):
    tomllib = pytest.importorskip("tomllib")                              # Python 3.11+
    paths = ['/home/me/.agents/skills/a/SKILL.md', 'C:\\Users\\me\\s "x"\\SKILL.md', '/home/me/스킬 😀/SKILL.md']
    monkeypatch.setattr(cli_models, "_user_skill_files", lambda: [*paths, "/bad\nname/SKILL.md", "/bad\udcff/SKILL.md"])
    argv = cli_models.codex_exec_argv("codex")
    value = argv[argv.index("-c") + 1]
    parsed = tomllib.loads(value)["skills"]["config"]
    assert [(e["path"], e["enabled"]) for e in parsed] == [(p, False) for p in paths]   # unwritable names are left out
    described = cli_models.codex_exec_description()
    assert "<3 personal skills off>" in described and "/home/me" not in described


def test_skill_list_is_capped(local_config, monkeypatch):
    monkeypatch.setattr(cli_models, "_user_skill_files", lambda: [f"/s/{i:05d}/{'x' * 200}/SKILL.md" for i in range(500)])
    value = cli_models._skills_off_arg()
    assert 0 < value.count("enabled=false") < 500 and len(value) < cli_models.SKILLS_OFF_MAX_CHARS + 100


def test_skill_folders_are_found(tmp_path, monkeypatch):
    monkeypatch.setattr(cli_models.Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codexhome"))
    for rel in (".agents/skills/one/SKILL.md", "codexhome/skills/pack/two/SKILL.md", ".agents/skills/not-a-skill/README.md",
                "elsewhere/linked/SKILL.md"):
        target = tmp_path / rel
        target.parent.mkdir(parents=True)
        target.write_text("x")
    expected = ["/.agents/skills/one/SKILL.md", "/codexhome/skills/pack/two/SKILL.md"]
    if os.name != "nt":                                                     # a linked skill, and a link loop
        os.symlink(tmp_path / "elsewhere" / "linked", tmp_path / "codexhome" / "skills" / "linked")
        os.symlink(tmp_path / "codexhome" / "skills", tmp_path / "codexhome" / "skills" / "pack" / "loop")
        expected.insert(1, "/codexhome/skills/linked/SKILL.md")
    assert [p.replace(str(tmp_path), "").replace("\\", "/") for p in cli_models._user_skill_files()] == expected
