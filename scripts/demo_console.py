"""A console full of invented work, for screenshots, recordings and trying the interface.

    python scripts/demo_console.py                 # http://127.0.0.1:8190 , Ctrl+C to stop
    python scripts/demo_console.py --port 8200 --dir /tmp/tribunal-demo --no-live

Real records hold your prompts, file names and folder paths, so they do not belong in a public picture. This
script builds a separate data set (its own database, missions, CLI transcripts) in a throwaway folder and serves
the normal console on top of it, read-only: the demo server refuses every change (chat, role changes, project
selection, apply/discard, the bridge), so nothing reaches the real data folder, the real projects or an AI.
Every number, goal and command you see is made up here.

With the default "live" mode one mission keeps running: the three AIs take turns, tools scroll by in the
"호출 안" panel and the time estimate fills, so the stage is never idle while you capture it.
"""
import argparse
import json
import os
import secrets
import sys
import tempfile
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROJECT = "/home/demo/projects/paper-crane"            # never created; only its last part is shown
WORKTREE = PROJECT + "/.director_worktrees/RUN-DEMO"

CLAUDE, CODEX, AGY = "ANTHROPIC", "OPENAI", "GOOGLE"
EXE = {CLAUDE: "claude", CODEX: "codex", AGY: "agy"}

# What each kind of call "does": (kind, name, detail, failed). Written out in the format of the CLI that made it.
ARCHITECT_PLAN = [("think", "", "", False), ("tool", "Read", "README.md", False), ("tool", "Glob", "src/**/*.py", False),
             ("tool", "Read", "src/settings/theme.py", False), ("say", "", "설정 화면 구조를 확인했습니다. 다음 단계의 작업 지시서를 씁니다.", False)]
ARCHITECT_DECIDE = [("think", "", "", False), ("tool", "Read", "tests/test_theme.py", False),
               ("say", "", '{"decision": "PASS", "rationale": "수용 기준 6개를 모두 충족했고 테스트 41개가 통과했습니다."}', False)]
BUILD = [("think", "", "", False), ("tool", "read_file", "src/settings/theme.py", False), ("tool", "read_file", "src/settings/view.py", False),
         ("think", "", "", False), ("tool", "write_file", "src/settings/theme.py", False), ("tool", "write_file", "src/settings/view.py", False),
         ("tool", "write_file", "tests/test_theme.py", False), ("think", "", "", False)]
REVIEW = [("say", "", "작업 지시서와 diff를 대조하고 테스트 근거를 확인하겠습니다.", False), ("tool", "exec", "git status --short", False),
          ("tool", "exec", "git diff HEAD -- src/settings tests/test_theme.py", False), ("think", "", "", False),
          ("tool", "exec", "rg -n 'prefers-color-scheme|set_theme' src tests", False), ("tool", "exec", "python3 -m pytest -q tests/test_theme.py", True),
          ("tool", "exec", "git diff HEAD --check", False),
          ("say", "", '{"verdict": "pass", "p0": [], "p1": [], "p2": ["토글 상태 저장 키 이름을 상수로 빼면 좋습니다."]}', False)]


def utc(dt):
    return dt.replace(tzinfo=None).isoformat()


def zulu(dt):
    return dt.replace(tzinfo=None).isoformat(timespec="milliseconds") + "Z"


class Demo:
    def __init__(self, folder: Path):
        self.dir = folder
        os.environ["TRIBUNAL_DB_PATH"] = str(folder / "director.db")
        os.environ["CLAUDE_CONFIG_DIR"] = str(folder / "claude")
        os.environ["CODEX_HOME"] = str(folder / "codex")
        os.environ.pop("DIRECTOR_TESTING", None)
        sys.path.insert(0, str(ROOT))
        from core import call_activity, usage
        from core.chat_manager import ChatManager
        from core.state_machine import StateMachine
        self.usage, self.activity = usage, call_activity
        StateMachine()                                   # creates the tables
        self.chat = ChatManager()
        self.lock = threading.Lock()
        self.started = time.time()

    # ---- low-level writers
    def sql(self, statement, params=()):
        with self.lock, self.usage._conn() as conn:
            cur = conn.execute(statement, params)
            conn.commit()
            return cur.lastrowid

    def start_call(self, provider, role, stage, began, mission, run):
        trace = str(uuid.uuid4()) if provider == CLAUDE else None
        row = self.sql("INSERT INTO ai_usage (started_at, status, provider, role, stage, run_id, mission_id, pid, prompt_chars, cwd, trace_id) "
                       "VALUES (?, 'RUNNING', ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                       (utc(began), provider, role, stage, run, mission, os.getpid(), 4200, WORKTREE, trace))
        if provider == CLAUDE:
            path = self.dir / "claude" / "projects" / "-home-demo-projects-paper-crane" / f"{trace}.jsonl"
        elif provider == CODEX:
            local = began.astimezone()
            path = (self.dir / "codex" / "sessions" / f"{local:%Y}" / f"{local:%m}" / f"{local:%d}"
                    / f"rollout-{local:%Y-%m-%dT%H-%M-%S}-{uuid.uuid4()}.jsonl")
        else:
            path = self.dir / "call_traces" / f"{row}.ndjson"
        path.parent.mkdir(parents=True, exist_ok=True)
        first = {"timestamp": zulu(began), "type": "session_meta", "payload": {"cwd": WORKTREE, "timestamp": zulu(began)}}
        path.write_text(json.dumps(first) + "\n" if provider == CODEX else "", encoding="utf-8")
        return {"row": row, "provider": provider, "path": path, "n": 0}

    def add_event(self, call, event, at):
        kind, name, detail, failed = event
        call["n"] += 1
        stamp, lines = zulu(at), []
        if call["provider"] == CLAUDE:
            if kind == "tool":
                key = "file_path" if name == "Read" else "pattern" if name in ("Glob", "Grep") else "command"
                value = WORKTREE + "/" + detail if key == "file_path" else detail
                ident = f"t{call['n']}"
                lines.append({"type": "assistant", "timestamp": stamp, "message": {"content": [
                    {"type": "tool_use", "id": ident, "name": name, "input": {key: value}}]}})
                if failed:
                    lines.append({"type": "user", "timestamp": stamp, "message": {"content": [
                        {"type": "tool_result", "tool_use_id": ident, "is_error": True}]}})
            else:
                block = {"type": "text", "text": detail} if kind == "say" else {"type": "thinking", "thinking": ""}
                lines.append({"type": "assistant", "timestamp": stamp, "message": {"content": [block]}})
        elif call["provider"] == CODEX:
            item = ({"type": "CommandExecution", "command": ["/bin/sh", "-lc", detail], "exit_code": 1 if failed else 0} if kind == "tool"
                    else {"type": "AgentMessage", "content": [{"type": "Text", "text": detail}]} if kind == "say" else {"type": "Reasoning"})
            lines.append({"timestamp": stamp, "type": "event_msg", "payload": {"type": "item_completed", "item": item}})
        else:
            lines.append({"at": utc(at), "kind": kind, "name": name, "detail": detail, "error": failed})
        with call["path"].open("a", encoding="utf-8") as fh:
            for line in lines:
                fh.write(json.dumps(line, ensure_ascii=False) + "\n")

    def finish_call(self, call, ended, seconds, tokens, exact=True):
        if call["provider"] == CODEX:
            self.add_raw(call, {"timestamp": zulu(ended), "type": "event_msg", "payload": {"type": "task_complete"}})
        elif call["provider"] == AGY:
            self.add_raw(call, {"at": utc(ended), "kind": "done", "name": "", "detail": "SUCCESS", "error": False})
        self.sql("UPDATE ai_usage SET ended_at=?, status='OK', duration_sec=?, output_chars=?, tokens_in=?, tokens_out=?, "
                 "tokens_total=?, tokens_exact=?, exit_code=0 WHERE id=?",
                 (utc(ended), seconds, 900, int(tokens * .9), int(tokens * .1), tokens, 1 if exact else 0, call["row"]))

    @staticmethod
    def add_raw(call, record):
        with call["path"].open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    def past_call(self, provider, role, stage, began, seconds, tokens, events, mission, run, exact=True):
        call = self.start_call(provider, role, stage, began, mission, run)
        for i, event in enumerate(events):
            self.add_event(call, event, began + timedelta(seconds=seconds * (i + 1) / (len(events) + 1)))
        self.finish_call(call, began + timedelta(seconds=seconds), seconds, tokens, exact)
        return began + timedelta(seconds=seconds + 2)

    def run_row(self, run, goal, created, state):
        self.sql("INSERT INTO runs (run_id, project_path, goal, current_state, worktree_path, branch_name, created_at, updated_at) "
                 "VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (run, PROJECT, goal, state, WORKTREE, "director/demo", utc(created), utc(created)))

    def move(self, run, state, at, details=""):
        self.sql("INSERT INTO state_transitions (run_id, from_state, to_state, details, timestamp) VALUES (?, '', ?, ?, ?)",
                 (run, state, details, utc(at)))
        self.sql("UPDATE runs SET current_state=?, updated_at=? WHERE run_id=?", (state, utc(at), run))

    def mission_file(self, mission):
        folder = self.dir / "missions"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{mission['mission_id']}.json").write_text(json.dumps(mission, ensure_ascii=False, indent=2), encoding="utf-8")

    # ---- the story
    def one_step(self, mission, run, goal, t, tests, first=False):
        """A whole passed step: plan -> build -> test -> review -> decide. Returns the time it ended."""
        self.run_row(run, goal, t, "PLANNING")
        self.move(run, "PLANNING", t)
        t = self.past_call(CLAUDE, "ARCHITECT", "CHAT" if first else "MISSION_PLANNING", t, 11 if first else 9, 11200, ARCHITECT_PLAN, mission, None if first else None)
        self.move(run, "BUILDING", t)
        t = self.past_call(AGY, "MAKER", "BUILDING", t, 31, 6400, BUILD, mission, run, exact=False)
        self.move(run, "VERIFYING", t, f"Tests: {tests} passed")
        t += timedelta(seconds=6)
        self.move(run, "REVIEWING", t)
        t = self.past_call(CODEX, "INSPECTOR", "REVIEWING", t, 24, 9800, REVIEW, mission, run)
        self.move(run, "DECIDING", t)
        t = self.past_call(CLAUDE, "ARCHITECT", "DECIDING", t, 8, 12100, ARCHITECT_DECIDE, mission, run)
        self.move(run, "PASS", t, "Final decision: 수용 기준을 모두 충족했습니다.")
        return t

    def step_record(self, index, run, goal, tests, state="PASS"):
        result = {"run_id": run, "final_state": state, "tests": {"passed": tests, "failed": 0, "total": tests},
                  "review_verdict": "pass", "repair_rounds": 0} if state else None
        return {"index": index, "order": {"goal": goal}, "run_id": run, "result": result}

    def seed(self, now):
        sid = "demo-session"
        self.chat.create_session(sid, PROJECT, CLAUDE)
        finished = [
            ("MSN-DEMO-0001", now - timedelta(hours=5), "캡션 글자 수 검사기를 만들어줘. 플랫폼별 최대 글자 수를 넘으면 경고한다.",
             ["플랫폼별 글자 수 한도 표와 검사 함수 추가", "명령줄에서 파일을 받아 검사하는 진입점 추가"], [18, 27]),
            ("MSN-DEMO-0002", now - timedelta(hours=2), "CSV 내보내기에 날짜 범위 필터를 추가해줘.",
             ["내보내기 함수에 시작일·종료일 인자 추가", "잘못된 날짜 범위 입력 처리와 테스트 보강", "README 사용 예 갱신"], [31, 36, 36]),
        ]
        for mid, began, goal, steps, tests in finished:
            t, records = began, []
            for i, (step_goal, count) in enumerate(zip(steps, tests), 1):
                run = f"RUN-DEMO-{mid[-4:]}-{i}"
                t = self.one_step(mid, run, step_goal, t, count, first=(i == 1)) + timedelta(seconds=4)
                records.append(self.step_record(i, run, step_goal, count))
            self.mission_file({"mission_id": mid, "project_path": PROJECT, "goal": goal, "status": "DONE", "created_at": utc(began),
                               "updated_at": utc(t), "max_steps": len(steps), "profile": "standard", "source": "chat",
                               "base_worktree": WORKTREE, "summary": goal.rstrip(".") + " — 완료했습니다.", "owner_pid": None,
                               "applied": {"status": "applied"}, "steps": records})
            self.chat.add_message(sid, "USER", goal)
            self.chat.add_message(sid, "ARCHITECT", f"작업 완료 ({len(steps)}/{len(steps)} 단계 통과) 목표: {goal}")

        # the mission that is running right now: step 1 passed a few minutes ago, step 2 is in progress
        mid, began = "MSN-DEMO-0003", now - timedelta(minutes=4)
        goal = "설정 화면에 다크 모드 전환을 추가해줘. 시스템 설정을 기본으로 따르고, 선택은 저장한다."
        step1, step2 = "테마 상태 모듈과 저장 로직 추가", "설정 화면에 전환 스위치 연결"
        t = self.one_step(mid, "RUN-DEMO-0003-1", step1, began, 41, first=True)
        self.live = {"mission": mid, "run": "RUN-DEMO-0003-2"}
        self.run_row(self.live["run"], step2, t, "PLANNING")
        self.mission_file({"mission_id": mid, "project_path": PROJECT, "goal": goal, "status": "RUNNING", "created_at": utc(began),
                           "updated_at": utc(now), "max_steps": 3, "profile": "standard", "source": "chat", "base_worktree": None,
                           "summary": "", "owner_pid": os.getpid(), "applied": None,
                           "steps": [self.step_record(1, "RUN-DEMO-0003-1", step1, 41), self.step_record(2, self.live["run"], step2, 0, state=None)]})
        self.chat.add_message(sid, "USER", goal)
        self.chat.add_message(sid, "ARCHITECT", "1단계를 통과했습니다. 2단계로 설정 화면에 전환 스위치를 연결합니다.")

    def close_live_mission(self):
        """--no-live: nothing is running, so the open mission ends after its first step and its second run goes."""
        path = self.dir / "missions" / f"{self.live['mission']}.json"
        mission = json.loads(path.read_text(encoding="utf-8"))
        mission.update(status="DONE", owner_pid=None, steps=mission["steps"][:1], max_steps=1, summary="1단계까지 완료했습니다.",
                       base_worktree=WORKTREE, applied={"status": "applied"})
        path.write_text(json.dumps(mission, ensure_ascii=False), encoding="utf-8")
        self.sql("DELETE FROM state_transitions WHERE run_id=?", (self.live["run"],))
        self.sql("DELETE FROM runs WHERE run_id=?", (self.live["run"],))

    def live_loop(self, stop):
        """Keeps step 2 of the running mission busy: one AI at a time, with tools appearing as the call goes on."""
        stages = [(AGY, "MAKER", "BUILDING", 26, 6400, BUILD, False), (None, None, "VERIFYING", 6, 0, [], True),
                  (CODEX, "INSPECTOR", "REVIEWING", 20, 9800, REVIEW, True), (CLAUDE, "ARCHITECT", "DECIDING", 9, 12100, ARCHITECT_DECIDE, True),
                  (CLAUDE, "ARCHITECT", "MISSION_PLANNING", 10, 11200, ARCHITECT_PLAN, True)]
        while not stop.is_set():
            try:
                self.live_cycle(stages, stop)
                self.prune()
            except Exception as exc:                     # e.g. a locked database: say so and try the next round
                print(f"demo live loop: {exc}", file=sys.stderr, flush=True)
                try:
                    self.sql("UPDATE ai_usage SET status='OK', ended_at=started_at, duration_sec=0 WHERE status='RUNNING'")
                except Exception:
                    pass
                if stop.wait(5):
                    return

    def prune(self, keep_calls=60, keep_minutes=30):
        """The loop may run for hours: keep the newest live calls and drop the files of the rest."""
        self.sql("DELETE FROM ai_usage WHERE run_id=? AND id NOT IN (SELECT id FROM ai_usage WHERE run_id=? ORDER BY id DESC LIMIT ?)",
                 (self.live["run"], self.live["run"], keep_calls))
        self.sql("DELETE FROM state_transitions WHERE run_id=? AND id NOT IN (SELECT id FROM state_transitions WHERE run_id=? "
                 "ORDER BY id DESC LIMIT ?)", (self.live["run"], self.live["run"], keep_calls))
        cutoff = time.time() - keep_minutes * 60
        for folder in ("claude", "codex", "call_traces"):
            for path in (self.dir / folder).rglob("*.*json*"):
                modified = path.stat().st_mtime
                if self.started < modified < cutoff:     # never the seeded history
                    path.unlink(missing_ok=True)

    def live_cycle(self, stages, stop):
        if True:
            for provider, role, stage, seconds, tokens, events, exact in stages:
                began = datetime.now(timezone.utc)
                if stage != "MISSION_PLANNING":
                    self.move(self.live["run"], stage, began)
                if not provider:
                    if stop.wait(seconds):
                        return
                    continue
                call = self.start_call(provider, role, stage, began, self.live["mission"], self.live["run"])
                gap = seconds / (len(events) + 1)
                for event in events:
                    if stop.wait(gap):
                        return
                    self.add_event(call, event, datetime.now(timezone.utc))
                if stop.wait(gap):
                    return
                self.finish_call(call, datetime.now(timezone.utc), seconds, tokens, exact)
                if stop.wait(1.5):
                    return


def block_real_ai_calls():
    from core.process_runner import ProcessTreeRunner

    def refuse(*args, **kwargs):
        raise RuntimeError("demo console: AI calls are disabled (this data is invented)")
    ProcessTreeRunner.run = classmethod(lambda cls, *a, **k: refuse())


DEMO_ROLES = {"architect": "claude", "maker": "antigravity", "inspector": "openai"}
READ_ONLY = {"error": "demo console: read-only (invented data)", "message": "데모 콘솔은 보기 전용입니다."}


def demo_ai():
    soon = lambda hours: (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()
    window = lambda used, hours: {"used_percent": used, "resets_at": soon(hours)}
    efforts = ["low", "medium", "high", "xhigh", "max"]
    choice = lambda model, effort, plan=None: {"model": model, "effort": effort, "plan": plan, "warn_percent": 80}
    gemini = {"name": "Gemini Models", "five_hour": window(8.0, 1.2), "weekly": window(27.0, 120)}
    return {
        "settings": {"claude": choice("sonnet", "medium"), "openai": choice(None, "high"),
                     "antigravity": choice("gemini-4-neon", "high", "ai_pro"), "usage_poll_minutes": 5},
        "options": {"poll_minutes": [1, 5, 10, 30],
                    "claude": {"models": [{"id": m, "name": m} for m in ("fable", "opus", "sonnet", "haiku")], "efforts": efforts, "plans": []},
                    "openai": {"models": [{"id": "gpt-6.2-sol", "name": "GPT-6.2-Sol"}], "efforts": efforts, "plans": []},
                    "antigravity": {"models": [{"id": "gemini-4-neon", "name": "Gemini 4 Neon", "efforts": ["low", "medium", "high"]}],
                                    "efforts": efforts, "plans": [{"id": "ai_pro", "name": "Google AI Pro"}, {"id": "ai_ultra", "name": "Google AI Ultra"}]}},
        "limits": {"claude": {"plan": "max", "five_hour": window(42.0, 2.2), "weekly": window(61.0, 70), "state": "ok", "as_of": soon(0)},
                   "openai": {"plan": "plus", "five_hour": window(18.0, 3.5), "weekly": window(86.0, 40), "state": "ok", "source": "live", "as_of": soon(0)},
                   "antigravity": {"plan": None, **{k: gemini[k] for k in ("five_hour", "weekly")}, "state": "ok", "headline": "Gemini Models", "as_of": soon(0),
                                   "groups": [gemini, {"name": "Claude and GPT models", "five_hour": window(0.0, 4), "weekly": window(3.0, 150)}]}},
        "accounts": {c: {"installed": True, "signed_in": True, "email_masked": m, "has_email": bool(m), "method": "subscription", "org": None,
                         "identity_known": c != "antigravity", "actions": [], "pending": False}
                     for c, m in (("claude", "d•••@e•••.com"), ("openai", "d•••@e•••.com"), ("antigravity", None))},   # invented; a demo has no buttons
        "alerts": [{"cli": "openai", "window": "weekly", "used_percent": 86.0, "threshold": 80, "resets_at": soon(40)}]}


def demo_handler():
    """The console's own handler with every door to the real machine closed. Only the read endpoints the stage
    needs are passed through; they read the demo database."""
    import companion_server as cs
    from urllib.parse import urlsplit

    class DemoHandler(cs.CompanionHandler):
        def do_POST(self):                                # chat, roles, project, decide, shutdown, bridge ...
            try:                                          # read the body so the connection closes cleanly
                self.rfile.read(min(int(self.headers.get("Content-Length") or 0), 1 << 20))
            except (ValueError, OSError):
                pass
            return self._send_json(READ_ONLY, 403)

        def do_GET(self):
            path = urlsplit(self.path).path
            if path.startswith("/bridge/") or path in ("/ops/pick-folder", "/project"):
                return self._send_json(READ_ONLY, 403)    # the bridge lists real project folders
            if path == "/ops/roles":                      # not the operator's real role choice
                return self._send_json({"roles": DEMO_ROLES, "independence": "full", "csrf": ""})
            if path == "/ops/ai":                         # invented plan, limits and choices: nothing is looked up
                return self._send_json(demo_ai())
            return super().do_GET()

        def _send_json(self, payload, code=200):
            if isinstance(payload, dict) and "diagnostics" in payload:
                payload = {**payload, "diagnostics": None, "allowed_projects": []}   # real executable paths
            return super()._send_json(payload, code)
    return DemoHandler


def serve(demo, port):
    import companion_server as cs
    server = cs.d.DashboardServer(("127.0.0.1", port), demo_handler())
    server.bridge_token = secrets.token_urlsafe(24)       # its own token: the real console's is never loaded here
    server.bridge = cs.OrderBridge(cs.d, [])
    server.stopping = False
    server.install_root = demo.dir                         # /ops/hello: not this folder's real console
    return server


def main(argv=None):
    parser = argparse.ArgumentParser(description="Serve the console on invented data (for screenshots and demos).")
    parser.add_argument("--port", type=int, default=8190)
    parser.add_argument("--dir", help="where to build the data set (default: a new temporary folder)")
    parser.add_argument("--no-live", action="store_true", help="no running mission: a still picture of finished work")
    parser.add_argument("--seed-only", action="store_true", help="build the data set and exit without serving")
    args = parser.parse_args(argv)
    folder = Path(args.dir).resolve() if args.dir else Path(tempfile.mkdtemp(prefix="tribunal-demo-"))
    if (folder / "director.db").exists():
        parser.error(f"{folder} already holds a data set; choose an empty folder")
    folder.mkdir(parents=True, exist_ok=True)
    demo = Demo(folder)
    demo.seed(datetime.now(timezone.utc))
    demo.started = time.time()                            # files older than this are the seeded history
    print(f"demo data: {folder}", flush=True)
    if args.seed_only:
        return 0
    block_real_ai_calls()
    server = serve(demo, args.port)
    stop = threading.Event()
    if not args.no_live:
        threading.Thread(target=demo.live_loop, args=(stop,), daemon=True).start()
    else:
        demo.close_live_mission()
    print(f"Tribunal AI demo console: http://127.0.0.1:{server.server_address[1]}   (invented data, Ctrl+C to stop)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
