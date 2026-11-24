"""One real, small call per (AI, role): does this CLI work in this role right now?

Used by the opt-in tools in scripts/ (they spend subscription quota; the test suite never calls them for real). The
agents are built exactly as a run builds them (Orchestrator._init_architect / _init_maker / _init_inspector), so a
check exercises the same adapter, prompt and parser a real task would. Nothing here touches a real project: every
call works in a throw-away folder, and the code a MAKER writes is run in a separate Python process, never imported
into this one.
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

PROVIDERS = ("claude", "openai", "antigravity")          # core.role_settings aliases
ROLES = ("architect", "maker", "inspector")
GOAL = "Create src/add.py with def add(a, b): return a + b. No other files."
# How the Codex and Claude inspectors report a call that did not work: as a "changes_required" verdict, not as an error.
CALL_FAILED = ("CONFIG_ERROR", "TIMEOUT", "UNPARSEABLE", "Codex CLI exited", "Claude CLI exited")
DIFF = "--- /dev/null\n+++ b/src/add.py\n@@ -0,0 +1,2 @@\n+def add(a, b):\n+    return a + b\n"


def _order():
    from schemas.order import OrderSchema
    return OrderSchema(goal=GOAL, allowed_paths=["src/**"], max_files_changed=1, max_diff_lines=20)


CODE_TIMEOUT = 20.0          # seconds the written code may take


def run_added_code(folder: Path, timeout: Optional[float] = None) -> Optional[str]:
    """Runs what the MAKER wrote in its own Python process (isolated mode: no site-packages tricks, no current folder
    on the path). None when add(2, 3) == 5, else what went wrong."""
    probe = "import sys; sys.path.insert(0, sys.argv[1]); from src.add import add; assert add(2, 3) == 5, add(2, 3)"
    # Its own process group, so a cut-off also ends whatever the written code started.
    from core.pythons import tribunal_python
    proc = subprocess.Popen([tribunal_python(), "-I", "-c", probe, str(folder)], cwd=str(folder), stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, start_new_session=True)
    try:
        out, err = proc.communicate(timeout=timeout or CODE_TIMEOUT)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError, AttributeError):
            proc.kill()
        proc.communicate()
        return "the written code did not finish"
    return None if proc.returncode == 0 else (err or out or "failed").strip()[-300:]


def check(orch, role: str, provider: str) -> Dict[str, Any]:
    """{'role', 'provider', 'ok', 'seconds', 'detail'} for one real call of `provider` acting as `role`."""
    started = time.monotonic()
    out: Dict[str, Any] = {"role": role, "provider": provider, "ok": False, "detail": ""}
    try:                                                      # the ledger shows these calls for what they are
        from core import usage
        usage.set_context(stage="ROLE_CHECK", run_id=None, mission_id=None)
    except Exception:
        pass
    try:
        with tempfile.TemporaryDirectory(prefix="tribunal-role-check-") as tmp:
            from core.bootstrap import prepare_project
            folder = Path(prepare_project(tmp))           # a git project, as every real run's folder is (Codex requires one)
            (folder / "src").mkdir()
            if role == "architect":
                agent = orch._init_architect(provider)
                order = agent.create_order(GOAL, {"project_path": str(folder), "existing_files": []})
                out.update(ok=bool(order.allowed_paths), detail=f"allowed_paths={order.allowed_paths}")
            elif role == "maker":
                agent = orch._init_maker(provider)
                result = agent.run(_order(), str(folder))
                problem = run_added_code(folder) if result.status == "COMPLETED" else f"status {result.status}"
                out.update(ok=problem is None, detail=problem or f"wrote {result.files_modified}")
            elif role == "inspector":
                agent = orch._init_inspector(provider)
                review = agent.review(_order(), DIFF, {"passed": True, "summary": "check only", "test_counts": {"passed": 1}},
                                      worktree_path=str(folder))
                failed = [p for p in (getattr(review, "p0", None) or []) if str(p).startswith(CALL_FAILED)]
                out.update(ok=review.verdict in ("pass", "changes_required") and not failed,
                           detail=f"verdict={review.verdict}" + (f" · {failed[0][:200]}" if failed else ""))
            else:
                raise ValueError(f"unknown role {role!r}")
    except Exception as exc:                                  # a failed check is a result, not a crash of the tool
        out["detail"] = f"{type(exc).__name__}: {str(exc)[-400:]}"
    out["seconds"] = round(time.monotonic() - started, 1)
    return out


def current_assignment(config: dict) -> Dict[str, str]:
    """role -> provider alias, as the next run would use them (config.yaml plus the console's role choice)."""
    from core.role_settings import current
    return current(config)


def plan(roles: List[str], providers: List[str]) -> List[tuple]:
    """(role, provider) pairs, validated."""
    bad = [r for r in roles if r not in ROLES] + [p for p in providers if p not in PROVIDERS]
    if bad:
        raise ValueError(f"unknown role or provider: {', '.join(bad)}")
    return [(r, p) for p in providers for r in roles]
