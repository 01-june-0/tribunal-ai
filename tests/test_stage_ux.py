"""Stage screen (console/index.html, stage.css, stage.js): what a user can lose, miss or not reach."""
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
    order = [esc.index(x) for x in ("closeRoleMenu(true)", "setChatLog(false)", "setAIPanel(false)", "closeCall()", "stopReplay()")]
    assert order == sorted(order) and esc.count("else if") == 4
    assert "function openCall(id){if(!$('ai-panel').hidden)setAIPanel(false,true);" in JS
    assert "if(open){if(openId!=null)closeCall();" in JS
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
