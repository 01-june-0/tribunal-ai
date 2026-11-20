"""Subscription plan and remaining limits of each AI CLI, for the console's "AI settings" panel.

All three are asked the same way: through the CLI itself, with the login the CLI already has, and without calling a
model. This program never reads a login token.

  ANTHROPIC  `claude -p "/usage"` prints the 5-hour ("session") and weekly usage as text; `claude auth status`
             gives the plan.
  OPENAI     `codex app-server` answers account/read (plan) and account/rateLimits/read over stdio. Should that
             fail (an older CLI), the rate-limit state Codex writes into every session record is used instead.
  GOOGLE     `agy -p "/usage" --output-format json` prints the quota groups (5-hour and weekly, per model family).
             The plan is only shown in the interactive banner, so the operator picks it in the panel.

Each source is refreshed in a background thread, at most once per the interval chosen in the panel, so a console
request never waits for a CLI. A source that turns out not to know its usage command — it would pass "/usage" to
the model as a prompt — is switched off for the rest of the process. What a CLI does not report stays unknown; the
panel says so instead of showing a number.
"""
import json
import os
import re
import subprocess
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

FIVE_HOURS, ONE_WEEK = 300, 10080            # minutes
DEFAULT_INTERVAL = 300                       # seconds between look-ups unless the panel says otherwise
_LOCK = threading.Lock()
_CACHE: Dict[str, Any] = {}                  # small synchronous values (plan, session record)


def _testing() -> bool:
    return os.environ.get("DIRECTOR_TESTING") == "1"


def _cached(key: str, seconds: float, produce: Callable[[], Any]) -> Any:
    with _LOCK:
        hit = _CACHE.get(key)
        if hit and time.time() - hit[0] < seconds:
            return hit[1]
    try:
        value = produce()
    except Exception as exc:                     # a broken source is "unknown", never an error page
        value = {"error": type(exc).__name__}
    with _LOCK:
        _CACHE[key] = (time.time(), value)
    return value


class _Source:
    """One CLI's answer, refreshed in the background. `get` returns the last value at once (None before the first)."""

    def __init__(self, name: str, produce: Callable[[], Optional[Dict[str, Any]]]):
        self.name, self.produce = name, produce
        self.value: Optional[Dict[str, Any]] = None
        self.at, self.busy, self.off = 0.0, False, False

    def _refresh(self) -> None:
        try:
            value = self.produce()
        except Exception:
            value = {"state": "lookup_failed"}
        with _LOCK:
            if isinstance(value, dict) and value.pop("off", False):
                self.off = True                  # the CLI does not know the command: never ask again
            self.value, self.at, self.busy = value, time.time(), False

    def get(self, interval: float, wait: bool = False) -> Optional[Dict[str, Any]]:
        with _LOCK:
            due = not self.busy and not self.off and time.time() - self.at >= interval
            if due:
                self.busy = True
        if due:
            if wait:
                self._refresh()
            else:
                threading.Thread(target=self._refresh, name=f"limits-{self.name}", daemon=True).start()
        with _LOCK:
            return dict(self.value) if self.value else None

    def reset(self, keep_value: bool = False) -> None:
        with _LOCK:
            self.at = 0.0
            if not keep_value:
                self.value, self.off = None, False


def _iso(epoch_or_text: Any) -> Optional[str]:
    try:
        if isinstance(epoch_or_text, (int, float)) and not isinstance(epoch_or_text, bool):
            return datetime.fromtimestamp(float(epoch_or_text), timezone.utc).isoformat()
        if isinstance(epoch_or_text, str) and epoch_or_text:
            return datetime.fromisoformat(epoch_or_text.replace("Z", "+00:00")).astimezone(timezone.utc).isoformat()
    except (ValueError, OverflowError, OSError):
        pass
    return None


def _window(used: Any, resets: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(used, (int, float)) or isinstance(used, bool):
        return None
    return {"used_percent": max(0.0, min(100.0, round(float(used), 1))), "resets_at": _iso(resets)}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _run(argv: List[str], timeout: float, cwd: Optional[str] = None) -> subprocess.CompletedProcess:
    from core.env_utils import get_sanitized_env
    return subprocess.run(argv, capture_output=True, text=True, timeout=timeout, env=get_sanitized_env(), cwd=cwd,
                          stdin=subprocess.DEVNULL)


def _json_tail(text: str) -> Any:
    return json.loads(text[text.index("{"):])


# ------------------------------------------------------------------ Claude
_MONTHS = {m: i for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), 1)}
_RESET_RE = re.compile(r"(?:(?P<mon>[A-Za-z]{3})[a-z]*\.? (?P<day>\d{1,2})(?:,? at)? )?(?P<h>\d{1,2})(?::(?P<m>\d{2}))?\s*(?P<ap>am|pm)"
                       r"(?: \((?P<tz>[^)]+)\))?", re.I)
_USED_RE = r"{label}[^\n:]*:\s*(\d+(?:\.\d+)?)% used(?:\s*·\s*resets ([^\n]+))?"


def parse_claude_reset(text: Optional[str], now: Optional[datetime] = None) -> Optional[str]:
    """'Nov 21 at 5:50am (Asia/Seoul)' or '8am (Asia/Seoul)' -> ISO UTC. The CLI prints no year and sometimes no
    date: the next such moment is meant. None when the text is not understood."""
    match = _RESET_RE.search(text or "")
    if not match:
        return None
    try:
        zone = timezone.utc
        if match.group("tz"):
            from zoneinfo import ZoneInfo
            zone = ZoneInfo(match.group("tz").strip())
        now = (now or datetime.now(timezone.utc)).astimezone(zone)
        hour = int(match.group("h")) % 12 + (12 if match.group("ap").lower() == "pm" else 0)
        minute = int(match.group("m") or 0)
        if match.group("mon"):
            month = _MONTHS[match.group("mon").lower()[:3]]
            when = now.replace(month=month, day=int(match.group("day")), hour=hour, minute=minute, second=0, microsecond=0)
            if when < now - timedelta(days=2):
                when = when.replace(year=when.year + 1)
        else:
            when = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if when < now:
                when += timedelta(days=1)
        return when.astimezone(timezone.utc).isoformat()
    except Exception:
        return None


def parse_claude_usage_text(text: Any, now: Optional[datetime] = None) -> Dict[str, Any]:
    """The text `claude -p "/usage"` prints -> the 5-hour ("Current session") and weekly ("Current week (all models)")
    windows. A line that is missing or worded differently leaves that window unknown."""
    text = text if isinstance(text, str) else ""

    def window(label: str):
        match = re.search(_USED_RE.format(label=label), text)
        return _window(float(match.group(1)), None) | {"resets_at": parse_claude_reset(match.group(2), now)} if match else None
    groups = []                                  # weekly limits the CLI lists per model, e.g. "Current week (Fable)"
    for match in re.finditer(_USED_RE.format(label=r"Current week \((?P<model>[^)\n]{1,40})\)"), text):
        if match.group("model").strip().lower() != "all models":
            groups.append({"name": match.group("model").strip(), "five_hour": None,
                           "weekly": _window(float(match.group(2)), None) | {"resets_at": parse_claude_reset(match.group(3), now)}})
    return {"five_hour": window("Current session"), "weekly": window(r"Current week \(all models\)"), "groups": groups}


def _work_dir() -> str:
    """Where the CLIs are started for a look-up: a folder of our own that only this user can write. (A shared temp
    folder could hold project settings planted by someone else, and these runs skip the trust prompt.)"""
    from core.db_path import get_db_path
    folder = Path(get_db_path()).parent / "limits-cwd"
    folder.mkdir(parents=True, exist_ok=True)
    try:
        folder.chmod(0o700)
    except OSError:
        pass
    return str(folder)


def _claude_plan(exe: str) -> Optional[str]:
    data = _json_tail(_run([exe, "auth", "status"], 15).stdout)
    plan = data.get("subscriptionType") if data.get("loggedIn") else None
    return plan if isinstance(plan, str) and plan else None          # nothing else from that output is kept


def _claude_usage() -> Dict[str, Any]:
    from core.env_utils import resolve_cli
    exe = resolve_cli("claude")
    if not exe:
        return {"state": "unavailable"}
    try:
        plan = _claude_plan(exe)
    except Exception:
        plan = None
    # No tools, no MCP servers, no hooks, nothing saved: only the built-in /usage command runs.
    done = _run([exe, "-p", "/usage", "--output-format", "json", "--strict-mcp-config", "--tools", "", "--no-session-persistence",
                 "--settings", '{"disableAllHooks":true}'], 60, cwd=_work_dir())
    data = _json_tail(done.stdout)
    usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
    if data.get("num_turns") or usage.get("output_tokens") or data.get("total_cost_usd"):
        # A model answered: this Claude Code sent "/usage" to the model instead of running it. Never ask again.
        return {"plan": plan, "state": "unavailable", "off": True}
    if "local_command" not in data or data.get("is_error"):
        return {"plan": plan, "state": "lookup_failed"}              # signed out, an error, a changed format: try again later
    parsed = parse_claude_usage_text(data.get("result"))
    return {**parsed, "plan": plan, "state": "ok" if (parsed["five_hour"] or parsed["weekly"]) else "no_record", "as_of": _now()}


# ------------------------------------------------------------------ Codex
def _codex_sessions_dir() -> Path:
    base = os.environ.get("CODEX_HOME")
    return (Path(base).expanduser() if base else Path.home() / ".codex") / "sessions"


def parse_codex_rate_limits(rate_limits: Any) -> Dict[str, Any]:
    """Codex names its windows primary/secondary; which one is the 5-hour or the weekly window is told by its
    length, because a plan may have only one of them."""
    out: Dict[str, Any] = {"plan": None, "five_hour": None, "weekly": None}
    if not isinstance(rate_limits, dict):
        return out
    plan = rate_limits.get("plan_type")
    out["plan"] = plan if isinstance(plan, str) and plan else None
    for name in ("primary", "secondary"):
        window = rate_limits.get(name)
        if not isinstance(window, dict):
            continue
        minutes = window.get("window_minutes")
        parsed = _window(window.get("used_percent"), window.get("resets_at"))
        if not parsed or not isinstance(minutes, (int, float)):
            continue
        if abs(minutes - FIVE_HOURS) <= 60:
            out["five_hour"] = parsed
        elif minutes >= ONE_WEEK * 0.9:
            out["weekly"] = parsed
    return out


def _snake(rate_limits: Any) -> Any:
    """The app server answers in camelCase; the session record uses snake_case. One parser reads both."""
    if not isinstance(rate_limits, dict):
        return rate_limits
    window = lambda w: ({"used_percent": w.get("usedPercent"), "window_minutes": w.get("windowDurationMins"),
                         "resets_at": w.get("resetsAt")} if isinstance(w, dict) else None)
    return {"plan_type": rate_limits.get("planType"), "primary": window(rate_limits.get("primary")),
            "secondary": window(rate_limits.get("secondary"))}


def _codex_rpc(requests: Dict[int, Any], timeout: float = 20.0) -> Dict[int, Any]:
    """Ask `codex app-server` a few read-only questions over stdio and stop it. {request id: result}."""
    from core.env_utils import get_sanitized_env, resolve_cli
    exe = resolve_cli("codex")
    if not exe:
        return {}
    process = subprocess.Popen([exe, "app-server"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                               text=True, env=get_sanitized_env())
    results: Dict[int, Any] = {}
    done = threading.Event()

    def read():
        try:
            for line in process.stdout:
                try:
                    message = json.loads(line)
                except ValueError:
                    continue
                if isinstance(message, dict) and message.get("id") in requests and ("result" in message or "error" in message):
                    results[message["id"]] = message.get("result")      # an error reply counts as answered (None)
                if isinstance(message, dict) and message.get("id") == 0:
                    done.set()                       # initialize answered
                if len(results) == len(requests):
                    done.set()
        except (OSError, ValueError):
            pass                                     # the pipe was closed under us at shutdown
    threading.Thread(target=read, daemon=True).start()
    try:
        send = lambda obj: (process.stdin.write(json.dumps(obj) + "\n"), process.stdin.flush())
        send({"id": 0, "method": "initialize", "params": {"clientInfo": {"name": "tribunal-ai", "title": "Tribunal AI", "version": "1"}}})
        if not done.wait(timeout):
            return {}
        done.clear()
        send({"method": "initialized"})
        for ident, (method, params) in requests.items():
            send({"id": ident, "method": method, **({"params": params} if params is not None else {})})
        done.wait(timeout)
        return dict(results)
    finally:
        try:
            process.stdin.close()
        except Exception:
            pass
        try:
            process.terminate()
            process.wait(timeout=5)
        except Exception:
            try:
                process.kill()
                process.wait(timeout=2)
            except Exception:
                pass


def _codex_live() -> Optional[Dict[str, Any]]:
    """Plan and limits as the CLI reports them right now, or None when it cannot be asked."""
    answers = _codex_rpc({1: ("account/read", {"refreshToken": False}), 2: ("account/rateLimits/read", None)})
    limits = (answers.get(2) or {}).get("rateLimits")
    if not isinstance(limits, dict):
        return None
    parsed = parse_codex_rate_limits(_snake(limits))
    if not parsed["five_hour"] and not parsed["weekly"]:
        return None                              # nothing usable: let the session record speak instead
    account = (answers.get(1) or {}).get("account") or {}
    plan = account.get("planType") if isinstance(account, dict) else None        # nothing else from the account is kept
    if isinstance(plan, str) and plan:
        parsed["plan"] = plan
    return {**parsed, "as_of": _now(), "state": "ok", "source": "live"}


def _latest_codex_rate_limits(max_files: int = 12, tail_bytes: int = 400_000) -> Optional[Dict[str, Any]]:
    root = _codex_sessions_dir()
    try:
        days = sorted((d for d in root.glob("*/*/*") if d.is_dir()), reverse=True)[:8]
    except OSError:
        return None
    files = []
    for day in days:
        try:
            files += [(f.stat().st_mtime, f) for f in day.glob("rollout-*.jsonl")]
        except OSError:
            continue
    for _, path in sorted(files, reverse=True)[:max_files]:
        try:
            with path.open("rb") as fh:
                fh.seek(0, os.SEEK_END)
                fh.seek(max(0, fh.tell() - tail_bytes))
                lines = fh.read().decode("utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line in reversed(lines):
            if '"token_count"' not in line:
                continue
            try:
                record = json.loads(line)
            except ValueError:
                continue
            payload = record.get("payload") if isinstance(record, dict) else None
            if isinstance(payload, dict) and payload.get("type") == "token_count" and payload.get("rate_limits"):
                return {"rate_limits": payload["rate_limits"], "as_of": _iso(record.get("timestamp"))}
    return None


def _codex_record() -> Dict[str, Any]:
    found = _latest_codex_rate_limits()
    if not found:
        return {"plan": None, "five_hour": None, "weekly": None, "as_of": None, "state": "no_record", "source": "record"}
    return {**parse_codex_rate_limits(found["rate_limits"]), "as_of": found["as_of"], "state": "ok", "source": "record"}


# ------------------------------------------------------------------ Antigravity
def parse_agy_usage(data: Any) -> Dict[str, Any]:
    """`agy -p "/usage" --output-format json` -> every quota group by name. The CLI reports what is LEFT
    (remaining_fraction); the console shows what is used, like the other two."""
    groups = []
    raw = (((data or {}).get("command") or {}).get("data") or {}).get("groups") if isinstance(data, dict) else None
    for group in raw if isinstance(raw, list) else []:
        if not isinstance(group, dict):
            continue
        entry = {"name": str(group.get("name") or "")[:60], "five_hour": None, "weekly": None}
        for bucket in group.get("buckets") if isinstance(group.get("buckets"), list) else []:
            left = bucket.get("remaining_fraction") if isinstance(bucket, dict) else None
            if not isinstance(left, (int, float)) or isinstance(left, bool):
                continue
            window = _window((1 - float(left)) * 100, bucket.get("reset_time"))
            if bucket.get("window") == "5h":
                entry["five_hour"] = window
            elif bucket.get("window") == "weekly":
                entry["weekly"] = window
        if entry["five_hour"] or entry["weekly"]:
            groups.append(entry)
    return {"five_hour": None, "weekly": None, "groups": groups}


def _headline_group(groups, model: Optional[str]) -> Dict[str, Any]:
    """The quota group the chosen Antigravity model draws from (by family word in the group's name), else the first."""
    name = (model or "").lower()
    wanted = "argon" if "argon" in name else "claude" if ("claude" in name or "gpt" in name) else None
    if wanted:
        for group in groups:
            if wanted in group["name"].lower():
                return group
    return groups[0] if groups else {}


def _agy_usage() -> Dict[str, Any]:
    from core.env_utils import resolve_cli
    exe = resolve_cli("agy")
    if not exe:
        return {"groups": [], "state": "unavailable"}
    done = _run([exe, "-p", "/usage", "--output-format", "json"], 40, cwd=_work_dir())
    if done.returncode != 0:                     # e.g. 2: signed in with an API key, which has no account quota
        return {"groups": [], "state": "unavailable"}
    data = _json_tail(done.stdout)
    if ((data.get("command") or {}) if isinstance(data, dict) else {}).get("name") != "usage":
        return {"groups": [], "state": "unavailable", "off": True}       # would have gone to the model as a prompt
    parsed = parse_agy_usage(data)
    return {**parsed, "state": "ok" if parsed["groups"] else "no_record", "as_of": _now()}


# ------------------------------------------------------------------ the three sources
_SOURCES = {"claude": _Source("claude", _claude_usage), "openai": _Source("codex", _codex_live),
            "antigravity": _Source("agy", _agy_usage)}


def clear_cache() -> None:
    """Forget everything (tests, and nothing else)."""
    with _LOCK:
        _CACHE.clear()
    for source in _SOURCES.values():
        source.reset()
    _LAST_REFRESH[0] = 0.0


_LAST_REFRESH = [0.0]
REFRESH_MIN_SECONDS = 30


def refresh_now() -> bool:
    """The panel's "check now": the next request starts a look-up for every source; shown values stay until then.
    Not more often than every REFRESH_MIN_SECONDS, however often it is pressed. Returns whether it was accepted."""
    with _LOCK:
        if time.time() - _LAST_REFRESH[0] < REFRESH_MIN_SECONDS:
            return False
        _LAST_REFRESH[0] = time.time()
    for source in _SOURCES.values():
        source.reset(keep_value=True)
    return True


def _blank(state: str) -> Dict[str, Any]:
    return {"plan": None, "five_hour": None, "weekly": None, "as_of": None, "state": state}


def claude_limits(interval: float = DEFAULT_INTERVAL, wait: bool = False) -> Dict[str, Any]:
    if _testing():
        return {**_blank("unavailable"), "groups": []}
    out = {**_blank("loading"), "groups": []}
    value = _SOURCES["claude"].get(interval, wait)
    if value:
        out.update(value)
    return out


def codex_limits(interval: float = DEFAULT_INTERVAL, wait: bool = False) -> Dict[str, Any]:
    """The live answer when there is one, else the newest session record."""
    record = _cached("codex", 30, _codex_record)
    if "error" in record:
        record = {**_blank("no_record"), "source": "record"}
    if _testing():
        return record
    live = _SOURCES["openai"].get(interval, wait)
    return live if live and live.get("state") == "ok" else record


def antigravity_limits(model: Optional[str] = None, interval: float = DEFAULT_INTERVAL, wait: bool = False) -> Dict[str, Any]:
    out = {**_blank("unavailable"), "groups": []}
    if _testing():
        return out
    value = _SOURCES["antigravity"].get(interval, wait)
    if value is None:
        out["state"] = "loading"
        return out
    out.update(value)
    out.setdefault("groups", [])
    headline = _headline_group(out["groups"], model)
    out.update(five_hour=headline.get("five_hour"), weekly=headline.get("weekly"), headline=headline.get("name"))
    return out


def alerts(limits: Dict[str, Any], thresholds: Dict[str, int]) -> List[Dict[str, Any]]:
    """Every window at or over its CLI's warning threshold: [{"cli", "window", "used_percent", "threshold", "resets_at"}]."""
    found = []
    now = _now()
    for cli, value in limits.items():
        threshold = thresholds.get(cli)
        if not isinstance(threshold, (int, float)):
            continue
        if not isinstance(value, dict):
            continue
        headline = value.get("headline")
        places = [(None, value)] + [(g.get("name"), g) for g in value.get("groups") or [] if isinstance(g, dict) and g.get("name") != headline]
        for group, holder in places:
            for window in ("five_hour", "weekly"):
                entry = holder.get(window)
                reset = _iso(entry.get("resets_at")) if isinstance(entry, dict) else None
                if reset and reset < now:
                    continue                         # that window has reset since it was read: the number is history
                if isinstance(entry, dict) and entry.get("used_percent", 0) >= threshold:
                    found.append({"cli": cli, "window": window, "group": group, "used_percent": entry["used_percent"],
                                  "threshold": threshold, "resets_at": entry.get("resets_at")})
    return found


def snapshot(antigravity_model: Optional[str] = None, interval: float = DEFAULT_INTERVAL) -> Dict[str, Any]:
    return {"claude": claude_limits(interval), "openai": codex_limits(interval),
            "antigravity": antigravity_limits(antigravity_model, interval)}
