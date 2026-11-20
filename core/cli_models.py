"""Per-machine model choice for the subscription CLIs, kept out of the tracked config.

config.local.yaml (untracked):

    cli_models:
      codex: gpt-6.1-sol      # passed as `codex exec -m gpt-6.1-sol`; omit to use the CLI's own default

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


def cli_model(name: str) -> Optional[str]:
    """The configured model for 'codex' (or another CLI name), or None. Unit tests never read the local file."""
    if os.environ.get("DIRECTOR_TESTING") == "1":
        return None
    try:
        data = yaml.safe_load(LOCAL_CONFIG.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return None
    value = ((data.get("cli_models") or {}) if isinstance(data, dict) else {}).get(name)
    if not isinstance(value, str) or not _MODEL_RE.match(value.strip()):
        return None                       # also keeps anything flag-shaped ("-c ...") off the command line
    return value.strip()


def codex_model_args() -> List[str]:
    model = cli_model("codex")
    return ["-m", model] if model else []


def codex_exec_argv(executable: str) -> List[str]:
    return [executable, "exec", *codex_model_args(), "--sandbox", "read-only", "-"]


def codex_exec_description() -> str:
    return " ".join(["codex", "exec", *codex_model_args(), "--sandbox", "read-only", "-", "<stdin>"])
