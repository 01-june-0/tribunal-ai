"""Per-machine model choice for the subscription CLIs, kept out of the tracked config.

config.local.yaml (untracked):

    cli_models:
      codex: gpt-6.1-sol      # passed as `codex exec -m gpt-6.1-sol`; omit to use the CLI's own default

    cli_options:
      claude_light: true            # default true: no MCP servers, no skills, read-only tools (about 51k -> 8k input tokens per call)
      claude_model: sonnet          # optional `claude --model`
      claude_effort: medium         # optional `claude --effort` (low|medium|high|xhigh|max)
      codex_reasoning_effort: high  # optional `codex exec -c model_reasoning_effort="high"` (minimal|low|medium|high|xhigh)

Why it exists: the Director otherwise runs whatever model ~/.codex/config.toml names, and a model that the signed-in
ChatGPT plan does not serve makes every Codex call fail in seconds ("model is not supported when using Codex with a
ChatGPT account"). Setting it here leaves the operator's everyday Codex configuration untouched.
"""
import os
import re
from pathlib import Path
from typing import List, Optional

import yaml

LOCAL_CONFIG = Path(__file__).resolve().parents[1] / "config.local.yaml"
_MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/:-]{0,99}$")


CLAUDE_EFFORTS = ("low", "medium", "high", "xhigh", "max")
CODEX_EFFORTS = ("minimal", "low", "medium", "high", "xhigh")
# HEAD and REVIEWER only read: the Director itself applies changes and runs the tests. Order matters less than
# the combination: limiting --tools WITHOUT --strict-mcp-config makes the CLI inline every MCP tool schema
# (measured 409k input tokens for a one-word prompt), so these three always travel together.
CLAUDE_LIGHT_ARGS = ("--strict-mcp-config", "--disable-slash-commands", "--tools", "Read,Grep,Glob")


def _section(name: str) -> dict:
    """One top-level mapping of config.local.yaml, or {}. Unit tests never read the local file."""
    if os.environ.get("DIRECTOR_TESTING") == "1":
        return {}
    try:
        data = yaml.safe_load(LOCAL_CONFIG.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return {}
    section = data.get(name) if isinstance(data, dict) else None
    return section if isinstance(section, dict) else {}


def _choice(key: str, allowed) -> Optional[str]:
    value = _section("cli_options").get(key)
    return value.strip() if isinstance(value, str) and value.strip() in allowed else None


def cli_model(name: str) -> Optional[str]:
    """The configured model for 'codex' (or another CLI name), or None."""
    value = _section("cli_models").get(name)
    if not isinstance(value, str) or not _MODEL_RE.match(value.strip()):
        return None                       # also keeps anything flag-shaped ("-c ...") off the command line
    return value.strip()


def codex_model_args() -> List[str]:
    model = cli_model("codex")
    args = ["-m", model] if model else []
    effort = _choice("codex_reasoning_effort", CODEX_EFFORTS)
    if effort:
        args += ["-c", f'model_reasoning_effort="{effort}"']
    return args


def codex_exec_argv(executable: str) -> List[str]:
    return [executable, "exec", *codex_model_args(), "--sandbox", "read-only", "-"]


def codex_exec_description() -> str:
    return " ".join(["codex", "exec", *codex_model_args(), "--sandbox", "read-only", "-", "<stdin>"])


def claude_extra_args() -> List[str]:
    """Flags added after `claude --print`: the light set (on unless claude_light is false) plus model/effort."""
    if os.environ.get("DIRECTOR_TESTING") == "1":
        return []
    options = _section("cli_options")
    light = options.get("claude_light")
    off = light is False or light == 0 or (isinstance(light, str) and light.strip().lower() in ("false", "no", "off", "0"))
    args = [] if off else list(CLAUDE_LIGHT_ARGS)
    model = options.get("claude_model")
    if isinstance(model, str) and _MODEL_RE.match(model.strip()):
        args += ["--model", model.strip()]
    effort = _choice("claude_effort", CLAUDE_EFFORTS)
    if effort:
        args += ["--effort", effort]
    return args


def claude_print_argv(executable: str, json_output: bool = True) -> List[str]:
    return [executable, "--print", *(["--output-format", "json"] if json_output else []), *claude_extra_args()]


def claude_print_description(json_output: bool = True) -> str:
    return " ".join(claude_print_argv("claude", json_output))
