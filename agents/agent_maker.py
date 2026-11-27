"""Agent-mode Maker: the CLI (Claude Code, Codex or Antigravity) works in the run's worktree itself.

It reads and edits files, installs what the project needs inside the project, writes and runs tests, and reports in
a short JSON at the end. Nothing is written by Tribunal: the worktree's git status after the call is what changed.
What it may not do on its own (system-wide installs, publishing, secrets) is caught by core/agent_guard.py and asked
about after the step. The proposal Maker (agents/proposal_maker.py) stays available as `maker.mode: proposal`.
"""
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from agents.proposal_maker import ProposalMaker
from core import agent_guard
from core.cli_runner import AgentCliRunner, ProviderCallError
from core.env_utils import get_sanitized_env, run_capture
from core.safety import SafetyPolicy
from schemas.maker_result import MakerResultSchema

# Folders an install or a test run creates. They stay in the worktree and are kept out of the change by .gitignore.
INSTALLED = ("node_modules", ".venv", "venv", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
             ".parcel-cache", ".next", ".turbo", ".cache")


def changed_paths(root: Path) -> List[str]:
    """Every path git sees as changed or new (ignored files are not), as repo-relative posix paths."""
    out = run_capture(["git", "-c", "core.quotepath=false", "status", "--porcelain=v1", "-uall", "-z"], cwd=root, timeout=60)
    if out.returncode != 0:
        return []
    paths, parts = [], out.stdout.split("\0")
    i = 0
    while i < len(parts):
        entry = parts[i]
        i += 1
        if len(entry) < 4:
            continue
        code, path = entry[:2], entry[3:]
        if code[0] in "RC":                           # a rename is followed by its old path
            i += 1
        paths.append(path.replace("\\", "/"))
    return paths


def head_of(root: Path) -> str:
    out = run_capture(["git", "rev-parse", "HEAD"], cwd=root, timeout=30)
    return out.stdout.strip() if out.returncode == 0 else ""


def undo_commits(root: Path, before: str) -> bool:
    """A Maker that committed moved HEAD, and every check compares with HEAD: its changes would pass unseen while
    apply still copied them. Moving HEAD back (soft: the files stay) puts them in front of the checks again."""
    if not before or head_of(root) == before:
        return False
    run_capture(["git", "reset", "--soft", before], cwd=root, timeout=60)
    run_capture(["git", "reset", "-q"], cwd=root, timeout=60)      # unstaged, like every other change
    return True


# Install/cache folder names that are unmistakable wherever they appear; the others (venv, .next, .cache, ...) are
# excluded only at the place they showed up, so a project's own folder of that name elsewhere stays visible.
ANYWHERE = {"node_modules", ".venv", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}


def exclude_installs(root: Path) -> List[str]:
    """Keeps the install and cache folders that showed up as new files (node_modules, .venv, ...) out of every change:
    git's own exclude list of the repository (.git/info/exclude, where Tribunal already keeps .director_worktrees
    out), never the project's .gitignore - a project file the ORDER may protect (found on Windows, 2026-11-26).
    Returns the patterns added."""
    wanted = []
    for rel in changed_paths(root):
        parts = Path(rel).parts
        for i, part in enumerate(parts[:-1]):
            if part in INSTALLED:
                pattern = f"{part}/" if part in ANYWHERE else "/" + "/".join(parts[:i + 1]) + "/"
                if pattern not in wanted:
                    wanted.append(pattern)
                break
    if not wanted:
        return []
    out = run_capture(["git", "rev-parse", "--git-path", "info/exclude"], cwd=root, timeout=30)
    if out.returncode != 0 or not out.stdout.strip():
        return []
    path = Path(out.stdout.strip())
    if not path.is_absolute():
        path = root / path
    try:
        text = path.read_bytes().decode("utf-8", errors="surrogateescape")
    except OSError:
        text = ""
    have = {line.strip() for line in text.splitlines()}
    added = [w for w in wanted if w not in have]
    if added:
        path.parent.mkdir(parents=True, exist_ok=True)
        body = text + ("" if not text or text.endswith("\n") else "\n") + "# Tribunal AI: installed packages and caches\n" + "\n".join(added) + "\n"
        with open(path, "ab" if text and body.startswith(text) else "wb") as f:      # appended: a line written meanwhile stays
            f.write((body[len(text):] if text else body).encode("utf-8", errors="surrogateescape"))
    return added


def read_events(domain: str, raw: str, fallback: str) -> "tuple[str, List[str]]":
    """The final answer and the shell commands run, from each CLI's own event record: Claude stream-json (Bash tool
    calls, the result event), Codex --json (command_execution items, the last agent_message), Antigravity stream-json
    (run_command steps; its final answer is already taken out by the runner)."""
    final, commands = "", []
    for line in (raw or "").splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if not isinstance(event, dict):
            continue
        if domain == "ANTHROPIC":
            if event.get("type") == "assistant":
                for part in ((event.get("message") or {}).get("content") or []):
                    if isinstance(part, dict) and part.get("type") == "tool_use" and part.get("name") == "Bash":
                        commands.append(str((part.get("input") or {}).get("command") or ""))
            elif event.get("type") == "result":
                final = "" if event.get("is_error") else str(event.get("result") or "")   # see stream_error
        elif domain == "OPENAI":
            item = event.get("item") or {}
            if event.get("type") == "item.completed" and item.get("type") == "command_execution":
                commands.append(str(item.get("command") or ""))
            elif event.get("type") == "item.completed" and item.get("type") == "agent_message":
                final = str(item.get("text") or "")
        elif domain == "GOOGLE":
            step = event.get("step_update") or {}
            if step.get("tool_name") == "run_command" and step.get("state") == "DONE":
                commands.append(str(((step.get("tool_info") or {}).get("parameters") or {}).get("CommandLine") or ""))
    if domain == "GOOGLE" or not final:          # no event stream (or Antigravity, already answered): the text as is
        final = fallback
    return final, [c for c in commands if c]


def stream_error(domain: str, raw: str) -> Optional[str]:
    """The error a CLI reported in its event stream while still exiting 0 (Claude's result with is_error)."""
    if domain != "ANTHROPIC":
        return None
    for line in reversed((raw or "").splitlines()):
        line = line.strip()
        if line.startswith("{") and '"result"' in line:
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if isinstance(event, dict) and event.get("type") == "result":
                return str(event.get("result") or "error")[:300] if event.get("is_error") else None
    return None


class AgentMaker(ProposalMaker):
    """Same provider selection, provenance and records as the proposal Maker; a different way of working."""

    # Set by the orchestrator before each step: where caught commands are recorded and which ones the person allowed.
    guard_log: Optional[str] = None
    guard_allowed: List[str] = []

    def _prompt(self, order, root: Path, documents) -> str:
        from core.pythons import project_python
        python = project_python(root)
        venv_python = ".venv\\Scripts\\python.exe" if os.name == "nt" else ".venv/bin/python"
        return (
            "You are the MAKER of Tribunal AI. Your current directory is a git worktree of the user's project, made for "
            "this task. The user agreed that you may run commands, install packages and edit files here without asking.\n"
            "Do the ORDER below completely:\n"
            "- Create and edit files in this directory only. Never touch .git, never commit, push, or change git "
            "settings: Tribunal reviews your changes and applies them.\n"
            f"- Install what the project needs INSIDE the project. Python: a virtual environment at ./.venv made with "
            f"`{python} -m venv .venv`, packages installed with `{venv_python} -m pip install ...` and listed in "
            "requirements.txt (or pyproject.toml). Node: `npm install <package>` here (package.json and its lock file "
            "record them).\n"
            "- Never install system-wide (sudo, brew, apt, winget, choco, npm -g, pip outside .venv), never publish or "
            "deploy (git push, npm publish, gh pr create, vercel ...), never read stored secrets: these need the user's "
            "approval. If Tribunal refuses such a command, continue without it and mention it in your summary.\n"
            "- node_modules, .venv and caches are kept out of the change by Tribunal: do not edit .gitignore for them.\n"
            "- Write real behavior tests and run them until they pass: Python with pytest (installed in .venv), "
            "JavaScript with the built-in node:test (`node --test`) unless the project already uses another runner. "
            "Browser behavior is tested through the logic a test can drive.\n"
            "- Do not leave servers, watchers or windows running: stop anything you start.\n"
            "- Never modify protected_paths. Delete only what allowed_deletions names.\n"
            "When you are done, reply with ONLY this JSON object and no other text:\n"
            '{"summary":"what you did and how you checked it","tests":"the command that runs the tests",'
            '"setup":"one shell line, run from the project root, that installs the dependencies into the project '
            '(empty when there are none)","run":{"command":"one shell line, run from the project root on this platform, '
            'that starts the result (empty for a static page that needs no server)","kind":"web|gui|terminal",'
            '"url":"http://127.0.0.1:PORT/ when it serves a page, else empty","open":"the .html file to show when no '
            'server is needed, else empty"}}\n'
            'Leave "run" out for a library or a change with nothing to start.\n'
            f"Platform: {sys.platform}. Python for new environments: {python} "
            f"({self._project_python_version(root)}).\n"
            + ("The user APPROVED these commands that Tribunal refused earlier in this task; run them now where the task "
               "needs them: " + json.dumps(self.guard_allowed, ensure_ascii=False) + ". A command that needs a password "
               "(sudo, doas, su) cannot be answered here: the user ran it themselves, so do not run it; check that its "
               "effect is in place and continue.\n" if self.guard_allowed else "")
            + "ORDER:\n" + order.model_dump_json() +
            ("\nREFERENCE DOCUMENTS:\n" + json.dumps(documents, ensure_ascii=False) if documents else ""))

    def _report(self, text: str) -> Dict[str, Any]:
        """The final JSON, from the CLI's answer (Claude wraps it in a result envelope). Unreadable: the text itself
        becomes the summary - the worktree, not the report, says what changed."""
        text = (text or "").strip()
        for _ in range(2):
            body = text
            if body.startswith("```"):
                body = body.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
            start, end = body.find("{"), body.rfind("}")
            try:
                found, _repairs = self.parse_proposal(body[start:end + 1] if start >= 0 and end > start else body)
            except Exception:
                found = None
            if isinstance(found, dict) and found.get("type") == "result" and "result" in found:
                if found.get("is_error"):
                    raise ValueError("Maker CLI returned an error result: " + str(found.get("result"))[:300])
                text = str(found.get("result") or "").strip()
                continue
            if isinstance(found, dict):
                return found
            break
        return {"summary": text[-1500:]}

    def run(self, order, worktree_path, maker_fn=None):
        if maker_fn is not None:
            return super().run(order, worktree_path, maker_fn)
        from core import usage
        from core.maker_context import referenced_documents
        usage.set_context(role='MAKER')
        from core.setup import agent_consented
        if not agent_consented():
            # the person has not agreed that the Maker may run commands here: nothing runs (the helper asks)
            return MakerResultSchema(status='FAILED', files_modified=[], commands_run=[], summary='Agent-mode terms not agreed',
                                     error='PERMISSION_CONSENT_MISSING: agree to the agent-mode terms in the first-run helper '
                                           '(AI settings > Start) before the Maker may run commands on this computer')
        root = Path(worktree_path).resolve()
        if self.guard_log:
            log = Path(self.guard_log)                     # cleared by the orchestrator once per Maker stage
        else:
            handle, name = tempfile.mkstemp(prefix="tribunal-guard-", suffix=".jsonl")
            os.close(handle)
            log = Path(name)
        before_head = head_of(root)
        exclude_installs(root)
        before_control = self._control_plane_snapshot(root)
        before = set(changed_paths(root))
        prompt = self._prompt(order, root, referenced_documents(order))
        domain = self.provider.upper()
        env = agent_guard.step_env(get_sanitized_env(), str(root), log, self.guard_allowed)
        runner = AgentCliRunner(env, executables={domain: self.executable}, timeout=self.timeout,
                                no_output_timeout=self.no_progress_timeout)
        self.last_execution_info = {'exit_code': None, 'attempts': [], 'output': '', 'mode': 'agent'}
        self.last_guard_requests = []
        try:
            result = runner.invoke(domain, prompt, str(root), 'BUILDING')
        except ProviderCallError as exc:
            self.last_execution_info = dict(exc.meta)
            self.last_execution_info.update(error=str(exc), output='', attempts=getattr(exc, 'attempts', []),
                                            exit_code=exc.meta.get('exit_code'), mode='agent',
                                            execution_duration_sec=sum(a.get('duration_sec', 0) for a in getattr(exc, 'attempts', [])))
            undo_commits(root, before_head)
            self.last_guard_requests = self._guard_requests(log, "")
            raise
        raw = result.get('raw_stdout') or result['output']
        output, commands = read_events(domain, raw, result['output'])
        self.last_guard_requests = self._guard_requests(log, output + "\n" + result.get('stderr', ''), commands, str(root),
                                                        self.guard_allowed)
        undone = undo_commits(root, before_head)
        added_ignores = exclude_installs(root)
        self.last_execution_info = {'invocation_command': result['invocation'], 'exit_code': result['exit_code'],
                                    'execution_duration_sec': result['duration_sec'], 'output': output,
                                    'attempts': result.get('attempts', []), 'attempt_number': result.get('attempt_number', 1),
                                    'prompt_chars': len(prompt), 'mode': 'agent', 'gitignore_added': added_ignores,
                                    'commits_undone': undone, 'commands_seen': len(commands),
                                    'guard_requests': self.last_guard_requests}
        if self._control_plane_snapshot(root) != before_control:
            return MakerResultSchema(status='FAILED', files_modified=[], commands_run=[result['invocation']],
                                     summary='The Maker changed Tribunal control files',
                                     error='CONTROL_PLANE_MODIFIED: the Maker touched .agents/, GEMINI.md or .director_worktrees/')
        failed = stream_error(domain, raw)              # raised only now: commits undone and caught commands kept first
        if failed:
            raise ValueError("Maker CLI returned an error result: " + failed)
        report = self._report(output)
        changed = [p for p in changed_paths(root) if not SafetyPolicy.is_control_plane_path(p)]
        from core.run_preview import clean_spec
        summary = str(report.get('summary') or 'Changes made in the worktree')[:2000]
        if not changed:
            if 'ARCHITECT REPAIR ORDER' in (order.context or '') or before:
                return MakerResultSchema(status='COMPLETED', files_modified=[], commands_run=[result['invocation']],
                                         summary='No further changes: ' + summary)
            return MakerResultSchema(status='FAILED', files_modified=[], commands_run=[result['invocation']], summary=summary,
                                     error='MAKER_NO_CHANGES: the Maker finished without changing any file')
        self.last_execution_info['setup'] = str(report.get('setup') or '')[:300]
        self.last_execution_info['tests'] = str(report.get('tests') or '')[:300]
        return MakerResultSchema(status='COMPLETED', files_modified=changed, commands_run=[result['invocation']],
                                 summary=summary, run=clean_spec(report.get('run')))

    @staticmethod
    def _guard_requests(log: Path, output: str, commands: List[str] = (), root: Optional[str] = None,
                        allowed: List[str] = ()) -> List[Dict[str, Any]]:
        """Refused commands (stand-ins, Claude's hook), then commands of an asked-about category the CLI's own record
        says it ran past every guard (a full path such as /usr/bin/sudo): those have run, and the person is told."""
        found = agent_guard.requests(log)
        ask = agent_guard.permissions()
        seen = {agent_guard.canon(f["command"]) for f in found}
        for item in agent_guard.ran_commands(commands, log, root, allowed):   # an allowed command that ran is no news
            if ask.get(item["category"]) and agent_guard.canon(item["command"]) not in seen:
                seen.add(agent_guard.canon(item["command"]))
                found.append(item)
        if ask.get("system_install") and not commands:   # no record of what ran: the text is all there is to go by
            for call in agent_guard.full_path_calls(output):
                if agent_guard.canon(call) not in seen and not any(call in f["command"] for f in found):
                    found.append({"category": "system_install", "command": call, "ran": True})
        return found
