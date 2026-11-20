"""Companion (console) settings: companion.json, overridden by the untracked companion.local.json.

The port lives here so the server, the launcher scripts and `director do` all agree on it. A machine where
8081 is already taken (e.g. by a Docker container) sets {"port": 8181} in companion.local.json.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PORT = 8081


def load_companion_config(root: Path = ROOT) -> dict:
    config = {}
    for name in ("companion.json", "companion.local.json"):
        path = Path(root) / name
        if not path.exists():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError(f"{name} must hold a JSON object")
        config.update(data)
    return config


def companion_port(root: Path = ROOT) -> int:
    return int(load_companion_config(root).get("port", DEFAULT_PORT))


if __name__ == "__main__":          # used by start-companion.sh
    print(companion_port())
