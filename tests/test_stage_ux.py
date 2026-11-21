"""Stage screen (console/index.html, stage.css, stage.js): what a user can lose, miss or not reach."""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

CONSOLE = Path(__file__).resolve().parent.parent / "console"
JS = (CONSOLE / "stage.js").read_text(encoding="utf-8")
CSS = (CONSOLE / "stage.css").read_text(encoding="utf-8")
HTML = (CONSOLE / "index.html").read_text(encoding="utf-8")


def test_script_parses():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    subprocess.run([node, "--check", str(CONSOLE / "stage.js")], check=True, timeout=30)


def test_nothing_on_the_stage_is_set_smaller_than_12px():
    assert not re.search(r"font-size:\s*(?:\d|1[01])(?:\.\d+)?px", CSS)
    assert not re.search(r"font:[^;}]*?(?<![\d.])(?:\d|1[01])(?:\.\d+)?px", CSS)


def test_notices_have_their_own_place_and_one_timer():
    assert '<div id="toast" role="status" hidden></div>' in HTML and "#toast{" in CSS
    assert "function notice(text){const s=$('toast');" in JS and "clearTimeout(noticeTimer)" in JS
    assert JS.count("$('shell-error')") == 2                                # only the connection message uses it now


def test_a_message_that_was_not_accepted_goes_back_into_the_box():
    assert "function restore(text)" in JS and JS.count("restore(text);notice(") == 2      # busy, or no answer at all
    assert "out.status==='error'||!res.ok)notice(" in JS                    # stored by the server already: not put back (no double send)
    assert "if(msg.id<=lastMsg)continue;" in JS and "const pollChat=guarded(" in JS             # no duplicate lines
    assert "!e.isComposing&&e.keyCode!==229" in JS                          # Korean input being composed is not sent


def test_applying_to_the_project_asks_first_and_reports_failures_honestly():
    assert "원본 프로젝트({0})에 적용할까요? 프로젝트의 파일이 바뀝니다." in JS
    assert "충돌한 파일은 건너뛰고 나머지 변경만 원본 프로젝트({0})에 적용할까요?" in JS
    assert "if(!res.ok||!out.status)throw Error(" in JS
    assert "if(box.dataset.sig===sig)return;" in JS and "b.disabled=deliveryBusy" in JS      # not rebuilt under the pointer


def test_role_labels_work_from_the_keyboard():
    for part in ("label.tabIndex=0", "label.setAttribute('role','button')", "label.setAttribute('aria-haspopup','menu')",
                 "function closeRoleMenu(refocus)", "e.key==='ArrowDown'||e.key==='ArrowUp'"):
        assert part in JS, part
    assert ".slot-label:focus-visible{outline:" in CSS
    assert "$('role-menu').hidden=true" not in JS                           # every close goes through closeRoleMenu


def test_escape_closes_one_layer_and_panels_do_not_stack():
    esc = JS[JS.index("if(e.key==='Escape'){"):]
    esc = esc[:esc.index("return;}") + 8]
    order = [esc.index(x) for x in ("closeRoleMenu(true)", "setChatLog(false)", "setAIPanel(false)", "closeResult()", "closeCall()", "stopReplay()")]
    assert order == sorted(order) and esc.count("else if") == 5
    assert "function openCall(id){if(!$('ai-panel').hidden)setAIPanel(false,true);if(result)closeResult();" in JS
    assert "if(open){if(openId!=null)closeCall();if(result)closeResult();" in JS
    assert "if(!$('ai-panel').hidden)setAIPanel(false,true);if(openId!=null)closeCall();\n  resultOpener=document.activeElement;" in JS
    assert "closest('textarea,input,select,[contenteditable]')" in JS and "e.isComposing||e.repeat" in JS


def test_the_now_panel_does_not_announce_every_tick():
    assert 'id="panel-now" class="glass" aria-label=' in HTML and 'id="now-headline" aria-live="polite"' in HTML
    assert "if(node.textContent===who+rest)return;" in JS
    assert "STEP_MARK={ok:'✓',bad:'✗',warn:'!',run:'▶',todo:''}" in JS


def test_short_windows_scroll_the_side_panels_instead_of_cutting_buttons_off():
    assert "overflow:hidden auto" in CSS and "#panel-now>*,#panel-work>*{flex:none}" in CSS
    wide = CSS[CSS.index("@media(max-width:1180px){"):]
    wide = wide[:wide.index("\n}")]
    assert ".meta-chip{display:none}" not in wide                           # the project stays reachable on a narrow window


def test_polls_do_not_pile_up():
    for flag in ("const pollActivity=guarded(", "const pollStatus=guarded(", "const pollRoles=guarded(", "const pollChat=guarded(",
                 "if(replayLoading)return;replayLoading=true;"):
        assert flag in JS, flag
    assert "activity=a;" in JS                                              # a failed answer never replaces the last good one


def test_a_poll_asked_for_while_one_is_running_runs_once_more(tmp_path):
    """The guard must not swallow the refresh asked for right after an action (apply, send, folder change)."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    src = JS[JS.index("function guarded(fn){"):JS.index("async function getJSON(url){")]
    script = src + """
let calls=0,release;const run=guarded(()=>{calls++;return new Promise(r=>{release=r;});});
(async()=>{const a=run(),b=run(),c=run();if(a!==b||b!==c)throw Error('not shared');
  await null;release();await new Promise(r=>setTimeout(r,10));if(calls!==2)throw Error('calls '+calls);
  release();await a;console.log('ok '+calls);})();"""
    path = tmp_path / "guard.js"
    path.write_text(script, encoding="utf-8")
    assert subprocess.run([node, str(path)], capture_output=True, text=True, check=True, timeout=30).stdout.strip() == "ok 2"


# ---------------------------------------------------------------- approval, "why it stopped" and the changes, on the stage
def test_the_card_asks_for_the_approval_itself():
    assert "function attentionKind(m){" in JS and "paintAttention(m);paintDelivery(m);" in JS
    assert "fetch(kind==='approve'?'/run/approve':'/run/reject'" in JS and "request_id:rid" in JS      # the same calls as the workshop
    assert "ms.steps.some(s=>s.run===ap.run_id)" in JS                    # only for a run of the mission that is shown
    assert "if(box.dataset.sig===sig)return;box.dataset.sig=sig;" in JS
    assert "$('attention-go').textContent=here?T('확인하기'):T('작업실에서 확인')" in JS
    assert "confirm(T('이 단계를 거절할까요? 거절하면 이 단계는 실행되지 않습니다.'))" in JS


def test_changes_are_seen_before_they_are_applied():
    assert 'id="result-panel" class="glass" role="dialog"' in HTML and 'id="rp-diff" tabindex="0"' in HTML
    assert "ms.deliverableRun?T('변경 내용 보기'):T('원본에 적용')" in JS and "apply.onclick=()=>{if(ms.deliverableRun)openResult(ms);else applyMission(ms,state);};" in JS
    assert "getJSON('/result?run_id='+encodeURIComponent(ms.deliverableRun))" in JS
    assert "diff.append(el('div',l||' '," in JS and "innerHTML" not in JS[JS.index("function paintResult()"):JS.index("function paintDelivery(m){")]   # file text is never parsed as markup
    assert "T('이 작업의 결과물을 원본 프로젝트({0})에 적용할까요? 프로젝트의 파일이 바뀝니다.'" in JS            # still confirmed


def test_why_a_task_stopped_is_put_in_words():
    for part in ("consecutive milestones failed", "step budget", "ARCHITECT could not plan the next step"):
        assert part in JS, part
    from core import mission
    src = Path(mission.__file__).read_text(encoding="utf-8")
    for engine in ('consecutive milestones failed"', 'f"step budget ({total}) used; next step was: ', 'f"ARCHITECT could not plan the next step: '):
        assert engine in src, engine                                       # the wording the stage matches is the engine's


def _node(tmp_path, script):
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    path = tmp_path / "case.js"
    path.write_text(script, encoding="utf-8")
    return subprocess.run([node, str(path)], capture_output=True, text=True, check=True, timeout=30).stdout.strip()


def test_which_block_the_card_shows_for_each_server_state(tmp_path):
    """attentionKind against the shapes dashboard_server.approval_info and mission_view really send."""
    src = JS[JS.index("const AT_WORK=new Set("):JS.index("function paintAttention(m){")]
    step = lambda state, run="RUN-B": {"run": run, "state": state}
    cases = [
        ("approve", {"required": True, "state": "HUMAN_REQUIRED", "run_id": "RUN-B"}, {"status": "BLOCKED", "live": False, "steps": [step("HUMAN_REQUIRED")]}),
        ("wait", {"required": False, "inflight": True, "state": "HUMAN_REQUIRED", "run_id": "RUN-B"}, {"status": "BLOCKED", "live": False, "steps": [step("HUMAN_REQUIRED")]}),
        # approved and picked up again: approval_info no longer says HUMAN_REQUIRED, the mission record still says BLOCKED
        ("wait", {"required": False, "state": "BUILDING", "run_id": "RUN-B"}, {"status": "BLOCKED", "live": False, "steps": [step("BUILDING")]}),
        ("stopped", {"required": False, "rejected": True, "state": "HUMAN_REQUIRED", "run_id": "RUN-B", "blocking": []}, {"status": "BLOCKED", "live": False, "steps": [step("HUMAN_REQUIRED")]}),
        ("stuck", {"required": False, "state": "HUMAN_REQUIRED", "run_id": "RUN-B", "blocking": [{"code": "REGRESSION"}]}, {"status": "BLOCKED", "live": False, "steps": [step("HUMAN_REQUIRED")]}),
        ("stopped", {"required": False, "state": "FAIL"}, {"status": "FAILED", "live": False, "steps": [step("FAIL")]}),
        # another mission's run waits for approval: this card does not offer to approve it
        ("stopped", {"required": True, "state": "HUMAN_REQUIRED", "run_id": "RUN-OTHER"}, {"status": "INCOMPLETE", "live": False, "steps": [step("PASS")]}),
        (None, {"required": False}, {"status": "DONE", "live": False, "steps": [step("PASS")]}),
        (None, {"required": False}, {"status": "RUNNING", "live": True, "steps": [step("BUILDING")]}),
    ]
    script = "let status=null;\n" + src + "\nconst out=[];for(const [ap,ms] of " + json.dumps([[a, m] for _, a, m in cases]) + \
        "){status={approval:ap};out.push(attentionKind({mode:'live',mission:ms}));}\n" \
        "status={approval:{required:true,state:'HUMAN_REQUIRED',run_id:'RUN-B'}};out.push(attentionKind({mode:'replay',mission:{status:'BLOCKED',live:false,steps:[{run:'RUN-B',state:'HUMAN_REQUIRED'}]}}));" \
        "console.log(JSON.stringify(out));"
    assert json.loads(_node(tmp_path, script)) == [k for k, _, _ in cases] + [None]      # and nothing is asked during a replay


def test_a_diff_keeps_lines_that_only_look_like_a_header(tmp_path):
    src = JS[JS.index("function diffBody(text){"):JS.index("async function openResult(ms){")]
    text = "diff --git a/q.sql b/q.sql\nindex 1..2 100644\n--- a/q.sql\n+++ b/q.sql\n@@ -1,2 +1,2 @@\n keep\n--- old comment\n+++ new comment"
    out = json.loads(_node(tmp_path, src + "\nconsole.log(JSON.stringify([diffBody(" + json.dumps(text) + "),diffLines(" + json.dumps(text) + ")]));"))
    assert out == [["@@ -1,2 +1,2 @@", " keep", "--- old comment", "+++ new comment"], [1, 1]]


def test_the_panel_decides_only_about_what_it_shows():
    panel = JS[JS.index("function paintResult(){"):JS.index("function paintDelivery(m){")]
    assert "now.status==='RUNNING'" in panel and "now.deliverableRun!==result.ms.deliverableRun" in panel and "if(!open||moved)return;" in panel
    assert "mine.done='applied'" in panel                                  # no second "원본에 적용" after it worked
    assert "const once=(node,sig,build)=>{if(node.dataset.sig===sig)return;" in panel       # a poll does not rebuild the diff being read
    assert "run_id:ms.deliverableRun" in JS and "decideMission(result.ms.id,'discard',{run_id:result.ms.deliverableRun})" in panel
