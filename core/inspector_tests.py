"""Independent tests from the inspector.

The Maker writes the tests for its own code, so a weak test can wave weak code through. To offset that, the inspector
— still read-only, it never touches a file — may answer its review with a few NEW test files as text. Tribunal writes
them into a private COPY of the worktree, runs the project's own test command there, and throws the copy away. They are
evidence, not part of the deliverable (and nothing they do can reach it): the sources and the outcome are kept in the run record (`inspector_tests/`,
`inspector_tests.json`). A failure becomes a P1 finding, which the existing correction rounds handle; the next review
is told what failed, so an inspector can correct a test of its own that was wrong.
"""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path, PurePosixPath
from typing import Any, Dict, List, Optional, Tuple

MAX_FILES = 3
MAX_CHARS = 20_000
TEST_DIRS = {"tests", "test", "__tests__", "spec", "specs"}
NAME = re.compile(r"^(test_inspector_[A-Za-z0-9_]+\.py|inspector_[A-Za-z0-9_]+\.(test|spec)\.(js|mjs|cjs|ts|tsx|jsx)|"
                  r"inspector_[A-Za-z0-9_]+_test\.go|InspectorTest[A-Za-z0-9]*\.(java|kt|cs))$")


def enabled(config: Optional[dict]) -> bool:
    """On by default; `autonomy.inspector_tests: false` turns it off. The quick profile sets that (small requests):
    a profile's knobs are merged into `autonomy` before a run starts (autopilot.profile_overrides)."""
    return bool(((config or {}).get("autonomy", {}) or {}).get("inspector_tests", True))


def prompt_section(verification: Optional[Dict[str, Any]]) -> str:
    """The paragraph added to a review prompt when Tribunal will run tests the inspector writes."""
    info = (verification or {}).get("inspector_tests")
    if not isinstance(info, dict) or not info.get("wanted"):
        return ""
    text = ("INDEPENDENT TESTS (optional): the tests in the diff were written by the same agent that wrote the code. "
            f"You may add up to {MAX_FILES} NEW test files that check the ACCEPTANCE CRITERIA from the outside, in the "
            'field "tests": [{"path": "<repo-relative path>", "content": "<full file text>"}]. Rules: you still modify '
            "nothing yourself — the Director runs these files in a throw-away copy of the project; new files only, inside an existing test directory, named like `test_inspector_<topic>.py` "
            "(or `inspector_<topic>.test.js`, `inspector_<topic>_test.go`); use only what the project already uses; "
            "assert only behaviour the ORDER states. If the existing tests already cover the criteria well, return "
            '"tests": [] — a wrong test costs a whole correction round.\n')
    previous = info.get("previous")
    if previous:
        text += ("YOUR TESTS FROM THE PREVIOUS ROUND FAILED. Decide whether the code is wrong or your test was, and "
                 "answer accordingly (keep, fix or drop the test):\n" + str(previous)[:1800] + "\n")
    return text + "\n"


def _reject(rel: Any, content: Any, worktree: Path) -> Optional[str]:
    from core.safety import SafetyPolicy
    if not isinstance(rel, str) or not isinstance(content, str) or not rel.strip() or not content.strip():
        return "path and content must be text"
    if len(content) > MAX_CHARS:
        return f"larger than {MAX_CHARS} characters"
    if "\\" in rel or rel.startswith(("/", "~")) or re.match(r"^[A-Za-z]:", rel):
        return "must be a repo-relative path with forward slashes"
    pure = PurePosixPath(rel)
    if any(part in ("..", ".", "") for part in pure.parts) or len(pure.parts) < 2:
        return "must be a plain relative path inside a test directory"
    if not NAME.match(pure.name):
        return "file name must mark it as an inspector test (e.g. test_inspector_<topic>.py)"
    if not TEST_DIRS & {part.lower() for part in pure.parts[:-1]}:
        return "must be inside a test directory (tests/, test/, __tests__/, spec/)"
    if SafetyPolicy.is_control_plane_path(rel):
        return "protected path"
    target = worktree / rel
    if not target.parent.is_dir():
        return "its directory does not exist in the project"
    if target.exists() or target.is_symlink():
        return "a file with this name already exists"
    if not SafetyPolicy.is_within_root(worktree, target.parent):
        return "outside the worktree"
    return None


def select(tests: Any, worktree_path: str) -> Tuple[List[Tuple[str, str]], List[Dict[str, str]]]:
    """(accepted [(path, content)], rejected [{path, reason}]). Nothing is written here."""
    from core import autopilot
    worktree = Path(worktree_path).resolve()
    accepted, rejected, seen = [], [], set()
    for item in list(tests or []):
        rel = getattr(item, "path", None) if not isinstance(item, dict) else item.get("path")
        content = getattr(item, "content", None) if not isinstance(item, dict) else item.get("content")
        reason = _reject(rel, content, worktree)
        if not reason and rel in seen:
            reason = "listed twice"
        if not reason and len(accepted) >= MAX_FILES:
            reason = f"more than {MAX_FILES} files"
        if not reason and autopilot.money_code_findings("", {rel: content}):
            reason = "contains code that could move real money"        # never executed, like any other such code
        if reason:
            rejected.append({"path": str(rel)[:200], "reason": reason})
        else:
            seen.add(rel)
            accepted.append((rel, content))
    return accepted, rejected


MAX_COPY_FILES = 40_000                         # a worktree larger than this is not copied: the check is skipped


def _copy(worktree: Path, sandbox: Path) -> bool:
    """A private copy of the worktree to run the extra tests in. False when it is too large to copy."""
    import os
    count = 0
    for _root, dirs, files in os.walk(worktree):
        dirs[:] = [d for d in dirs if d not in (".git", ".director_worktrees")]
        count += len(files)
        if count > MAX_COPY_FILES:
            return False
    shutil.copytree(worktree, sandbox, symlinks=True, ignore=shutil.ignore_patterns(".git", ".director_worktrees"))
    return True


def run(orch, run_id: str, review, worktree_path: Optional[str], verification: Optional[Dict[str, Any]], logger) -> None:
    """Run the tests the inspector proposed and fold the outcome into `review` (mutated in place).

    They never run in the worktree itself: the files are code nobody has reviewed, and whatever they write, change or
    delete must not reach the deliverable. They run in a copy that is thrown away afterwards."""
    from core.verifier import Verifier
    tests = list(getattr(review, "tests", None) or [])
    review.tests = []                              # only tests that ran and failed travel on with the review
    record: Dict[str, Any] = {"proposed": len(tests), "files": [], "rejected": [], "ran": False, "passed": None}
    out_dir = orch._get_run_dir(run_id) / "inspector_tests"
    shutil.rmtree(out_dir, ignore_errors=True)     # also clears a copy left behind by an interrupted run
    if not tests or not worktree_path or not Path(worktree_path).is_dir():
        orch._save_json(run_id, "inspector_tests.json", record)
        return
    accepted, record["rejected"] = select(tests, worktree_path)
    _, test_cmd, _ = orch._verification_cmds()
    worktree, sandbox = Path(worktree_path).resolve(), out_dir / "sandbox"
    skipped = ("no acceptable test file" if not accepted else "no test command is configured" if not test_cmd
               else "the project's own tests do not pass yet" if not (verification or {}).get("passed") else None)
    if not skipped and (out_dir.resolve() == worktree or worktree in out_dir.resolve().parents):
        skipped = "the run record is inside the worktree"          # a copy into itself would never end
    if not skipped:
        out_dir.mkdir(parents=True, exist_ok=True)
        if not _copy(worktree, sandbox):
            skipped = "the worktree is too large to copy"
    if skipped:
        record["skipped"] = skipped
        orch._save_json(run_id, "inspector_tests.json", record)
        return
    written: List[str] = []
    try:
        for rel, content in accepted:
            keep = out_dir / "files" / rel         # the source stays in the run record
            keep.parent.mkdir(parents=True, exist_ok=True)
            keep.write_text(content, encoding="utf-8")
            (sandbox / rel).write_text(content, encoding="utf-8")
            written.append(rel)
        result = Verifier.verify(worktree_path=str(sandbox), build_cmd=None, test_cmd=test_cmd, lint_cmd=None, git_checks=False)
    finally:
        shutil.rmtree(sandbox, ignore_errors=True)
    test = result.get("test") or {}
    record.update(ran=True, passed=bool(test.get("passed")), files=written, test_counts=result.get("test_counts"),
                  output_tail=str(test.get("output") or "")[-4000:])
    orch._save_json(run_id, "inspector_tests.json", record)
    orch.sm.log_audit(run_id, "ORCHESTRATOR", "INSPECTOR_TESTS",
                      json.dumps({"files": written, "passed": record["passed"], "rejected": record["rejected"]}, ensure_ascii=False)[:1000])
    if record["passed"]:
        review.summary = (review.summary or "") + f" [independent tests by the inspector: {len(written)} file(s), PASS]"
        logger.info(f"[Inspector tests] {len(written)} file(s) passed")
        return
    review.verdict = "changes_required"
    review.tests = [t for t in tests if getattr(t, "path", None) in written]      # what the Maker has to satisfy, or the next review to correct
    review.p1 = list(review.p1) + [
        "INSPECTOR_TEST_FAILED: independent tests written by the inspector fail (" + ", ".join(written) + "). "
        "Their source is in the review's `tests` field. Output tail: " + record["output_tail"][-900:]]
    logger.warning(f"[Inspector tests] failed: {', '.join(written)}")


def previous_failure(orch, run_id: str) -> Optional[str]:
    """What to tell the next review about the last round's own tests, when they failed."""
    record = orch._load_json(run_id, "inspector_tests.json")
    if not isinstance(record, dict) or record.get("passed") is not False:
        return None
    return "files: " + ", ".join(record.get("files") or []) + "\noutput tail:\n" + str(record.get("output_tail") or "")[-1400:]
