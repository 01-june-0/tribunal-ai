import os
import re
import sys
import shlex
import shutil
from pathlib import Path
from typing import Dict, Any, Optional, Union, List
from core.git_manager import GitManager
from core.process_runner import ProcessTreeRunner, ProcessResult
from core.env_utils import get_sanitized_env

class Verifier:
    """Orchestrator-driven verification executing build, test, and git checks."""

    @staticmethod
    def _execute_cmd(cmd_str: Optional[Union[str, List[str]]], cwd: Path, timeout: float = 120.0, on_line=None,
                     python_root: Optional[str] = None) -> Dict[str, Any]:
        if not cmd_str:
            return {"command": None, "executed": False, "passed": True, "output": "No command specified"}
        
        try:
            env = get_sanitized_env()
            # Verify under the user's default Python I/O encoding, not whatever the Director process was launched
            # with: an inherited PYTHONIOENCODING/PYTHONUTF8 once hid a CLI that breaks in a normal cp949 terminal.
            for leaked in ("PYTHONIOENCODING", "PYTHONUTF8", "PYTHONLEGACYWINDOWSSTDIO"):
                env.pop(leaked, None)
            cwd_str = str(cwd)
            current_ppath = env.get("PYTHONPATH", "")
            env["PYTHONPATH"] = f"{cwd_str}{os.pathsep}{current_ppath}" if current_ppath else cwd_str
            # Always, watched or not: every verification of a run (baseline, the round itself, apply) must see the
            # same environment. A Python test runner then writes each line as it happens, as it would in a terminal.
            env["PYTHONUNBUFFERED"] = "1"
            # No bytecode cache: Python reuses a cached module when the source has the same size and the same mtime
            # second, so a fix written quickly over a same-size bug was not what got tested (seen on Linux). It also
            # keeps __pycache__ out of the worktree, whose files applying writes into the project.
            env["PYTHONDONTWRITEBYTECODE"] = "1"
            env.setdefault("CI", "1")           # test runners that watch by default (vitest, jest --watch) run once

            if isinstance(cmd_str, list):
                argv = list(cmd_str)
            else:
                raw_tokens = shlex.split(cmd_str, posix=False)
                argv = []
                for t in raw_tokens:
                    if len(t) >= 2 and ((t[0] == '"' and t[-1] == '"') or (t[0] == "'" and t[-1] == "'")):
                        argv.append(t[1:-1])
                    else:
                        argv.append(t)

            if not argv:
                return {"command": cmd_str, "executed": False, "passed": True, "output": "Empty command"}

            # `python` / `python3`: the project's own environment when it has one that can run this (its packages are
            # there), else Tribunal's interpreter as before (core/pythons.py)
            if argv[0] in ("python", "python3"):
                from core.pythons import project_python
                needs = None                    # `python [-B -u …] -m pytest …` or `-mpytest`: the module it runs
                for i, tok in enumerate(argv[1:], start=1):
                    if tok == "-m" and i + 1 < len(argv):
                        needs = argv[i + 1]
                        break
                    if tok.startswith("-m") and len(tok) > 2:
                        needs = tok[2:]
                        break
                    if not tok.startswith("-"):
                        break                   # a script file: whatever follows are its own arguments
                argv[0] = project_python(Path(python_root or cwd_str), needs=needs)
            else:
                resolved = shutil.which(argv[0])
                if resolved:
                    argv[0] = resolved

            res: ProcessResult = ProcessTreeRunner.run(
                argv=argv,
                cwd=cwd_str,
                env=env,
                timeout=timeout,
                no_output_timeout=None,
                on_output=on_line
            )

            if res.timed_out:
                return {
                    "command": cmd_str if isinstance(cmd_str, str) else " ".join(cmd_str),
                    "executed": True,
                    "passed": False,
                    "exit_code": -1,
                    "output": f"Command timed out after {timeout} seconds: {res.timeout_reason}"
                }

            combined_output = (res.stdout or "") + ("\n" + res.stderr if res.stderr else "")
            passed = (res.exit_code == 0)
            return {
                "command": cmd_str if isinstance(cmd_str, str) else " ".join(cmd_str),
                "executed": True,
                "passed": passed,
                "exit_code": res.exit_code,
                "output": combined_output.strip()
            }
        except Exception as e:
            return {
                "command": cmd_str if isinstance(cmd_str, str) else " ".join(cmd_str),
                "executed": True,
                "passed": False,
                "exit_code": -1,
                "output": f"Execution error: {str(e)}"
            }

    @classmethod
    def verify(
        cls,
        worktree_path: str,
        build_cmd: Optional[str] = None,
        test_cmd: Optional[str] = None,
        lint_cmd: Optional[str] = None,
        timeout: float = 120.0,
        git_checks: bool = True,
        on_line=None,
        python_root: Optional[str] = None,
        node_tests: bool = True
    ) -> Dict[str, Any]:
        """`on_line(phase, text)` observes the commands' output while they run (phase: build / test / lint). The text
        comes in pieces as it arrives, not necessarily whole lines. `python_root`: where to look for the project's
        Python when the commands run somewhere else (the inspector's throw-away copy)."""
        def watch(phase):
            return (lambda line: on_line(phase, line)) if on_line is not None else None

        wt = Path(worktree_path).resolve()

        # 1. Git checks
        if git_checks:
            git_status = GitManager.get_status(str(wt))
            git_diff = GitManager.get_diff(str(wt))
        else:                                   # apply-verify on the MAIN tree: never touch its index (no intent-to-add)
            git_status, git_diff = "", ""

        # 2. Run build
        build_res = cls._execute_cmd(build_cmd, wt, timeout=timeout, on_line=watch("build"), python_root=python_root)

        # 3. Run test: the configured command, then the project's own Node tests when it has some (a JavaScript game
        # or site would otherwise be judged on the Python smoke test alone, its real tests never run)
        test_res = cls._execute_cmd(test_cmd, wt, timeout=timeout, on_line=watch("test"), python_root=python_root)
        test_counts = cls._parse_test_counts(test_res.get("output", "")) if test_res.get("executed") else \
            {"passed": 0, "failed": 0, "total": 0}
        # node_tests=False: re-checking where the run never ran Node tests (applying a result): a first, late run there
        # could undo a passed result for tests that were never part of it
        node_cmd, node_note = (None, None) if cls._runs_node_already(test_cmd) or not node_tests else cls.node_test_command(wt)
        node_info: Dict[str, Any] = {"command": None, "note": node_note}
        if node_cmd:
            node_res = cls._execute_cmd(node_cmd, wt, timeout=timeout, on_line=watch("test"))
            node_counts = cls._parse_node_counts(node_res.get("output", ""))
            node_info.update(command=node_res.get("command"), passed=node_res["passed"], test_counts=node_counts)
            test_res = cls._join_tests(test_res, node_res)
            test_counts = {k: test_counts.get(k, 0) + node_counts.get(k, 0) for k in ("passed", "failed", "total")}

        # 4. Run lint
        lint_res = cls._execute_cmd(lint_cmd, wt, timeout=timeout, on_line=watch("lint"), python_root=python_root)

        # Overall verification pass condition:
        # Build must pass (if executed)
        # Test must pass (if executed)
        # Lint must pass (if executed)
        overall_passed = build_res["passed"] and test_res["passed"] and lint_res["passed"]

        summary_parts = []
        if build_res["executed"]:
            summary_parts.append(f"Build: {'PASS' if build_res['passed'] else 'FAIL'}")
        if test_res["executed"]:
            summary_parts.append(f"Test: {'PASS' if test_res['passed'] else 'FAIL'}")
        if lint_res["executed"]:
            summary_parts.append(f"Lint: {'PASS' if lint_res['passed'] else 'FAIL'}")
        
        if node_info["command"]:
            summary_parts.append(f"Node tests: {'PASS' if node_info['passed'] else 'FAIL'}")
        elif node_note:
            summary_parts.append(f"Node tests not run: {node_note}")
        summary = " | ".join(summary_parts) if summary_parts else "No build/test commands configured"

        return {
            "passed": overall_passed,
            "summary": summary,
            "build": build_res,
            "test": test_res,
            "lint": lint_res,
            "test_counts": test_counts,
            "node_tests": node_info,
            "git_status": git_status,
            "git_diff": git_diff
        }

    # Folders never searched for Node tests: dependencies, version control, Tribunal's own records, build output.
    _NODE_SKIP_DIRS = {"node_modules", ".git", ".director_worktrees", ".venv", "venv", "__pycache__", "dist", "build",
                       "coverage", ".next", ".cache"}
    _NODE_TEST_NAME = re.compile(r"(\.test|\.spec|[-_]test)\.(js|mjs|cjs)$|^test[-_].*\.(js|mjs|cjs)$", re.I)
    _NODE_TEST_IMPORT = re.compile(r"""(require\(\s*|from\s+|import\s*\(\s*)['"]node:test['"]""")
    _NODE_MAX_FILES = 200

    @classmethod
    def node_test_command(cls, wt: Path):
        """(argv or None, note). `node --test` over the test files written for Node's built-in runner (they import
        node:test) when there are any; otherwise the project's declared `npm test` when package.json has a real test
        script (and its dependencies are installed, or it has none). Files for the built-in runner always run this
        way, so a changed test script cannot hide them. Jest, Mocha and the like run only through a test script: run
        by `node --test` they would fail for reasons that have nothing to do with the code."""
        import json
        files = cls._node_test_files(wt)
        if files:
            node = shutil.which("node")
            if not node:
                return None, f"{len(files)} Node test file(s) found but node is not installed"
            return [node, "--test", *files], None
        package = wt / "package.json"
        script, deps = "", False
        if package.is_file():
            try:
                data = json.loads(package.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    scripts = data.get("scripts")
                    script = str((scripts if isinstance(scripts, dict) else {}).get("test") or "").strip()
                    deps = bool(data.get("dependencies") or data.get("devDependencies"))
            except (OSError, ValueError):
                script = ""
        if not script or "no test specified" in script:
            return None, None
        if deps and not (wt / "node_modules").is_dir():
            # The packages are installed where the agent-mode Maker worked (node_modules in its worktree); a folder
            # without them cannot run the script, and the summary says why instead of reporting a failure.
            return None, "package.json test script needs dependencies that are not installed here (no node_modules)"
        npm = shutil.which("npm")
        if not npm:
            return None, "package.json has a test script but npm is not installed"
        return [npm, "test"], None

    @classmethod
    def _node_test_files(cls, wt: Path) -> List[str]:
        found: List[str] = []
        for root, dirs, names in os.walk(wt):
            dirs[:] = sorted(d for d in dirs if d not in cls._NODE_SKIP_DIRS and not d.startswith("."))
            for name in sorted(names):
                if not cls._NODE_TEST_NAME.search(name):
                    continue
                path = Path(root) / name
                try:
                    if path.is_symlink() or path.stat().st_size > 1_000_000:
                        continue
                    if not cls._NODE_TEST_IMPORT.search(path.read_text(encoding="utf-8", errors="replace")):
                        continue
                except OSError:
                    continue
                found.append(path.relative_to(wt).as_posix())
                if len(found) >= cls._NODE_MAX_FILES:
                    return found
        return found

    @staticmethod
    def _runs_node_already(test_cmd) -> bool:
        """The configured command is itself a Node test run (`npm test`, `node --test`, `npx jest` ...): running the
        Node tests again would double their count and their time."""
        if not test_cmd:
            return False
        tokens = list(test_cmd) if isinstance(test_cmd, list) else shlex.split(str(test_cmd), posix=False)
        first = Path(str(tokens[0]).strip("\"'")).name.lower() if tokens else ""
        return first in ("npm", "npm.cmd", "npx", "npx.cmd", "node", "node.exe", "yarn", "yarn.cmd", "pnpm", "pnpm.cmd") \
            or "--test" in tokens

    @staticmethod
    def _join_tests(first: Dict[str, Any], node: Dict[str, Any]) -> Dict[str, Any]:
        """One test result out of the configured command's and the Node tests'; the Node part comes last, under a
        heading, so the end of the output shows its summary."""
        if not first.get("executed"):
            return node
        codes = [c for c in (first.get("exit_code"), node.get("exit_code")) if c not in (None, 0)]
        return {
            "command": f"{first.get('command')} ; {node.get('command')}",
            "executed": True,
            "passed": bool(first.get("passed")) and bool(node.get("passed")),
            "exit_code": codes[0] if codes else 0,
            "output": f"{first.get('output') or ''}\n\n===== Node tests: {node.get('command')} =====\n{node.get('output') or ''}",
        }

    @staticmethod
    def _parse_node_counts(output: str) -> Dict[str, int]:
        """node:test summaries ("ℹ pass 18" spec, "# pass 18" TAP; every summary is added, a script may run several),
        then the "Tests:" line of Jest/Vitest (the line before it counts files or suites), then Mocha ("18 passing")."""
        counts = {"passed": 0, "failed": 0, "total": 0}
        if not output:
            return counts
        own = re.findall(r"^\s*(?:#|ℹ)\s*pass\s+(\d+)\s*$", output, re.M)
        if own:
            counts["passed"] = sum(int(n) for n in own)
            counts["failed"] = sum(int(n) for n in re.findall(r"^\s*(?:#|ℹ)\s*fail\s+(\d+)\s*$", output, re.M))
        else:
            line = next((l for l in output.splitlines() if re.match(r"^\s*Tests:?\s", l)), None)
            text = line if line is not None else output
            passed = re.search(r"(\d+)\s+pass(?:ed|ing)\b", text)
            failed = re.search(r"(\d+)\s+fail(?:ed|ing)\b", text)
            counts["passed"] = int(passed.group(1)) if passed else 0
            counts["failed"] = int(failed.group(1)) if failed else 0
        counts["total"] = counts["passed"] + counts["failed"]
        return counts

    @staticmethod
    def _parse_test_counts(output: str) -> Dict[str, int]:
        import re
        counts = {"passed": 0, "failed": 0, "total": 0}
        if not output:
            return counts

        # Pytest pattern: '12 passed, 1 failed' or '4 passed in 0.02s'
        pass_match = re.search(r"(\d+)\s+passed", output)
        if pass_match:
            counts["passed"] = int(pass_match.group(1))

        fail_match = re.search(r"(\d+)\s+failed", output)
        if fail_match:
            counts["failed"] = int(fail_match.group(1))

        # Unittest pattern: 'Ran 4 tests in 0.001s'
        ran_match = re.search(r"Ran\s+(\d+)\s+tests", output)
        if ran_match:
            counts["total"] = int(ran_match.group(1))
            if "OK" in output:
                counts["passed"] = counts["total"]

        if counts["total"] == 0:
            counts["total"] = counts["passed"] + counts["failed"]

        return counts
