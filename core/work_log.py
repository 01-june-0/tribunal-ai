"""One record of the work: AI calls, what Tribunal did itself (tests, stops, endings) and the user's decisions,
merged by time for the console (`rows`), plus everything known about one line (`detail`).

Read-only. Every value comes from a record that exists — the usage ledger, the state transitions, the audit log or
a run's own files. A file's content is tied to a call or a test round only when the file was written inside that
call's or round's time window; otherwise the value is left out, never guessed."""
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

TERMINAL = ("PASS", "FAIL", "TIMEOUT", "HUMAN_REQUIRED")
HUMAN_ACTIONS = ("HUMAN_APPROVAL", "HUMAN_REJECTED", "RESULT_APPLY_COMPLETED", "RESULT_DISCARDED")
KEY_RE = re.compile(r"^(call|tr|au)-(\d{1,12})$")
RUN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,119}$")
SLACK_SEC = 10                         # a result file is written just after the call that produced it returns
TAIL_CHARS = 2400
TEXT_CHARS = 1600
LIST_MAX = 40


def _conn() -> sqlite3.Connection:
    from core import usage
    return usage._conn()               # the ledger and the run records live in the same database


def _runs_dir() -> Path:
    from core.db_path import SOURCE_ROOT
    return SOURCE_ROOT / "runs"


def _run_dir(run_id: Any) -> Optional[Path]:
    if not isinstance(run_id, str) or not RUN_RE.match(run_id) or ".." in run_id:
        return None
    path = _runs_dir() / run_id
    return path if path.is_dir() else None


def _epoch(text: Optional[str]) -> Optional[float]:
    """Ledger and transition times are naive UTC."""
    try:
        return datetime.fromisoformat(str(text)).replace(tzinfo=timezone.utc).timestamp()
    except (TypeError, ValueError):
        return None


def _read(run_id: Any, name: str, start: Optional[str] = None, end: Optional[str] = None) -> Optional[dict]:
    """A run's JSON file. With a window, only when the file was written inside it (it then belongs to that call or
    round and not to a later one that overwrote it)."""
    folder = _run_dir(run_id)
    if not folder:
        return None
    path = folder / name
    try:
        if start is not None:
            first, last, written = _epoch(start), _epoch(end), path.stat().st_mtime
            if first is None or written < first - 1 or (last is not None and written > last + SLACK_SEC):
                return None
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _text(value: Any, limit: int = TEXT_CHARS) -> str:
    text = str(value or "").strip()
    return text if len(text) <= limit else text[:limit] + "…"


def _strings(value: Any, limit: int = LIST_MAX, chars: int = 300) -> List[str]:
    return [_text(x, chars) for x in (value if isinstance(value, list) else [])][:limit]


def _counts(verification: Optional[dict]) -> Optional[dict]:
    counts = (verification or {}).get("test_counts")
    if isinstance(counts, dict) and all(isinstance(counts.get(k), int) for k in ("passed", "failed", "total")):
        return {"passed": counts["passed"], "failed": counts["failed"], "total": counts["total"]}
    return None


def model_of(argv: List[str]) -> Tuple[str, str]:
    """(model, effort) as given on the command line; "" means the CLI's own default was used."""
    model = effort = ""
    args = [str(a) for a in (argv or [])]
    for i, arg in enumerate(args):
        nxt = args[i + 1] if i + 1 < len(args) else ""
        if arg in ("--model", "-m") and nxt:
            model = nxt
        elif arg == "--effort" and nxt:
            effort = nxt
        elif arg == "-c" and nxt.startswith("model_reasoning_effort="):
            effort = nxt.split("=", 1)[1].strip('"\'')
    return model[:80], effort[:40]


# ------------------------------------------------------------------ which task a line belongs to

def _mission_index() -> Dict[str, Any]:
    from core.mission import MissionStore
    by_run, goals = {}, {}
    try:
        for m in MissionStore().all():
            goals[m.get("mission_id")] = str(m.get("goal") or "")
            for s in m.get("steps", []):
                if s.get("run_id"):
                    by_run[s["run_id"]] = (m.get("mission_id"), s.get("index"))
    except Exception:
        pass
    return {"by_run": by_run, "goals": goals}


def _group(conn, index, run_id: Optional[str], mission_id: Optional[str], cache: dict) -> dict:
    """{key, title, project, step}: a mission when there is one, else the run, else the conversation."""
    step = None
    if run_id and run_id in index["by_run"]:
        mission_id, step = index["by_run"][run_id]
    project = ""
    if run_id:
        if run_id not in cache:
            row = conn.execute("SELECT goal, project_path FROM runs WHERE run_id=?", (run_id,)).fetchone()
            cache[run_id] = (str(row["goal"] or ""), Path(row["project_path"] or "").name) if row else ("", "")
        project = cache[run_id][1]
    if mission_id:
        return {"key": mission_id, "title": _text(index["goals"].get(mission_id) or (cache.get(run_id) or ("",))[0], 160),
                "project": project, "step": step}
    if run_id:
        return {"key": run_id, "title": _text(cache[run_id][0], 160), "project": project, "step": None}
    return {"key": "chat", "title": "", "project": "", "step": None}


# ------------------------------------------------------------------ what a call or a round produced

RESULT_FILE = {"PLANNING": "order.json", "ENTRY_REVIEW": "order.json", "BUILDING": "maker.json",
               "REVIEWING": "review.json", "DECIDING": "decision.json"}


def _window_end(conn, row) -> str:
    """Until when a file can still be this call's: the next call of the run or the run's next step, whichever comes
    first (the engine may save a result a while after the CLI returned, e.g. after running the inspector's tests)."""
    end = row["ended_at"]
    nxt_call = conn.execute("SELECT MIN(started_at) FROM ai_usage WHERE run_id=? AND started_at>=? AND id!=?",
                            (row["run_id"], end, row["id"])).fetchone()[0]
    nxt_step = conn.execute("SELECT MIN(timestamp) FROM state_transitions WHERE run_id=? AND timestamp>=?",
                            (row["run_id"], end)).fetchone()[0]
    return min([t for t in (nxt_call, nxt_step) if t] or [end])


def _round_entry(conn, run_id: str, after: str) -> Optional[dict]:
    """The repair_history entry of the round a review or decision led to: the first "correction round k" step after
    `after`, provided no new test run came in between (then the call belongs to a later cycle)."""
    for s in conn.execute("SELECT to_state, details FROM state_transitions WHERE run_id=? AND timestamp>=? ORDER BY id", (run_id, after)):
        if s["to_state"] == "VERIFYING":
            return None
        match = re.search(r"correction round (\d+)", str(s["details"] or ""))
        if s["to_state"] == "BUILDING" and match:
            folder = _run_dir(run_id)
            try:
                history = json.loads((folder / "repair_history.json").read_text(encoding="utf-8")) if folder else []
            except (OSError, ValueError):
                return None
            for entry in history if isinstance(history, list) else []:
                if isinstance(entry, dict) and entry.get("round") == int(match.group(1)):
                    return entry
            return None
    return None


def _call_result(conn, row) -> Optional[dict]:
    """What this very call produced, from the file written in its own window."""
    stage, run_id, start = row["stage"], row["run_id"], row["started_at"]
    if not run_id or not row["ended_at"] or row["status"] != "OK" or stage not in RESULT_FILE:
        return None
    end = _window_end(conn, row)
    if stage in ("PLANNING", "ENTRY_REVIEW"):
        order = _read(run_id, "order.json", start, end)
        if order:
            return {"type": "order", "goal": _text(order.get("goal")), "allowed": _strings(order.get("allowed_paths")),
                    "criteria": _strings(order.get("acceptance_criteria")), "needs_approval": bool(order.get("requires_human_approval")),
                    "risk": _text(order.get("risk_level"), 20)}
    elif stage == "BUILDING":
        maker = _read(run_id, "maker.json", start, end)
        if maker:
            return {"type": "build", "files": _strings(maker.get("files_modified")), "summary": _text(maker.get("summary")),
                    "status": _text(maker.get("status"), 40), "error": _text(maker.get("error"), 400)}
    elif stage == "REVIEWING":
        review, kept = _read(run_id, "review.json", start, end), False
        if not review:                               # an earlier round: what it answered is kept with the repair it led to
            entry = _round_entry(conn, run_id, row["ended_at"]) or {}
            review, kept = (entry.get("review") if isinstance(entry.get("review"), dict) else None), True
        if review:
            findings = [{"level": level, "text": text} for level in ("p0", "p1", "p2") for text in _strings(review.get(level), 20, 500)]
            return {"type": "review", "verdict": _text(review.get("verdict"), 40), "findings": findings, "summary": _text(review.get("summary")),
                    "file": "repair_history.json" if kept else "review.json"}
    elif stage == "DECIDING":
        decision, kept = _read(run_id, "decision.json", start, end), False
        if not decision:
            entry = _round_entry(conn, run_id, row["ended_at"]) or {}
            decision, kept = (entry.get("architect") if isinstance(entry.get("architect"), dict) else None), True
        if decision:
            # The engine may change the ARCHITECT's answer before saving it (final gate, proxy): then the file is
            # Tribunal's final decision, not what this call said, and is labelled so.
            changed = str(decision.get("rationale") or "").startswith("Overridden by Orchestrator") or bool(conn.execute(
                "SELECT 1 FROM audit_logs WHERE run_id=? AND action IN ('FINAL_GATE_BLOCK','ARCHITECT_ESCALATION_RESOLVED_BY_PROXY') "
                "AND timestamp>=? AND timestamp<=? LIMIT 1", (run_id, start, end)).fetchone())
            return {"type": "decision", "decision": _text(decision.get("decision"), 40), "rationale": _text(decision.get("rationale")),
                    "next_steps": _strings(decision.get("next_steps"), 10, 400), "changed_by_tribunal": changed,
                    "file": "repair_history.json" if kept else "decision.json"}
    return None


def _result_brief(result: Optional[dict]) -> Optional[dict]:
    """The few words the list shows."""
    if not result:
        return None
    kind = result["type"]
    if kind == "build":
        return {"type": kind, "files": len(result["files"])}
    if kind == "review":
        return {"type": kind, "verdict": result["verdict"], "findings": len(result["findings"])}
    if kind == "decision":
        return {"type": kind, "decision": result["decision"], "changed_by_tribunal": result["changed_by_tribunal"]}
    return {"type": kind, "needs_approval": result.get("needs_approval")}


def _verify_round(conn, tr) -> Tuple[Optional[dict], int, int]:
    """(verification, nth, count) for one transition into VERIFYING; nth 0 means the run was stopped before any test
    ran. Repair round k keeps the test result it reacted
    to in repair_history.json: that is the last test run before the step "correction round k". A test run that no
    repair round followed is verification.json, when the file was written in that run's own window. Anything else
    (a run reopened after an approval, a retried step) has no record that can be tied to it."""
    steps = conn.execute("SELECT id, to_state, details, timestamp FROM state_transitions WHERE run_id=? ORDER BY id", (tr["run_id"],)).fetchall()
    # The Scope Guard looks at the change first; when it stops the run there, no test was run in that phase.
    guarded = {s["id"] for s, nxt in zip(steps, steps[1:]) if s["to_state"] == "VERIFYING"
               and nxt["to_state"] == "HUMAN_REQUIRED" and str(nxt["details"] or "").startswith("Scope violation: ")}
    tests = [s["id"] for s in steps if s["to_state"] == "VERIFYING" and s["id"] not in guarded]
    if tr["id"] in guarded:
        return None, 0, len(tests)                   # nth 0: stopped before the tests
    nth, count = tests.index(tr["id"]) + 1, len(tests)
    after = [s for s in steps if s["id"] > tr["id"]]
    round_no = None
    for s in after:                                  # the first correction round after this test run, if no other test run came first
        if s["to_state"] == "VERIFYING":
            break
        match = re.search(r"correction round (\d+)", str(s["details"] or ""))
        if s["to_state"] == "BUILDING" and match:
            round_no = int(match.group(1))
            break
    if round_no is not None:
        folder = _run_dir(tr["run_id"])
        try:
            history = json.loads((folder / "repair_history.json").read_text(encoding="utf-8")) if folder else []
        except (OSError, ValueError):
            history = []
        for entry in history if isinstance(history, list) else []:
            if isinstance(entry, dict) and entry.get("round") == round_no and isinstance(entry.get("verification"), dict):
                return entry["verification"], nth, count
        return None, nth, count
    if any(s["to_state"] == "VERIFYING" for s in after):
        return None, nth, count                      # a later test run wrote over verification.json
    return _read(tr["run_id"], "verification.json", tr["timestamp"], after[0]["timestamp"] if after else None), nth, count


# ------------------------------------------------------------------ the list

def _call_row(conn, index, cache, r) -> dict:
    return {"key": f"call-{r['id']}", "kind": "ai", "id": r["id"], "at": r["ended_at"] or r["started_at"],
            "provider": r["provider"], "role": r["role"], "stage": r["stage"], "status": r["status"],
            "seconds": r["duration_sec"], "tokens": r["tokens_total"], "exact": bool(r["tokens_exact"]),
            "run_id": r["run_id"], "result": _result_brief(_call_result(conn, r)),
            "group": _group(conn, index, r["run_id"], r["mission_id"], cache)}


def rows(limit: int = 40) -> List[dict]:
    """The newest lines of all three kinds, newest first."""
    limit = max(1, min(int(limit), 200))
    index, cache, out, floors = _mission_index(), {}, [], []
    with _conn() as conn:
        calls = conn.execute("SELECT * FROM ai_usage WHERE status!='RUNNING' ORDER BY COALESCE(ended_at, started_at) DESC, id DESC LIMIT ?",
                             (limit,)).fetchall()
        live = conn.execute("SELECT * FROM ai_usage WHERE status='RUNNING' ORDER BY id DESC LIMIT 10").fetchall()
        out += [_call_row(conn, index, cache, r) for r in live]
        out += [_call_row(conn, index, cache, r) for r in calls]
        trans = conn.execute(
            "SELECT * FROM state_transitions WHERE to_state IN ('VERIFYING','PASS','FAIL','TIMEOUT','HUMAN_REQUIRED') "
            "ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        for t in trans:
            row = {"key": f"tr-{t['id']}", "kind": "sys", "at": t["timestamp"], "run_id": t["run_id"],
                   "group": _group(conn, index, t["run_id"], None, cache)}
            if t["to_state"] == "VERIFYING":
                found, nth, rounds = _verify_round(conn, t)
                test = (found or {}).get("test") if isinstance((found or {}).get("test"), dict) else {}
                row.update(event="verify", round=nth, rounds=rounds, known=found is not None, skipped=nth == 0,
                           passed=found.get("passed") if found else None, counts=_counts(found),
                           ran=bool(test.get("executed")) if found else None)
            else:
                row.update(event="end", state=t["to_state"],
                           stage="ENTRY" if str(t["details"] or "").startswith("APPROVAL_REQUIRED") else None)
            out.append(row)
        marks = ",".join("?" * len(HUMAN_ACTIONS))
        audits = conn.execute(f"SELECT * FROM audit_logs WHERE action IN ({marks}) ORDER BY id DESC LIMIT ?",
                              (*HUMAN_ACTIONS, limit)).fetchall()
        for a in audits:
            out.append({"key": f"au-{a['id']}", "kind": "me", "at": a["timestamp"], "run_id": a["run_id"], "action": a["action"],
                        "group": _group(conn, index, a["run_id"], None, cache)})
        # A source that filled its quota may have older lines we did not read: nothing older than that is shown,
        # so the list never has a stretch where one kind is silently missing.
        for got in (calls, trans, audits):
            if len(got) == limit:
                last = got[-1]
                floors.append(str((last["ended_at"] or last["started_at"]) if got is calls else last["timestamp"]))
    floor = max(floors) if floors else ""
    out = [r for r in out if str(r["at"] or "") >= floor or r.get("status") == "RUNNING"]   # a call still at work is always a line
    out.sort(key=lambda r: str(r["at"] or ""), reverse=True)
    return out[:limit]


# ------------------------------------------------------------------ one line in full

def _call_detail(row_id: int) -> dict:
    from core import call_activity
    out = call_activity.activity(row_id)
    out["key"], out["kind"] = f"call-{row_id}", "ai"
    if not out.get("known"):
        return out
    with _conn() as conn:
        r = conn.execute("SELECT * FROM ai_usage WHERE id=?", (row_id,)).fetchone()
        have = set(r.keys())
        out.update(tokens_in=r["tokens_in"], tokens_out=r["tokens_out"], tokens=r["tokens_total"], exact=bool(r["tokens_exact"]),
                   prompt_chars=r["prompt_chars"], output_chars=r["output_chars"], exit_code=r["exit_code"],
                   model=r["model"] if "model" in have else None, effort=r["effort"] if "effort" in have else None,
                   run_id=r["run_id"], backfilled=r["source"] == "backfill",
                   group=_group(conn, _mission_index(), r["run_id"], r["mission_id"], {}))
        out["result"] = _call_result(conn, r)
        # A finished call of a stage that saves a file, and no file of its own: said as that, without a guessed cause.
        out["result_missing"] = (out["result"] is None and bool(r["run_id"]) and r["status"] == "OK"
                                 and r["stage"] in RESULT_FILE and bool(r["ended_at"]))
    out["sources"] = ["ledger"] + ([out["source"]] if out.get("found") else []) + \
        ([(out["result"] or {}).get("file") or {"order": "order.json", "build": "maker.json"}.get(out["result"]["type"], "")] if out["result"] else [])
    return out


def _run_totals(conn, run_id: str, until: str) -> dict:
    """The run's calls up to `until` (an ending that was resumed later does not count what came after it)."""
    calls = conn.execute("SELECT COUNT(*) AS n, SUM(tokens_total) AS tokens, MIN(tokens_exact) AS exact, SUM(duration_sec) AS sec "
                         "FROM ai_usage WHERE run_id=? AND status!='RUNNING' AND started_at<=?", (run_id, until)).fetchone()
    return {"calls": calls["n"] or 0, "tokens": calls["tokens"], "exact": bool(calls["exact"]) if calls["n"] else None,
            "cli_seconds": calls["sec"]}


def _transition_detail(tr_id: int) -> dict:
    with _conn() as conn:
        t = conn.execute("SELECT * FROM state_transitions WHERE id=?", (tr_id,)).fetchone()
        if not t or t["to_state"] not in ("VERIFYING",) + TERMINAL:
            return {"key": f"tr-{tr_id}", "known": False}
        run_id = t["run_id"]
        out: Dict[str, Any] = {"key": f"tr-{tr_id}", "kind": "sys", "known": True, "at": t["timestamp"], "run_id": run_id,
                               "group": _group(conn, _mission_index(), run_id, None, {})}
        if t["to_state"] == "VERIFYING":
            found, nth, rounds = _verify_round(conn, t)
            nxt = conn.execute("SELECT timestamp FROM state_transitions WHERE run_id=? AND id>? ORDER BY id LIMIT 1",
                               (run_id, tr_id)).fetchone()
            out.update(event="verify", round=nth, rounds=rounds, found=found is not None, skipped=nth == 0,
                       ended_at=nxt["timestamp"] if nxt else None)
            if found:
                test = found.get("test") if isinstance(found.get("test"), dict) else {}
                out["test"] = {"command": _text(test.get("command"), 300) or None, "ran": bool(test.get("executed")),
                               "passed": test.get("passed"), "exit_code": test.get("exit_code"),
                               "output_tail": str(test.get("output") or "")[-TAIL_CHARS:]}
                out["passed"], out["counts"] = found.get("passed"), _counts(found)
                out["changed"] = [line for line in str(found.get("git_status") or "").splitlines() if line.strip()][:LIST_MAX]
                out["missing_outputs"] = _strings(found.get("required_outputs_missing"))
                baseline = _read(run_id, "baseline_verification.json")
                out["baseline"] = {"passed": baseline.get("passed"), "counts": _counts(baseline)} if baseline else None
            later_test = conn.execute("SELECT 1 FROM state_transitions WHERE run_id=? AND to_state='VERIFYING' AND id>? LIMIT 1", (run_id, tr_id)).fetchone()
            out["sources"] = (["repair_history.json" if later_test else "verification.json", "baseline_verification.json"]) if found else ["transitions"]
            return out
        first = conn.execute("SELECT timestamp FROM state_transitions WHERE run_id=? ORDER BY id LIMIT 1", (run_id,)).fetchone()
        latest = conn.execute("SELECT id FROM state_transitions WHERE run_id=? ORDER BY id DESC LIMIT 1", (run_id,)).fetchone()
        is_last = bool(latest and latest["id"] == tr_id)
        out.update(event="end", state=t["to_state"], from_state=t["from_state"], details=_text(t["details"], 3000),
                   started_at=first["timestamp"] if first else None, is_last=is_last, totals=_run_totals(conn, run_id, t["timestamp"]),
                   repairs=conn.execute("SELECT COUNT(*) FROM state_transitions WHERE run_id=? AND from_state='DECIDING' AND to_state='BUILDING' AND id<?",
                                        (run_id, tr_id)).fetchone()[0])
        sources = ["transitions", "ledger"]
        if t["to_state"] == "HUMAN_REQUIRED":
            reason = str(t["details"] or "")             # the same two prefixes Orchestrator.approval_state goes by
            out["stage"] = ("ENTRY" if reason.startswith("APPROVAL_REQUIRED") else "POST_BUILD" if reason.startswith("Scope violation: ")
                            else "FINAL" if reason.startswith("Final decision") and t["from_state"] == "DECIDING" else None)
            decided = conn.execute("SELECT action, timestamp FROM audit_logs WHERE run_id=? AND action IN ('HUMAN_APPROVAL','HUMAN_REJECTED') "
                                   "AND timestamp>=? ORDER BY id LIMIT 1", (run_id, t["timestamp"])).fetchone()
            nxt = conn.execute("SELECT timestamp FROM state_transitions WHERE run_id=? AND id>? ORDER BY id LIMIT 1", (run_id, tr_id)).fetchone()
            if decided and (not nxt or decided["timestamp"] <= nxt["timestamp"]):      # an answer to this stop, not to a later one
                out["answer"] = {"action": decided["action"], "at": decided["timestamp"]}
        if is_last:                                   # the run ended here: its closing files describe this ending
            before = conn.execute("SELECT timestamp FROM state_transitions WHERE run_id=? AND id<? ORDER BY id DESC LIMIT 1", (run_id, tr_id)).fetchone()
            since = before["timestamp"] if before else t["timestamp"]
            evidence = _read(run_id, "final_evidence.json", since, t["timestamp"])
            if evidence:
                out["gates"] = {k: str(v)[:40] for k, v in evidence.items() if k in (
                    "order_paths", "canonical_containment", "baseline", "verification", "regression", "inspector_verdict", "architect_decision")}
                out["gate_reasons"] = _strings(evidence.get("reasons"), 10, 400)
                sources.append("final_evidence.json")
            summary = _read(run_id, "result_summary.json", since, t["timestamp"])
            if summary and isinstance(summary.get("counts"), dict):
                out["changed_counts"] = {k: summary["counts"].get(k) for k in ("A", "M", "D")}
                out["changed"] = [{"path": _text(f.get("path"), 300), "status": _text(f.get("type") or f.get("status"), 4)}
                                  for f in (summary.get("changed_files") or []) if isinstance(f, dict)][:LIST_MAX]
                sources.append("result_summary.json")
        out["sources"] = sources
        return out


def _audit_detail(audit_id: int) -> dict:
    with _conn() as conn:
        a = conn.execute("SELECT * FROM audit_logs WHERE id=?", (audit_id,)).fetchone()
        if not a or a["action"] not in HUMAN_ACTIONS:
            return {"key": f"au-{audit_id}", "known": False}
        try:
            payload = json.loads(a["payload"] or "{}")
        except ValueError:
            payload = {}
        payload = payload if isinstance(payload, dict) else {}
        out = {"key": f"au-{audit_id}", "kind": "me", "known": True, "at": a["timestamp"], "run_id": a["run_id"], "action": a["action"],
               "group": _group(conn, _mission_index(), a["run_id"], None, {}),
               "stage": _text(payload.get("stage") or payload.get("approval_stage"), 20) or None,
               "reason": _text(payload.get("reason") or payload.get("approval_reason"), 1200),
               "scope": _strings(payload.get("approved_scope")), "gates": _strings(payload.get("approved_gates"), 20, 80),
               "files": _strings(payload.get("files") or payload.get("applied_files")), "note": _text(payload.get("note"), 300),
               "verified": _counts(payload.get("verification") if isinstance(payload.get("verification"), dict) else None),
               "sources": ["audit"]}
        if a["action"] in ("HUMAN_APPROVAL", "HUMAN_REJECTED"):
            after = conn.execute("SELECT to_state, timestamp FROM state_transitions WHERE run_id=? AND timestamp>=? ORDER BY id LIMIT 1",
                                 (a["run_id"], a["timestamp"])).fetchone()
            out["resumed"] = bool(after)              # a transition after the decision: the run went on
            out["maker_ran"] = bool(conn.execute("SELECT 1 FROM state_transitions WHERE run_id=? AND to_state='BUILDING' LIMIT 1",
                                                 (a["run_id"],)).fetchone())
        return out


def detail(key: Any) -> dict:
    match = KEY_RE.match(str(key or ""))
    if not match:
        raise ValueError("unknown record key")
    number = int(match.group(2))
    return {"call": _call_detail, "tr": _transition_detail, "au": _audit_detail}[match.group(1)](number)
