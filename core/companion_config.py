"""Companion (console) settings and where the console is actually listening.

Port choice
  companion.json holds the default (8081). When nothing else is said and that port is busy, the server takes the
  next free one — so a machine where 8081 belongs to something else (a Docker container, say) needs no setup.
  A port the operator chose — companion.local.json {"port": N} or the TRIBUNAL_PORT environment variable — is
  never changed behind their back: if it is busy the server stops and says so.

Where it ended up
  The running server writes data/companion.port; `active_port()` returns it while that server still answers, so
  the launcher scripts and `director do` find the console wherever it is.

Is that really our console?
  Another program may be listening on the port. `probe()` asks GET /ops/hello; `verify()` adds a challenge that
  only a server holding this installation's bridge token can answer, so the token is never sent to a stranger.
"""
import hashlib
import hmac
import json
import os
import secrets
import socket
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PORT = 8081
APP_ID = "tribunal-ai"
PORT_TRIES = 20                      # default port .. default port + 19
RUNTIME_FILE = Path("data") / "companion.port"


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


def bridge_token_path(root: Path = ROOT) -> Path:
    """data/bridge.token — the local secret a request must carry to change anything. A token file from before the
    rename is moved over once, so open consoles and scripts keep working across the upgrade."""
    path = Path(root) / "data" / "bridge.token"
    old = Path(root) / "data" / "solomon-bridge.token"
    if old.exists() and not path.exists():
        try:
            old.replace(path)
        except OSError:
            return path if path.exists() else old       # another process moved it first, or it cannot be moved at all
    return path


def _valid_port(value: Any) -> int:
    port = int(value)
    if not 1 <= port <= 65535:
        raise ValueError(f"port out of range: {port}")
    return port


def configured_port(root: Path = ROOT) -> Tuple[int, bool]:
    """(port, chosen by the operator?). Only a port that was not chosen may be moved when it is busy."""
    env = (os.environ.get("TRIBUNAL_PORT") or "").strip()
    if env:
        return _valid_port(env), True
    local = Path(root) / "companion.local.json"
    if local.exists():
        data = json.loads(local.read_text(encoding="utf-8"))
        if isinstance(data, dict) and "port" in data:
            return _valid_port(data["port"]), True
    return _valid_port(load_companion_config(root).get("port", DEFAULT_PORT)), False


def companion_port(root: Path = ROOT) -> int:
    """The configured port (see active_port for where a running console really is)."""
    return configured_port(root)[0]


def install_id(root: Path = ROOT) -> str:
    """Tells two checkouts of this program apart without revealing the folder."""
    return hashlib.sha256(str(Path(root).resolve()).encode("utf-8")).hexdigest()[:16]


def hello_proof(token: str, nonce: str) -> str:
    return hmac.new(token.encode("utf-8"), nonce.encode("utf-8"), hashlib.sha256).hexdigest()


def hello_payload(root: Path, token: str, nonce: str = "") -> Dict[str, Any]:
    """What GET /ops/hello answers. The proof is only computed for a well-formed nonce."""
    payload: Dict[str, Any] = {"app": APP_ID, "install": install_id(root), "pid": os.getpid()}
    if nonce and len(nonce) <= 128 and nonce.isalnum():
        payload["proof"] = hello_proof(token, nonce)
    return payload


def _port_open(port: int, timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except OSError:
        return False


def local_open(request, timeout: float):
    """urlopen for the console on this machine. HTTP_PROXY and friends are ignored on purpose: a request to
    127.0.0.1 — above all one that carries the bridge token — must never travel through a proxy."""
    return urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request, timeout=timeout)


def _get_json(port: int, path: str, timeout: float = 2.0) -> Optional[dict]:
    try:
        with local_open(f"http://127.0.0.1:{port}{path}", timeout) as response:
            data = json.loads(response.read(1024 * 1024).decode("utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _hello(port: int, nonce: str = "", timeout: float = 2.0) -> Optional[dict]:
    data = _get_json(port, "/ops/hello" + (f"?nonce={nonce}" if nonce else ""), timeout)
    return data if data and data.get("app") == APP_ID else None


def probe(port: int, root: Path = ROOT) -> str:
    """'free' — nothing listens; 'ours' — this installation's console; 'legacy' — a console from before
    /ops/hello existed (it cannot say which folder it serves); 'other' — anything else."""
    if not _port_open(port):
        return "free"
    hello = _hello(port)
    if hello:
        return "ours" if hello.get("install") == install_id(root) else "other"
    state = _get_json(port, "/ops/state")              # an older console: it has /ops/state (csrf + orders) but no /ops/hello
    return "legacy" if state and "csrf" in state and "orders" in state else "other"


def verify(port: int, token: str) -> bool:
    """True only when the listener proves it holds this installation's bridge token."""
    if not token:
        return False
    nonce = secrets.token_hex(16)
    hello = _hello(port, nonce)
    return bool(hello and isinstance(hello.get("proof"), str)
                and hmac.compare_digest(hello["proof"], hello_proof(token, nonce)))


def choose_port(root: Path = ROOT) -> Tuple[str, int, str]:
    """('bind', port, note) to start on that port, ('running', port, '') when our console is already there, or
    ('blocked', port, reason) when the operator's chosen port is taken (or no port in the range is free)."""
    wanted, chosen = configured_port(root)
    recorded = recorded_port(root)              # a console that moved to another port earlier is still ours
    if recorded and probe(recorded, root) == "ours":
        return "running", recorded, ""
    last = min(65535, wanted + PORT_TRIES - 1)
    for port in ([wanted] if chosen else range(wanted, last + 1)):
        state = probe(port, root)
        if state == "ours":
            return "running", port, ""
        if state == "legacy":
            return "blocked", port, (f"an older Tribunal AI / AI DEV DIRECTOR console is already running on port {port}. "
                                     "Stop it first (stop-companion), then start again.")
        if state == "free":
            return "bind", port, "" if port == wanted else f"port {wanted} is in use by another program; using {port}"
        if chosen:
            return "blocked", port, (f"port {port} is in use by another program. It was set explicitly (TRIBUNAL_PORT or "
                                     "companion.local.json), so it is not changed automatically: free it, choose another, "
                                     "or remove the setting to let the console pick a free port.")
    return "blocked", wanted, f"no free port between {wanted} and {last}"


def write_runtime(root: Path, port: int) -> None:
    path = Path(root) / RUNTIME_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"port": port, "pid": os.getpid()}), encoding="utf-8")


def clear_runtime(root: Path) -> None:
    """Remove the runtime file, but only our own (a second start that found the console running must not)."""
    path = Path(root) / RUNTIME_FILE
    try:
        if json.loads(path.read_text(encoding="utf-8")).get("pid") == os.getpid():
            path.unlink()
    except (OSError, ValueError, AttributeError):
        pass


def recorded_port(root: Path = ROOT) -> Optional[int]:
    """The port in data/companion.port, or None. The file may be stale: probe before trusting it."""
    try:
        return _valid_port(json.loads((Path(root) / RUNTIME_FILE).read_text(encoding="utf-8"))["port"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def active_port(root: Path = ROOT) -> int:
    """Where this installation's console is listening right now, else the configured port."""
    port = recorded_port(root)
    if port and probe(port, root) == "ours":
        return port
    return companion_port(root)


if __name__ == "__main__":          # used by the launcher scripts
    print(active_port())
