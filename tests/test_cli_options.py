"""config.local.yaml cli_options -> extra CLI flags (core/cli_models.py)."""
import pytest

from core import cli_models


@pytest.fixture
def local_config(tmp_path, monkeypatch):
    """Point the module at a temp config.local.yaml and lift the unit-test bypass."""
    path = tmp_path / "config.local.yaml"
    monkeypatch.setattr(cli_models, "LOCAL_CONFIG", path)
    monkeypatch.delenv("DIRECTOR_TESTING", raising=False)
    return path


def test_unit_tests_get_upstream_argv():
    assert cli_models.claude_print_argv("claude") == ["claude", "--print", "--output-format", "json"]
    assert cli_models.codex_exec_argv("codex") == ["codex", "exec", "--sandbox", "read-only", "-"]


def test_claude_is_light_by_default_even_without_a_file(local_config):
    argv = cli_models.claude_print_argv("claude", json_output=False)
    assert argv == ["claude", "--print", *cli_models.CLAUDE_LIGHT_ARGS]
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
    assert cli_models.codex_exec_argv("codex") == ["codex", "exec", "--sandbox", "read-only", "-"]


def test_codex_model_and_effort(local_config):
    local_config.write_text("cli_models:\n  codex: gpt-x\ncli_options:\n  codex_reasoning_effort: high\n")
    assert cli_models.codex_exec_argv("codex") == [
        "codex", "exec", "-m", "gpt-x", "-c", 'model_reasoning_effort="high"', "--sandbox", "read-only", "-"]


def test_broken_yaml_falls_back(local_config):
    local_config.write_text("cli_options: [unclosed\n")
    assert cli_models.claude_extra_args() == list(cli_models.CLAUDE_LIGHT_ARGS)
    assert cli_models.codex_model_args() == []


@pytest.mark.parametrize("value", ["false", '"false"', "'off'", "0", "no"])
def test_claude_light_off_spellings(local_config, value):
    local_config.write_text(f"cli_options:\n  claude_light: {value}\n")
    assert cli_models.claude_extra_args() == []
