#!/usr/bin/env python3
import sys
import yaml
import json
from pathlib import Path
from typing import Optional
import click

from core.orchestrator import Orchestrator
from core.state_machine import StateMachine, State

def _merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for key, value in over.items():
        out[key] = _merge(out[key], value) if isinstance(value, dict) and isinstance(out.get(key), dict) else value
    return out


def load_config() -> dict:
    """config.yaml that ships with the code, and - for an installed copy - the person's own config.yaml in Tribunal's
    home on top of it (only the keys they set; core/paths.py). Run from source, both are the same file."""
    from core.paths import CODE_ROOT, home
    from core.role_settings import apply
    from core.role_names import canon
    cfg: dict = {}
    for path in dict.fromkeys([CODE_ROOT / "config.yaml", home() / "config.yaml"]):
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                cfg = _merge(cfg, canon(yaml.safe_load(f) or {}))    # old key names (head:, builder_attempts ...) are still read
    return apply(cfg) if cfg else {}

@click.group()
def cli():
    """TRIBUNAL AI v3.1.8 - Local Autonomous Orchestrator (Subscription CLIs)"""
    pass

@cli.command()
@click.option("--project", "-p", required=True, help="Target project root directory")
@click.option("--goal", "-g", required=True, help="User goal/prompt for the run")
@click.option("--architect-provider", "--head-provider", "architect_provider", help="Override ARCHITECT provider (claude, codex, mock)")
def run(project: str, goal: str, architect_provider: Optional[str]):
    """Start a new development run."""
    config = load_config()
    if architect_provider:
        config.setdefault("architect", {})["provider"] = architect_provider

    click.echo(f"=== Initiating TRIBUNAL AI Run ===")
    click.echo(f"Project: {project}")
    click.echo(f"Goal:    {goal}\n")

    orchestrator = Orchestrator(config=config)
    try:
        summary = orchestrator.run(project_path=project, goal=goal)
        _print_summary(summary)
    except Exception as e:
        click.secho(f"\n[CRITICAL ERROR] Run aborted: {str(e)}", fg="red")
        sys.exit(1)

@cli.command()
@click.option("--run-id", "-r", help="Specific Run ID to inspect")
def status(run_id: Optional[str]):
    """Inspect status of previous runs."""
    sm = StateMachine()
    if run_id:
        run = sm.get_run(run_id)
        if not run:
            click.secho(f"Run {run_id} not found.", fg="red")
            return
        
        click.echo(f"\n=== Details for {run_id} ===")
        click.echo(f"Project:       {run['project_path']}")
        click.echo(f"Goal:          {run['goal']}")
        click.echo(f"Current State: {run['current_state']}")
        click.echo(f"Worktree:      {run['worktree_path']}")
        click.echo(f"Branch:        {run['branch_name']}")
        click.echo(f"Created At:    {run['created_at']}")
        click.echo(f"Updated At:    {run['updated_at']}\n")

        transitions = sm.get_transitions(run_id)
        click.echo("--- State History ---")
        for t in transitions:
            click.echo(f"  [{t['timestamp']}] {t['from_state']} -> {t['to_state']} : {t['details'] or ''}")
    else:
        runs = sm.list_runs()
        if not runs:
            click.echo("No runs recorded in database yet.")
            return

        click.echo(f"\n{'RUN ID':<20} {'STATE':<16} {'CREATED AT':<24} {'GOAL'}")
        click.echo("-" * 80)
        for r in runs:
            goal_preview = (r['goal'][:35] + '...') if len(r['goal']) > 35 else r['goal']
            click.echo(f"{r['run_id']:<20} {r['current_state']:<16} {r['created_at'][:19]:<24} {goal_preview}")

@cli.command()
@click.argument("run_id")
def resume(run_id: str):
    """Resume an interrupted or paused run."""
    config = load_config()
    click.echo(f"=== Resuming TRIBUNAL AI Run: {run_id} ===")
    orchestrator = Orchestrator(config=config)
    try:
        summary = orchestrator.resume(run_id)
        _print_summary(summary)
    except Exception as e:
        click.secho(f"\n[RESUME ERROR] {str(e)}", fg="red")
        sys.exit(1)

@cli.command()
@click.argument("goal")
@click.option("--project", "-p", default=None, help="Project folder (default: the current folder, which must be a git repo)")
@click.option("--profile", type=click.Choice(["quick", "standard", "deep"]), default=None, help="Budget: quick / standard / deep")
@click.option("--no-apply", is_flag=True, help="Keep the result in the worktree instead of applying it to the project")
def do(goal: str, project: Optional[str], profile: Optional[str], no_apply: bool):
    """The compact way: `director do "캡션 검사기 만들어줘"` inside a project folder. Starts the mission through the
    running companion console (so it shows on the stage) or, when no companion is up, runs it right here."""
    import os
    import urllib.request
    import uuid
    target = project or os.getcwd()
    from core import autopilot as _ap
    tag, goal = _ap.split_profile_tag(goal)
    profile = profile or tag or "standard"
    payload = {"request_id": "cli-" + uuid.uuid4().hex[:16], "project_path": str(Path(target).resolve()), "goal": goal,
               "profile": profile, "auto_apply": "off" if no_apply else None,
               # A folder named with -p that is not a git project yet is made one, as a mission started here would do.
               # Never the current folder by default, and never a folder inside someone else's repository.
               "create_project": bool(project) and _fresh_folder(Path(target).resolve())}
    from core.companion_config import bridge_token_path
    from core.paths import home as tribunal_home
    token_path = bridge_token_path(tribunal_home())
    from core.companion_config import active_port, verify, local_open, DEFAULT_PORT
    try:
        port = active_port()
    except (OSError, ValueError, TypeError):          # unreadable companion*.json must not block the in-process fallback
        port = DEFAULT_PORT
    import urllib.error
    reachable = False
    try:
        token = token_path.read_text(encoding="utf-8").strip()
        if not verify(port, token):                    # another program on that port must never receive the token
            raise RuntimeError("no Tribunal AI console of this folder is listening there")
        reachable = True
        req = urllib.request.Request(f"http://127.0.0.1:{port}/bridge/missions", data=json.dumps(payload).encode("utf-8"),
                                     headers={"Content-Type": "application/json", "X-Tribunal-Token": token})
        with local_open(req, 600) as r:              # never through a proxy: the request carries the token
            res = json.loads(r.read().decode("utf-8"))
        click.echo(f"[{res.get('status')}] " + (res.get("mission_id") or res.get("message") or res.get("error") or ""))
        if res.get("reason"):
            click.echo(str(res["reason"]))
        if res.get("mission_id"):
            click.echo(f"진행 상황: http://127.0.0.1:{port}/  (한눈에 탭에서 실시간으로 보입니다)")
        if res.get("status") == "escalated":
            raise SystemExit(2)                        # waits for a decision: not a started task
        return
    except urllib.error.HTTPError as exc:
        # The console is there and said no (a folder it does not take, a busy project, ...). Its answer stands:
        # running the same goal here instead would go around exactly the rule that refused it.
        try:
            res = json.loads(exc.read().decode("utf-8"))
        except Exception:
            res = {}
        raise click.ClickException(f"콘솔이 이 요청을 받지 않았습니다: {res.get('error') or res.get('message') or exc.reason}")
    except SystemExit:
        raise
    except Exception as exc:
        refused = isinstance(exc, ConnectionRefusedError) or isinstance(getattr(exc, "reason", None), ConnectionRefusedError)
        if reachable and not refused:
            # The request may have reached the console (it answers only after the ARCHITECT's first call): running the
            # same goal here as well could start it twice.
            raise click.ClickException(f"콘솔과의 연결이 응답 전에 끊겼습니다({str(exc)[:120]}). 콘솔에서 작업이 시작됐는지 "
                                       f"확인한 뒤 다시 시도하세요.")
        click.echo(f"{port} companion unavailable ({str(exc)[:120]}); running the mission in this process instead.")
    from companion_server import bridge_target_ok
    ok, why = bridge_target_ok(str(Path(target).resolve()))     # the console's own folder rule holds here too
    if not ok:
        raise click.ClickException(f"이 폴더에는 작업을 시킬 수 없습니다: {why}")
    ctx = click.get_current_context()
    ctx.invoke(mission, project=str(Path(target).resolve()), goal=goal, mission_id=None, max_steps=None, replan=None, profile=profile,
               no_apply=no_apply)


def _fresh_folder(path: Path) -> bool:
    """A folder that is not a git project and does not sit inside one: the only kind `do` asks to have prepared."""
    import subprocess
    if (path / ".git").exists():
        return False
    try:
        r = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=str(path), capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return False
    return r.returncode != 0                           # inside another repository: leave it alone


@cli.command()
@click.option("--project", "-p", required=True, help="Target project root directory")
@click.option("--goal", "-g", required=True, help="What you want built, in your own words")
@click.option("--mission-id", help="Continue an existing mission instead of starting one")
@click.option("--max-steps", type=int, help="Milestone budget for a new mission (default: autonomy.max_steps)")
@click.option("--replan", help="With --mission-id: send the blocked step back to ARCHITECT planning, with this reason")
@click.option("--profile", type=click.Choice(["quick", "standard", "deep"]), default=None, help="Budget profile for a new mission")
@click.option("--no-apply", is_flag=True, help="Keep the result in the worktree instead of applying it to the project")
def mission(project: str, goal: str, mission_id: Optional[str], max_steps: Optional[int], replan: Optional[str] = None,
            profile: Optional[str] = None, no_apply: bool = False):
    """Run a goal-driven mission: ARCHITECT plans milestones and decides on your behalf until the goal is done."""
    from core import autopilot
    from core.chat_manager import ChatManager
    from core.mission import MissionRunner, MissionStore, latest_deliverable
    from core.bootstrap import prepare_project

    config = load_config()
    if max_steps:
        config.setdefault("autonomy", {})["max_steps"] = max_steps
    project = str(prepare_project(project))
    try:
        from dashboard_server import active_session_id
        sid = active_session_id()
    except Exception:
        sid = None

    def notify(text, run_id=None, role="SYSTEM"):
        click.echo(f"[{role}] {text}\n")
        if sid:
            try:
                ChatManager().add_message(sid, role, text, run_id=run_id)
            except Exception:
                pass

    runner = MissionRunner(lambda: Orchestrator(config=load_config()), MissionStore(), notify)
    if not mission_id:
        orch = Orchestrator(config=config)
        previous = latest_deliverable(project)
        context = orch._read_project_context(previous or project)
        if previous:
            notify(f"이전 작업 결과물에서 이어서 진행: {previous}")
            context["note"] = "Continuing from the latest mission deliverable; the listed files already exist there."
        from core import usage
        usage.set_context(stage="CHAT", run_id=None, mission_id=None)   # the ledger shows what this first ARCHITECT call is
        try:
            resp, swaps = orch.architect_chat(goal, context, [])
        except Exception as exc:
            raise click.ClickException(f"ARCHITECT를 부르지 못했습니다: {str(exc)[:400]}")
        for note in swaps:
            notify("ARCHITECT 교체: " + note)
        if resp.get("type") != "DEV_TASK":
            click.echo(resp.get("message", ""))
            return
        from schemas.order import OrderSchema
        gate = autopilot.entry_gate(OrderSchema(**resp["order"]), project, orch.architect, cwd=project)
        for note in gate["notes"]:
            notify("ARCHITECT 대리 처리: " + note)
        if gate["escalate"]:
            notify(f"사용자 결정 필요: {gate['escalate']}")
            return
        mission_id = runner.create(project, goal, gate["order"], config=config, notes=gate["notes"], profile=profile, source="cli",
                                   auto_apply="off" if no_apply else None)["mission_id"]
        notify(f"작업 시작 {mission_id}")
    else:
        if no_apply:
            click.echo("--no-apply는 새 작업에만 적용됩니다. 이어 가는 작업은 처음 정한 적용 방식을 따릅니다.")
        if max_steps:
            existing = runner.store.load(mission_id)
            existing["max_steps"] = max(max_steps, len(existing["steps"]) + 1)
            runner.store.save(existing)
            notify(f"작업 {mission_id} 최대 단계를 {existing['max_steps']}로 조정")
        if replan:
            existing = runner.store.load(mission_id)
            existing["steps"][-1]["operator_replan"] = replan
            runner.store.save(existing)
            notify(f"작업 {mission_id}: 멈춘 단계를 운영자가 재계획으로 돌려보냄 - {replan}")
        runner.reopen(mission_id)
    final = runner.run(mission_id)
    click.echo(f"=== Mission {mission_id}: {final['status']} ===")


def _print_summary(summary: dict):
    run_id = summary.get("run_id", "UNKNOWN")
    final_state = summary.get("final_state", "UNKNOWN")
    files_changed = summary.get("files_changed", 0)
    scope_violations = summary.get("scope_violations", 0)

    # Verification details
    v_data = summary.get("verification") or {}
    test_info = "N/A"
    build_info = "N/A"
    if v_data:
        if v_data.get("build", {}).get("executed"):
            build_info = "PASS" if v_data["build"]["passed"] else "FAIL"
        else:
            build_info = "PASS (skipped)"
        if v_data.get("test", {}).get("executed"):
            test_info = "PASS" if v_data["test"]["passed"] else "FAIL"
        else:
            test_info = "PASS (skipped)"

    # Maker status
    b_data = summary.get("maker") or {}
    maker_status = b_data.get("status", "N/A")

    # Review status
    r_data = summary.get("review") or {}
    review_verdict = r_data.get("verdict", "N/A").upper()

    # Baseline details
    base_data = summary.get("baseline_verification") or {}
    base_test_info = "N/A"
    if base_data:
        b_cnt = base_data.get("test_counts", {}).get("passed", 0)
        base_test_info = f"PASS ({b_cnt} tests)" if base_data.get("passed") else "FAIL"

    architect_label = summary.get("architect_label") or "ARCHITECT"
    inspector_label = summary.get("inspector_label") or "CODEX"
    failover_mode = getattr(summary.get("failover_mode", "NORMAL"), "value", summary.get("failover_mode", "NORMAL"))
    mode_tag = f" [{failover_mode}]" if failover_mode != "NORMAL" else ""

    click.echo("\n" + "=" * 36)
    click.echo(f"{run_id}{mode_tag}\n")
    click.echo(f"ARCHITECT        {'PASS' if summary.get('order') else 'N/A'}")      # no ORDER: planning never finished
    click.echo(f"BASELINE TEST    {base_test_info}")
    click.echo(f"MAKER            {maker_status}")          # the role: which AI holds it is a setting, and may have moved
    click.echo(f"BUILD            {build_info}")
    click.echo(f"POST TEST        {test_info}")
    click.echo("INSPECTOR".ljust(17) + f"{review_verdict}")
    click.echo("")
    click.echo(f"FILES CHANGED    {files_changed}")
    click.echo(f"SCOPE VIOLATION  {scope_violations}")
    click.echo("")
    click.echo("FINAL:")
    if final_state == State.PASS:
        click.secho("READY_FOR_HUMAN_REVIEW (PASS)", fg="green", bold=True)
    elif final_state == State.HUMAN_REQUIRED:
        click.secho("HUMAN_REQUIRED", fg="yellow", bold=True)
    else:
        click.secho(f"FAIL ({final_state})", fg="red", bold=True)
    if final_state != State.PASS and summary.get("stop_detail"):
        click.echo(f"REASON: {summary['stop_detail']}")
    click.echo("=" * 36 + "\n")

@cli.command("clean-worktrees")
@click.option("--project", "-p", required=True, help="Target project root directory")
@click.option("--dry-run", is_flag=True, default=False, help="List worktrees to remove without deleting them")
@click.option("--purge-reviewed", is_flag=True, default=False, help="Force remove PASS and HUMAN_REQUIRED worktrees")
def clean_worktrees(project: str, dry_run: bool, purge_reviewed: bool):
    """Safely remove completed/terminal worktrees while protecting active runs and branches."""
    import shutil
    import subprocess
    from core.git_manager import GitManager
    from core.state_machine import TERMINAL_STATES

    proj = Path(project).resolve()
    click.echo(f"Inspecting worktrees for project: {proj} (dry_run={dry_run})...")

    sm = StateMachine()
    runs = sm.list_runs()

    # Runs whose working copy nobody is waiting for any more: the result was applied or discarded, or the task they
    # belong to was closed (its copies cleared from the console). Those go without a flag, changes and branch included -
    # the work is in the project, or was thrown away on purpose.
    from core.mission import MissionStore
    from core.result_manager import ResultManager
    rm = ResultManager()
    settled, kept = set(), set()
    missions = MissionStore().all()
    closed = {s.get("run_id") for m in missions if m.get("closed") for s in m.get("steps", [])}
    # An apply that skipped a conflicting file keeps its copies on purpose: the AIs' version of that file is only there.
    for m in missions:
        if (m.get("applied") or {}).get("skipped_conflicts") and not m.get("closed"):
            kept.update(s.get("run_id") for s in m.get("steps", []))
    for r in runs:
        try:
            state = rm.result_state(r["run_id"])
            if state.get("skipped_conflicts"):
                kept.add(r["run_id"])
            if r["run_id"] in closed or state.get("state") in ("APPLIED", "DISCARDED"):
                settled.add(r["run_id"])
        except Exception:
            continue

    # Query terminal runs and active runs for this project
    terminal_worktrees = set()
    active_worktrees = set()

    for r in runs:
        try:
            r_proj = Path(r["project_path"]).resolve()
        except Exception:
            continue
        if r_proj != proj:
            continue

        wt_path = r.get("worktree_path")
        if not wt_path:
            continue
        resolved_wt = str(Path(wt_path).resolve())

        if r["current_state"] in TERMINAL_STATES or r["run_id"] in settled:
            terminal_worktrees.add((r["run_id"], r["current_state"], resolved_wt))
        else:
            active_worktrees.add(resolved_wt)

    # Get worktrees currently registered in git
    registered_wts = set()
    try:
        raw_list = subprocess.run(
            ["git", "worktree", "list", "--porcelain"],
            cwd=str(proj),
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=True
        ).stdout
        for line in raw_list.splitlines():
            if line.startswith("worktree "):
                registered_wts.add(str(Path(line.split(" ", 1)[1].strip()).resolve()))
    except Exception as e:
        click.secho(f"Warning: git worktree list query: {e}", fg="yellow")

    if not dry_run:         # entries whose folder is already gone would keep their branch "checked out" and undeletable
        subprocess.run(["git", "worktree", "prune"], cwd=str(proj), capture_output=True)

    cleaned_count = 0
    for run_id, state, wt in terminal_worktrees:
        # Never remove an active run's worktree
        if wt in active_worktrees:
            click.echo(f"[PROTECTED] Skipping active worktree: {wt}")
            continue

        wt_path_obj = Path(wt)
        wt_exists = wt_path_obj.exists()
        wt_registered = wt in registered_wts

        if not wt_exists and not wt_registered:
            if run_id in settled and run_id not in kept and not dry_run:
                rm.release_worktrees([run_id], by="CLI", why="clean-worktrees")      # only its branch is left
            continue

        if run_id in settled and run_id in kept and not purge_reviewed:
            click.echo(f"Keeping {run_id}: a conflicting file was skipped when it was applied, and the AIs' version of it "
                       f"exists only in this working copy. Use --purge-reviewed to remove it anyway.")
            continue
        if run_id in settled:
            if dry_run:
                click.echo(f"[DRY-RUN] Would remove worktree and branch: {wt} (Run: {run_id}, applied / discarded / closed)")
                cleaned_count += 1
            elif rm.release_worktrees([run_id], by="CLI", why="clean-worktrees"):
                click.echo(f"Removed worktree and branch: {wt} (Run: {run_id}, applied / discarded / closed)")
                cleaned_count += 1
            else:
                click.secho(f"Failed to remove {wt}", fg="red")
            continue

        # Skip PASS and HUMAN_REQUIRED unless --purge-reviewed is True
        if state in ["PASS", "HUMAN_REQUIRED"] and not purge_reviewed:
            click.echo(f"Skipping {run_id} ({state}) by default. Use --purge-reviewed to remove.")
            continue

        # Check for uncommitted changes if worktree directory exists
        has_uncommitted = False
        if wt_exists:
            try:
                status_out = subprocess.run(
                    ["git", "status", "--porcelain"],
                    cwd=wt,
                    capture_output=True,
                    text=True,
                    encoding="utf-8"
                ).stdout
                if status_out.strip():
                    has_uncommitted = True
            except Exception:
                has_uncommitted = True

        if has_uncommitted:
            click.secho(f"SKIPPED_UNREVIEWED_CHANGES: {wt}", fg="yellow")
            continue

        if dry_run:
            click.echo(f"[DRY-RUN] Would remove worktree: {wt} (Run: {run_id}, State: {state})")
            cleaned_count += 1
        else:
            click.echo(f"Removing worktree: {wt} (Run: {run_id}, State: {state})...")
            try:
                GitManager.remove_worktree(str(proj), wt, force=purge_reviewed)
                if wt_path_obj.exists():
                    shutil.rmtree(wt, ignore_errors=True)
                cleaned_count += 1
            except Exception as e:
                click.secho(f"Failed to remove {wt}: {e}", fg="red")

    if not dry_run:
        try:
            res = subprocess.run(["git", "worktree", "prune", "-v"], cwd=str(proj), capture_output=True, text=True, encoding="utf-8")
            if res.stdout.strip():
                click.echo(res.stdout.strip())
        except Exception:
            pass

    action_label = "Identified" if dry_run else "Cleaned"
    click.echo(f"\n{action_label} {cleaned_count} terminal worktree(s). A run that still waits for a decision keeps its branch.")

if __name__ == "__main__":
    cli()
