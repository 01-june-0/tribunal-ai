"""
v3.0.8 MAKER PROMPT SIZE: a 310K-char Maker prompt (every test file writable) produced empty responses and 600 s
timeouts. Writable files are now ranked (required outputs, files the ORDER names, then smallest first) under a smaller
budget, overflow is listed by path only, and the Maker may answer with exact search/replace edits instead of
rewriting whole files. An edit whose anchor is missing or ambiguous rejects the whole batch before anything is written.
"""
import json
import sys

import pytest

from agents.proposal_maker import ProposalMaker
from core.cli_runner import ReadOnlyCliRunner
from schemas.order import OrderSchema


def write(root, rel, text):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def reply(monkeypatch, proposal, seen=None):
    def invoke(self, domain, prompt, cwd, stage):
        if seen is not None:
            seen["prompt"] = prompt
        return dict(output=json.dumps(proposal), invocation="t", exit_code=0, duration_sec=0)
    monkeypatch.setattr(ReadOnlyCliRunner, "invoke", invoke)


def test_exact_edits_change_only_the_anchored_text(tmp_path, monkeypatch):
    write(tmp_path, "backend/vision.py", "def parse(text):\n    return json.loads(text)\n\nTIMEOUT = 120\n")
    reply(monkeypatch, {"edits": [
        {"path": "backend/vision.py", "old": "    return json.loads(text)\n", "new": "    return json.loads(strip_fence(text))\n"},
        {"path": "backend/vision.py", "old": "TIMEOUT = 120", "new": "TIMEOUT = 45"}],
        "files": [{"path": "backend/fence.py", "content": "def strip_fence(t):\n    return t\n"}]})
    res = ProposalMaker(executable=sys.executable).run(OrderSchema(goal="g", allowed_paths=["backend/**"]), str(tmp_path))
    assert sorted(res.files_modified) == ["backend/fence.py", "backend/vision.py"]
    assert (tmp_path / "backend/vision.py").read_text(encoding="utf-8") == \
        "def parse(text):\n    return json.loads(strip_fence(text))\n\nTIMEOUT = 45\n"


@pytest.mark.parametrize("old, why", [("TIMEOUT = 999", "found 0"), ("x = 1", "found 2")])
def test_missing_or_ambiguous_anchor_rejects_the_whole_batch(tmp_path, monkeypatch, old, why):
    write(tmp_path, "src/a.py", "x = 1\nx = 1\n")
    write(tmp_path, "src/b.py", "B = 0\n")
    reply(monkeypatch, {"edits": [{"path": "src/b.py", "old": "B = 0", "new": "B = 1"},
                                  {"path": "src/a.py", "old": old, "new": "y"}]})
    with pytest.raises(ValueError, match=why):
        ProposalMaker(executable=sys.executable).run(OrderSchema(goal="g", allowed_paths=["src/**"]), str(tmp_path))
    assert (tmp_path / "src/b.py").read_text(encoding="utf-8") == "B = 0\n"          # nothing was written


def test_edits_obey_the_scope_guard_and_need_an_existing_file(tmp_path, monkeypatch):
    write(tmp_path, "secret/keys.py", "K = 1\n")
    reply(monkeypatch, {"edits": [{"path": "secret/keys.py", "old": "K = 1", "new": "K = 2"}]})
    maker = ProposalMaker(executable=sys.executable)
    with pytest.raises(ValueError, match="denied"):
        maker.run(OrderSchema(goal="g", allowed_paths=["src/**"]), str(tmp_path))
    reply(monkeypatch, {"edits": [{"path": "src/new.py", "old": "a", "new": "b"}]})
    with pytest.raises(ValueError, match="does not exist"):
        maker.run(OrderSchema(goal="g", allowed_paths=["src/**"]), str(tmp_path))


def test_large_writable_trees_are_ranked_and_overflow_is_listed_by_path(tmp_path, monkeypatch):
    for i in range(6):                                                    # 6 x 40 KB of writable tests
        write(tmp_path, f"backend/tests/test_big_{i}.py", "# " + "t" * 40_000 + "\n")
    write(tmp_path, "backend/tests/test_vision_lmstudio.py", "# NAMED-TEST-MARKER " + "n" * 50_000 + "\n")
    write(tmp_path, "backend/vision_lmstudio.py", "# REQUIRED-MARKER\n")
    seen = {}
    reply(monkeypatch, {"edits": [{"path": "backend/vision_lmstudio.py", "old": "# REQUIRED-MARKER", "new": "# done"}]}, seen)
    maker = ProposalMaker(executable=sys.executable)
    order = OrderSchema(goal="Parse fenced JSON; extend backend/tests/test_vision_lmstudio.py", allowed_paths=["backend/**"],
                        required_outputs=["backend/vision_lmstudio.py"])
    maker.run(order, str(tmp_path))
    info = maker.last_execution_info
    assert info["context_files"][:2] == ["backend/vision_lmstudio.py", "backend/tests/test_vision_lmstudio.py"]
    assert "NAMED-TEST-MARKER" in seen["prompt"] and info["omitted_files"]
    assert "WRITABLE FILES NOT SHOWN" in seen["prompt"] and info["omitted_files"][0] in seen["prompt"]
    assert info["prompt_chars"] < 200_000


def test_full_file_proposals_still_work(tmp_path, monkeypatch):
    reply(monkeypatch, {"files": [{"path": "src/a.py", "content": "A = 1\n"}]})
    res = ProposalMaker(executable=sys.executable).run(OrderSchema(goal="g", allowed_paths=["src/**"]), str(tmp_path))
    assert res.files_modified == ["src/a.py"] and (tmp_path / "src/a.py").read_text(encoding="utf-8") == "A = 1\n"


def test_anchor_miss_gets_retry_advice():
    from core.autopilot import maker_retry_feedback
    assert "verbatim" in maker_retry_feedback("Edit for a.py must match exactly once (found 0)",
                                        OrderSchema(goal="g", allowed_paths=["src/**"]))


def test_read_only_files_are_sent_by_how_much_they_have_to_do_with_the_order(tmp_path, monkeypatch):
    """A large project's unrelated read-only files used to fill 60 KB of every Maker call, alphabetically. What the
    ORDER names, what the writable files import and what sits beside them goes first; the rest gets a small share and
    is otherwise listed by path."""
    write(tmp_path, "src/app.py", "from lib.rates import rate\nimport lib.helpers\n\n\ndef total(x):\n    return x * rate()\n")
    write(tmp_path, "src/notes.md", "# BESIDE-MARKER\n")                                # same folder as the writable file
    write(tmp_path, "lib/rates.py", "# IMPORTED-MARKER\ndef rate():\n    return 2\n")
    write(tmp_path, "lib/helpers.py", "# IMPORTED-TOO\n")
    write(tmp_path, "docs/billing.md", "# NAMED-MARKER\n" + "n" * 30_000)               # named by the ORDER: goes first
    for i in range(8):                                                                   # 8 x 9 KB that nothing points at
        write(tmp_path, f"vendor/aaa_{i}.py", f"# DISTANT-{i}\n" + "d" * 9_000)
    seen = {}
    reply(monkeypatch, {"edits": [{"path": "src/app.py", "old": "return x * rate()", "new": "return x * rate() + 1"}]}, seen)
    maker = ProposalMaker(executable=sys.executable)
    maker.run(OrderSchema(goal="Add one to the total; the rules are in docs/billing.md", allowed_paths=["src/app.py"]), str(tmp_path))
    info, prompt = maker.last_execution_info, seen["prompt"]
    shown = info["context_files"]
    assert shown[0] == "src/app.py"                                                      # writable first, as before
    assert shown[1] == "docs/billing.md" and set(shown[2:4]) == {"lib/helpers.py", "lib/rates.py"} and shown[4] == "src/notes.md"
    for marker in ("NAMED-MARKER", "IMPORTED-MARKER", "IMPORTED-TOO", "BESIDE-MARKER"):
        assert marker in prompt
    distant = [f for f in shown if f.startswith("vendor/")]
    assert len(distant) == 2 and info["unread_files"] == 6                              # 20 KB of the unrelated, not all 72 KB
    assert "READ-ONLY FILES NOT SHOWN" in prompt and "vendor/aaa_7.py" in prompt and "DISTANT-7" not in prompt
    assert info["prompt_chars"] < 60_000
    # nothing left out in a small project: no such line at all
    small = tmp_path / "small"; small.mkdir()
    write(small, "src/a.py", "A = 1\n"); write(small, "README.md", "hello\n")
    reply(monkeypatch, {"edits": [{"path": "src/a.py", "old": "A = 1", "new": "A = 2"}]}, seen)
    maker.run(OrderSchema(goal="g", allowed_paths=["src/**"]), str(small))
    assert "READ-ONLY FILES NOT SHOWN" not in seen["prompt"] and maker.last_execution_info["unread_files"] == 0


def test_linked_files_follow_python_and_relative_js_imports(tmp_path):
    write(tmp_path, "pkg/__init__.py", ""); write(tmp_path, "pkg/core.py", "X = 1\n"); write(tmp_path, "util.py", "U = 1\n")
    write(tmp_path, "main.py", "import util, os\nfrom pkg.core import X\nfrom pkg import core\nimport missing.thing\n")
    write(tmp_path, "web/a.ts", "import {b} from './b'\nconst c = require('../shared/c.js')\nimport x from 'react'\n")
    write(tmp_path, "web/b.ts", "export const b = 1\n"); write(tmp_path, "shared/c.js", "module.exports = 1\n")
    found = ProposalMaker.linked_files([tmp_path / "main.py", tmp_path / "web/a.ts", tmp_path / "gone.py"], tmp_path)
    assert found == {"util.py", "pkg/core.py", "pkg/__init__.py", "web/b.ts", "shared/c.js"}


def test_callers_and_tests_of_a_writable_file_are_sent_and_relative_imports_are_followed(tmp_path, monkeypatch):
    """From the review: a file that imports the one being changed, and that file's tests, must not be cut as
    unrelated - the Maker cannot read them by itself and would break a call it never saw."""
    write(tmp_path, "src/pricing.py", "def price(x):\n    return x\n")
    write(tmp_path, "app/checkout.py", "# CALLER-MARKER\nfrom src.pricing import price\n" + "c" * 9_000)
    write(tmp_path, "tests/test_pricing.py", "# TEST-MARKER\n" + "t" * 9_000)
    write(tmp_path, "pkg/__init__.py", ""); write(tmp_path, "pkg/core.py", "# REL-MARKER\n")
    write(tmp_path, "pkg/use.py", "from . import core\nfrom .core import X\n")
    for i in range(6):
        write(tmp_path, f"vendor/zzz_{i}.py", "d" * 9_000)
    write(tmp_path, "a/README.md", "# README-A\n"); write(tmp_path, "b/README.md", "# README-B\n" + "r" * 30_000)
    seen = {}
    reply(monkeypatch, {"edits": [{"path": "src/pricing.py", "old": "return x", "new": "return x + 1"}]}, seen)
    maker = ProposalMaker(executable=sys.executable)
    maker.run(OrderSchema(goal="price adds one (see README.md)", allowed_paths=["src/pricing.py"]), str(tmp_path))
    prompt, shown = seen["prompt"], maker.last_execution_info["context_files"]
    assert "CALLER-MARKER" in prompt and "TEST-MARKER" in prompt
    assert shown.index("app/checkout.py") < shown.index("vendor/zzz_0.py") if "vendor/zzz_0.py" in shown else True
    assert "README-B" not in prompt                         # "README.md" is two files' name: naming it lifts neither
    linked = ProposalMaker.linked_files([tmp_path / "pkg/use.py"], tmp_path)
    assert linked == {"pkg/core.py"}                      # `from . import core` and `from .core import X`
