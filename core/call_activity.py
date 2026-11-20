"""What an AI CLI is doing *inside* one call: the tools it runs and what it says, while the call is still going.

The work ledger (core.usage) knows that a call started and how it ended; this module fills in the middle from
records the CLIs already produce. Everything here is read-only except the small Antigravity trace file.

  ANTHROPIC  Claude Code's session transcript  <config>/projects/*/<session-id>.jsonl
             (the runner adds `--session-id <uuid>` so the file is found without guessing)
  OPENAI     Codex's rollout file  <codex home>/sessions/YYYY/MM/DD/rollout-*.jsonl
             (matched by working directory and start time — the CLI offers no way to name it up front)
  GOOGLE     Antigravity prints stream-json events on stdout; each is summarised as it arrives into
             <data>/call_traces/<ledger id>.ndjson  (the raw stream, which holds whole files, is not kept)

These formats are internal to each CLI and can change between versions: unknown lines are skipped, so a format
change shows up as missing events, never as a failed call or a crashed console.

Event: {"at": ISO-8601 UTC or None, "kind": "tool" | "say" | "think" | "done", "name": str, "detail": str,
        "error": bool}. Text is clipped; prompts and file contents are never copied into an event.
"""
import json
import os
import re
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

MAX_EVENTS = 200                      # what one answer carries (the newest ones)
DETAIL_CHARS = 160
MAX_FILE_BYTES = 20 * 1024 * 1024     # a transcript bigger than this is not read
TRACE_KEEP_DAYS = 14
_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_codex_file_cache: Dict[Tuple[str, int], str] = {}     # finished Codex call -> its rollout path ("" = none found)


# ------------------------------------------------------------------ small helpers
def _short(text: Any, limit: int = DETAIL_CHARS) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[:limit - 1] + "…"


def _real(path: Optional[str]) -> str:
    try:
        return os.path.realpath(path) if path else ""
    except OSError:
        return path or ""


def _rel(path: Any, cwd: Optional[str]) -> str:
    """A path as the reader wants it: relative to the call's folder, else with the home folder as ~."""
    text = str(path or "")
    if text.startswith("file://"):
        text = text[7:]
    for base, prefix in ((_real(cwd), ""), (cwd or "", ""), (str(Path.home()), "~/")):
        if base and (text == base or text.startswith(base.rstrip("/\\") + os.sep)):
            rest = text[len(base):].lstrip("/\\")
            return (prefix + rest) if rest else "."
    return text


def _tidy(text: Any, cwd: Optional[str]) -> str:
    """Command text with the call's own folder shortened, clipped."""
    text = str(text or "")
    for base in {_real(cwd), cwd or ""}:
        if base:
            text = text.replace(base.rstrip("/\\") + os.sep, "").replace(base, ".")
    return _short(text.replace(str(Path.home()) + os.sep, "~/"))


def _event(at: Optional[str], kind: str, name: str = "", detail: str = "", error: bool = False) -> Dict[str, Any]:
    return {"at": at, "kind": kind, "name": _short(name, 40), "detail": detail, "error": bool(error)}


def _json_lines(path: Path):
    try:
        if path.stat().st_size > MAX_FILE_BYTES:
            return
        with path.open(encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    record = json.loads(line)
                except ValueError:
                    continue                      # a half-written last line, or a format we do not know
                if isinstance(record, dict):
                    yield record
    except OSError:
        return


# ------------------------------------------------------------------ before / during the call (process runner)
def prepare(provider: str, argv: List[str]) -> Tuple[List[str], Optional[str]]:
    """(argv to run, trace id to store). Claude gets a session id of our choosing; the others are unchanged."""
    if provider == "ANTHROPIC" and "--print" in argv and "--session-id" not in argv:
        session_id = str(uuid.uuid4())
        return [*argv, "--session-id", session_id], session_id
    return argv, None


def _trace_dir() -> Path:
    from core.db_path import get_db_path
    return Path(get_db_path()).parent / "call_traces"


def summarize_agy_line(line: str, cwd: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """One Antigravity stream-json line -> an event, or None when the line carries nothing worth showing."""
    try:
        record = json.loads(line)
    except ValueError:
        return None
    if not isinstance(record, dict):
        return None
    now = datetime.utcnow().isoformat()
    if record.get("event") == "result":
        result = record.get("result") or {}
        status = str(result.get("status") or "")
        return _event(now, "done", "", _short(status, 40), error=status not in ("", "SUCCESS"))
    step = record.get("step_update") if record.get("event") == "step_update" else None
    if not isinstance(step, dict):
        return None
    if step.get("step_type") == "tool" and step.get("state") == "ACTIVE":
        info = step.get("tool_info") or {}
        params = info.get("parameters") if isinstance(info.get("parameters"), dict) else {}
        target = next((params[k] for k in ("Path", "AbsolutePath", "TargetFile", "CommandLine", "Query", "Url")
                       if params.get(k)), None)
        is_path = isinstance(target, str) and (target.startswith("/") or target.startswith("file://"))
        return _event(now, "tool", step.get("tool_name") or info.get("name") or "tool",
                      _short(_rel(target, cwd)) if is_path else _tidy(target, cwd))
    if step.get("step_type") == "agent_response" and step.get("state") == "DONE" and step.get("usage"):
        return _event(now, "think")
    return None


def stream_recorder(provider: str, row_id: Optional[int], cwd: Optional[str]) -> Optional[Callable[[str], None]]:
    """A per-line stdout callback for the process runner (Antigravity only). It must never raise."""
    if provider != "GOOGLE" or not row_id:
        return None
    try:
        folder = _trace_dir()
        folder.mkdir(parents=True, exist_ok=True)
        cutoff = time.time() - TRACE_KEEP_DAYS * 86400
        for old in folder.glob("*.ndjson"):
            if old.stat().st_mtime < cutoff:
                old.unlink(missing_ok=True)
        target = folder / f"{int(row_id)}.ndjson"
        target.write_text("", encoding="utf-8")     # a ledger id reused after a database reset starts clean
    except Exception:
        return None

    def record(line: str) -> None:
        try:
            event = summarize_agy_line(line, cwd)
            if event:
                with target.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(event, ensure_ascii=False) + "\n")
        except Exception:
            pass
    return record


# ------------------------------------------------------------------ reading: Claude
def _claude_projects_dir() -> Path:
    base = os.environ.get("CLAUDE_CONFIG_DIR")
    return (Path(base).expanduser() if base else Path.home() / ".claude") / "projects"


def _claude_tool_detail(tool_input: Any, cwd: Optional[str]) -> str:
    if not isinstance(tool_input, dict):
        return ""
    for key in ("file_path", "path", "notebook_path"):
        if tool_input.get(key):
            extra = tool_input.get("pattern")
            return _short((f"{extra}  in  " if extra else "") + _rel(tool_input[key], cwd))
    for key in ("pattern", "command", "query", "url", "description"):
        if tool_input.get(key):
            return _tidy(tool_input[key], cwd)
    return ""


def claude_events(session_id: Optional[str], cwd: Optional[str] = None) -> Optional[List[Dict[str, Any]]]:
    """Events of one Claude session, or None when its transcript is not there (yet)."""
    if not session_id or not _UUID_RE.match(session_id):
        return None
    try:
        files = list(_claude_projects_dir().glob(f"*/{session_id}.jsonl"))
    except OSError:
        files = []
    if not files:
        return None
    events: List[Dict[str, Any]] = []
    by_tool_id: Dict[str, Dict[str, Any]] = {}
    for record in _json_lines(files[0]):
        if record.get("isSidechain"):
            continue
        content = (record.get("message") or {}).get("content")
        if not isinstance(content, list):
            continue
        at = record.get("timestamp")
        for block in content:
            if not isinstance(block, dict):
                continue
            kind = block.get("type")
            if record.get("type") == "assistant" and kind == "tool_use":
                event = _event(at, "tool", block.get("name") or "tool", _claude_tool_detail(block.get("input"), cwd))
                by_tool_id[str(block.get("id"))] = event
                events.append(event)
            elif record.get("type") == "assistant" and kind == "text" and str(block.get("text") or "").strip():
                events.append(_event(at, "say", "", _short(block.get("text"))))
            elif record.get("type") == "assistant" and kind == "thinking":
                events.append(_event(at, "think"))
            elif record.get("type") == "user" and kind == "tool_result" and block.get("is_error"):
                event = by_tool_id.get(str(block.get("tool_use_id")))
                if event:
                    event["error"] = True
    return events


# ------------------------------------------------------------------ reading: Codex
def _codex_sessions_dir() -> Path:
    base = os.environ.get("CODEX_HOME")
    return (Path(base).expanduser() if base else Path.home() / ".codex") / "sessions"


def _utc(text: Optional[str]) -> Optional[datetime]:
    """Ledger times are naive UTC; CLI times end in Z. Both come back as aware UTC."""
    if not text:
        return None
    try:
        stamp = datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except ValueError:
        return None
    return stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)


def _first_record(path: Path) -> Optional[dict]:
    try:
        with path.open(encoding="utf-8", errors="replace") as fh:
            record = json.loads(fh.readline(4 * 1024 * 1024))
        return record if isinstance(record, dict) else None
    except (OSError, ValueError):
        return None


_ROLLOUT_NAME_RE = re.compile(r"^rollout-(\d{4})-(\d\d)-(\d\d)T(\d\d)-(\d\d)-(\d\d)-")


def _name_time(path: Path) -> Optional[datetime]:
    """The local start time Codex puts in the file name, as aware UTC (None for a name we do not know)."""
    match = _ROLLOUT_NAME_RE.match(path.name)
    if not match:
        return None
    try:
        return datetime(*map(int, match.groups())).astimezone().astimezone(timezone.utc)
    except (ValueError, OSError):
        return None


def find_codex_rollout(cwd: Optional[str], started_at: Optional[str], ended_at: Optional[str] = None,
                       taken: Optional[set] = None) -> Optional[Path]:
    """The rollout file of the `codex exec` that began in `cwd` right after `started_at`.
    Day folders are named in local time, so the day before and after are searched too. `taken` holds files
    already attributed to other calls: one rollout never explains two calls."""
    start = _utc(started_at)
    if not cwd or not start:
        return None
    end = _utc(ended_at) or datetime.now(timezone.utc)
    taken = taken or set()
    root, want, best = _codex_sessions_dir(), _real(cwd), None
    local = start.astimezone()
    for day in (local - timedelta(days=1), local, local + timedelta(days=1)):
        folder = root / f"{day.year:04d}" / f"{day.month:02d}" / f"{day.day:02d}"
        try:
            names = sorted(folder.glob("rollout-*.jsonl"))
        except OSError:
            continue
        for path in names:
            if str(path) in taken:
                continue
            named = _name_time(path)                # cheap filter before any file is opened
            if named and (named < start - timedelta(seconds=90) or named > end + timedelta(seconds=90)):
                continue
            meta = _first_record(path)
            payload = (meta or {}).get("payload") if (meta or {}).get("type") == "session_meta" else None
            if not isinstance(payload, dict) or _real(payload.get("cwd")) != want:
                continue
            began = _utc(payload.get("timestamp") or meta.get("timestamp"))
            if not began or began < start - timedelta(seconds=2) or began > end + timedelta(seconds=2):
                continue
            gap = abs((began - start).total_seconds())
            if best is None or gap < best[0]:
                best = (gap, path)
    return best[1] if best else None


def codex_events(path: Path, cwd: Optional[str] = None) -> List[Dict[str, Any]]:
    events: List[Dict[str, Any]] = []
    for record in _json_lines(path):
        payload = record.get("payload")
        if record.get("type") != "event_msg" or not isinstance(payload, dict):
            continue
        at = record.get("timestamp")
        if payload.get("type") == "task_complete":
            events.append(_event(at, "done"))
            continue
        item = payload.get("item") if payload.get("type") == "item_completed" else None
        if not isinstance(item, dict):
            continue
        kind = item.get("type")
        if kind == "CommandExecution":
            parsed = item.get("parsed_cmd")
            command = parsed[0].get("cmd") if isinstance(parsed, list) and parsed and isinstance(parsed[0], dict) else None
            if not command:
                raw = item.get("command")
                command = raw[-1] if isinstance(raw, list) and raw else raw
            events.append(_event(at, "tool", "exec", _tidy(command, cwd), error=item.get("exit_code") not in (0, None)))
        elif kind == "AgentMessage":
            parts = item.get("content") if isinstance(item.get("content"), list) else []
            text = " ".join(str(p.get("text") or "") for p in parts if isinstance(p, dict))
            if text.strip():
                events.append(_event(at, "say", "", _short(text)))
        elif kind == "Reasoning":
            events.append(_event(at, "think"))
        elif kind and kind != "UserMessage":
            events.append(_event(at, "tool", kind, ""))
    return events


# ------------------------------------------------------------------ reading: Antigravity trace
def agy_events(row_id: int) -> Optional[List[Dict[str, Any]]]:
    path = _trace_dir() / f"{int(row_id)}.ndjson"
    if not path.exists():
        return None
    return [e for e in _json_lines(path) if e.get("kind")]


# ------------------------------------------------------------------ one call, for the console
def activity(row_id: int) -> Dict[str, Any]:
    """Everything the console shows for one ledger row. `found` is False when the CLI's own record is not
    available — the call may be seconds old, older than this feature, or the CLI changed its format."""
    from core import usage
    row = usage.call_row(row_id)
    if not row:
        return {"id": row_id, "known": False, "found": False, "events": [], "total": 0}
    provider, cwd = row["provider"], row["cwd"]
    events: Optional[List[Dict[str, Any]]] = None
    source = {"ANTHROPIC": "transcript", "OPENAI": "rollout", "GOOGLE": "stream"}.get(provider, "")
    try:
        if provider == "ANTHROPIC":
            events = claude_events(row["trace_id"], cwd)
        elif provider == "OPENAI":
            key = (str(_trace_dir()), row_id)       # ledger ids restart in another database
            cached = _codex_file_cache.get(key)
            if cached is None:
                others = {p for k, p in _codex_file_cache.items() if k != key and p}
                path = find_codex_rollout(cwd, row["started_at"], row["ended_at"], taken=others)
                # While the call runs its own file may not exist yet, so nothing is remembered until it ends;
                # for a finished call a miss is remembered too, so old calls are not searched on every poll.
                if row["status"] != "RUNNING":
                    _codex_file_cache[key] = str(path) if path else ""
                    if len(_codex_file_cache) > 500:
                        _codex_file_cache.pop(next(iter(_codex_file_cache)))
            else:
                path = Path(cached) if cached else None
            if path:
                events = codex_events(path, cwd)
        elif provider == "GOOGLE":
            events = agy_events(row_id)
    except Exception:
        events = None                               # never let a strange record break the console
    found = events is not None
    events = events or []
    # How long since the CLI last showed a sign of life (a fact, not a verdict: long thinking is quiet too).
    # Without the CLI's record we do not know, and say nothing.
    quiet = None
    if row["status"] == "RUNNING" and found:
        began = _utc(row["started_at"])
        last = max([t for t in (_utc(e.get("at")) for e in events) if t] + ([began] if began else []), default=None)
        if last:
            quiet = max(0, int((datetime.now(timezone.utc) - last).total_seconds()))
    return {"id": row_id, "known": True, "found": found, "source": source, "quiet_sec": quiet,
            "provider": provider, "provider_name": usage.PROVIDER_NAME.get(provider, provider),
            "role": row["role"], "stage": row["stage"], "status": row["status"],
            "started_at": row["started_at"], "ended_at": row["ended_at"], "seconds": row["duration_sec"],
            "total": len(events), "tools": sum(1 for e in events if e["kind"] == "tool"),
            "errors": sum(1 for e in events if e.get("error")), "events": events[-MAX_EVENTS:]}
