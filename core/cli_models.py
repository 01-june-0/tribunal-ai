"""Per-machine model choice for the subscription CLIs, kept out of the tracked config.

config.local.yaml (untracked):

    cli_models:
      codex: gpt-6.1-sol      # passed as `codex exec -m gpt-6.1-sol`; omit to use the CLI's own default

    cli_options:
      claude_light: true            # default true: no MCP servers, no skills, read-only tools (about 51k -> 8k input tokens per call)
      claude_model: sonnet          # optional `claude --model`
      claude_effort: medium         # optional `claude --effort` (low|medium|high|xhigh|max)
      codex_light: true             # default true: no plugins/skills, memories, hooks or apps (about 52k -> 7k tokens per review)
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

from core.paths import home as _home

LOCAL_CONFIG = _home() / "config.local.yaml"
_MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/:-]{0,99}$")


CLAUDE_EFFORTS = ("low", "medium", "high", "xhigh", "max")
CODEX_EFFORTS = ("minimal", "low", "medium", "high", "xhigh", "max", "ultra")
# ARCHITECT and INSPECTOR only read: the Director itself applies changes and runs the tests. Order matters less than
# the combination: limiting --tools WITHOUT --strict-mcp-config makes the CLI inline every MCP tool schema
# (measured 409k input tokens for a one-word prompt), so these three always travel together.
# The inspector judges a diff against an order; the operator's personal Codex plugins (skills), memories, hooks and
# connected apps only add context and extra tool calls to that. Measured on one review-shaped prompt: 51,852 -> 7,232.
# Personal skill folders are switched off separately (see _skills_off_arg).
CODEX_LIGHT_FEATURES = ("plugins", "memories", "hooks", "apps", "skill_search")
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


def _is_off(value) -> bool:
    return value is False or (value == 0 and value is not True and not isinstance(value, str)) or (
        isinstance(value, str) and value.strip().lower() in ("false", "no", "off", "0"))


SKILLS_OFF_MAX_CHARS = 20000          # stays far below the Windows command-line limit


def _user_skill_files() -> List[str]:
    """The operator's personal skills. Disabling the plugins feature does not cover these two folders, and
    Codex has no switch for all skills, so each one is switched off by path."""
    codex_home = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex").expanduser()
    found: List[str] = []
    seen = set()
    for root in (Path.home() / ".agents" / "skills", codex_home / "skills"):
        try:
            # os.walk with followlinks: skills are often installed as links, which `**` skips on newer Pythons.
            for folder, subdirs, files in os.walk(root, followlinks=True):
                real = os.path.realpath(folder)
                if real in seen or folder.count(os.sep) - str(root).count(os.sep) > 6:
                    subdirs[:] = []                 # a link loop, or deeper than any skill layout
                    continue
                seen.add(real)
                subdirs.sort()
                if "SKILL.md" in files:
                    found.append(os.path.join(folder, "SKILL.md"))
        except OSError:
            continue
    return found


def _skills_off_arg() -> Optional[str]:
    """`skills.config=[{path="...",enabled=false},...]` for `codex exec -c`, or None when there is nothing to
    switch off. json.dumps(ensure_ascii=False) of a printable path is a valid TOML basic string (the default
    \\uD83D-style surrogate escapes are not)."""
    import json
    entries, size = [], 0
    for path in _user_skill_files():
        try:
            path.encode("utf-8")                    # an undecodable file name cannot be written as TOML
        except UnicodeEncodeError:
            continue
        if not path.isprintable():
            continue
        entry = "{path=%s,enabled=false}" % json.dumps(path, ensure_ascii=False)
        if size + len(entry) > SKILLS_OFF_MAX_CHARS:
            break
        entries.append(entry)
        size += len(entry) + 1
    return "skills.config=[" + ",".join(entries) + "]" if entries else None


def codex_model_args(describe: bool = False) -> List[str]:
    """Everything between `codex exec` and `--sandbox`: model, reasoning effort, and the light set.
    describe=True gives the form kept in records: the skill list is shown as a count, not as home-folder paths."""
    if os.environ.get("DIRECTOR_TESTING") == "1":
        return []
    from core import cli_settings
    chosen = cli_settings.choice("openai")           # set in the console; wins over config.local.yaml
    model = chosen["model"] or cli_model("codex")
    args = ["-m", model] if model else []
    if not _is_off(_section("cli_options").get("codex_light")):
        for feature in CODEX_LIGHT_FEATURES:
            args += ["--disable", feature]
        skills_off = _skills_off_arg()
        if skills_off:
            args += ["-c", f"skills.config=<{skills_off.count('enabled=false')} personal skills off>" if describe else skills_off]
    effort = chosen["effort"] or _choice("codex_reasoning_effort", CODEX_EFFORTS)
    if effort:
        args += ["-c", f'model_reasoning_effort="{effort}"']
    return args


def codex_exec_argv(executable: str, outside_git: bool = False) -> List[str]:
    """outside_git: the folder is not a git repository yet (a new project before its first task), which `codex exec`
    otherwise refuses; read-only, so nothing is written there either way."""
    return [executable, "exec", *codex_model_args(), "--sandbox", "read-only",
            *(["--skip-git-repo-check"] if outside_git else []), "-"]


def codex_exec_description(outside_git: bool = False) -> str:
    return " ".join(["codex", "exec", *codex_model_args(describe=True), "--sandbox", "read-only",
                     *(["--skip-git-repo-check"] if outside_git else []), "-", "<stdin>"])


def claude_extra_args() -> List[str]:
    """Flags added after `claude --print`: the light set (on unless claude_light is false) plus model/effort."""
    if os.environ.get("DIRECTOR_TESTING") == "1":
        return []
    options = _section("cli_options")
    args = [] if _is_off(options.get("claude_light")) else list(CLAUDE_LIGHT_ARGS)
    from core import cli_settings
    chosen = cli_settings.choice("claude")           # set in the console; wins over config.local.yaml
    model = chosen["model"] or options.get("claude_model")
    if isinstance(model, str) and _MODEL_RE.match(model.strip()):
        args += ["--model", model.strip()]
    effort = chosen["effort"] or _choice("claude_effort", CLAUDE_EFFORTS)
    if effort:
        args += ["--effort", effort]
    return args


def agy_extra_args() -> List[str]:
    """`--model` / `--effort` for Antigravity, from the console's AI settings (nothing unless chosen there)."""
    if os.environ.get("DIRECTOR_TESTING") == "1":
        return []
    from core import cli_settings
    chosen = cli_settings.choice("antigravity")
    model, effort = chosen["model"], chosen["effort"]
    if model and effort:
        levels = cli_settings.agy_levels(model)
        listed_as_full_id = any(m["id"] == model for m in cli_settings._AGY_MODELS["models"])
        if listed_as_full_id or (levels is not None and effort not in levels):
            effort = None                           # the CLI refuses a full id with --effort, and a level the model lacks
    return [*(["--model", model] if model else []), *(["--effort", effort] if effort else [])]


CLAUDE_AGENT_ARGS = ("--strict-mcp-config", "--disable-slash-commands", "--permission-mode", "bypassPermissions")


def _claude_model_args() -> List[str]:
    if os.environ.get("DIRECTOR_TESTING") == "1":
        return []
    return [a for a in claude_extra_args() if a not in CLAUDE_LIGHT_ARGS]


def claude_agent_argv(executable: str, settings: Optional[str] = None) -> List[str]:
    """Agent-mode Maker: every tool, no permission prompts (the person agreed at install). `settings` is the JSON
    that gives its shell commands Tribunal's PATH (core/agent_guard.py)."""
    return [executable, "--print", "--output-format", "json", *CLAUDE_AGENT_ARGS,
            *(["--settings", settings] if settings else []), *_claude_model_args()]


def codex_agent_argv(executable: str) -> List[str]:
    return [executable, "exec", *codex_model_args(), "--dangerously-bypass-approvals-and-sandbox", "-"]


def agy_agent_argv(executable: str) -> List[str]:
    return [executable, "--input-format", "stream-json", "--output-format", "stream-json",
            "--dangerously-skip-permissions", *agy_extra_args()]


def claude_print_argv(executable: str, json_output: bool = True) -> List[str]:
    return [executable, "--print", *(["--output-format", "json"] if json_output else []), *claude_extra_args()]


def claude_print_description(json_output: bool = True) -> str:
    return " ".join(claude_print_argv("claude", json_output))
