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
    order = [esc.index(x) for x in ("closeRoleMenu(true)", "setChatLog(false)", "setAIPanel(false)", "closeResult()", "closeCall()", "leaveCloud()")]
    assert order == sorted(order) and esc.count("else if") == 5      # the cloud is the bottom layer: panels close first
    assert "replay" not in JS.lower() and "attract" not in JS      # the replay of a past task was removed
    assert "function openRecord(key){if(!$('ai-panel').hidden)setAIPanel(false,true);if(result)closeResult();" in JS
    assert "if(open){if(openKey!=null)closeCall();if(result)closeResult();" in JS
    assert "if(!$('ai-panel').hidden)setAIPanel(false,true);if(openKey!=null)closeCall();\n  resultOpener=document.activeElement;" in JS
    assert "closest('textarea,input,select,[contenteditable]')" in JS and "e.isComposing||e.repeat" in JS


def test_the_now_panel_does_not_announce_every_tick():
    assert 'id="panel-now" class="glass" aria-label=' in HTML and 'id="now-headline" aria-live="polite"' in HTML
    assert "if(node.textContent===who+rest)return;" in JS
    assert "STEP_MARK={ok:'✓',bad:'✗',warn:'!',off:'—',run:'▶',todo:''}" in JS


def test_short_windows_scroll_the_side_panels_instead_of_cutting_buttons_off():
    assert "overflow:hidden auto" in CSS and "#panel-now>*,#panel-work>*{flex:none}" in CSS
    wide = CSS[CSS.index("@media(max-width:1180px){"):]
    wide = wide[:wide.index("\n}")]
    assert ".meta-chip{display:none}" not in wide                           # the project stays reachable on a narrow window


def test_polls_do_not_pile_up():
    for flag in ("const pollActivity=guarded(", "const pollStatus=guarded(", "const pollRoles=guarded(", "const pollChat=guarded("):
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
    assert "$('attention-go').textContent=here?T('확인하기'):T('자세히 탭에서 확인')" in JS
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
        ("stopped", {"required": True, "state": "HUMAN_REQUIRED", "run_id": "RUN-OTHER", "in_mission": True}, {"status": "INCOMPLETE", "live": False, "steps": [step("PASS")]}),
        # a task stopped at its very start belongs to no mission yet: the card asks, whatever mission it shows (or none)
        ("approve", {"required": True, "state": "HUMAN_REQUIRED", "run_id": "RUN-NEW", "in_mission": False}, {"status": "DONE", "live": False, "steps": [step("PASS")]}),
        ("approve", {"required": True, "state": "HUMAN_REQUIRED", "run_id": "RUN-NEW", "in_mission": False}, None),
        (None, {"required": False}, {"status": "DONE", "live": False, "steps": [step("PASS")]}),
        (None, {"required": False}, {"status": "RUNNING", "live": True, "steps": [step("BUILDING")]}),
    ]
    script = "let status=null;\n" + src + "\nconst out=[];for(const [ap,ms] of " + json.dumps([[a, m] for _, a, m in cases]) + \
        "){status={approval:ap};out.push(attentionKind({mission:ms}));}\n" \
        "console.log(JSON.stringify(out));"
    assert json.loads(_node(tmp_path, script)) == [k for k, _, _ in cases]


def test_a_rejected_step_reads_as_closed_not_as_waiting(tmp_path):
    """The user said no: the chip, the badge and the box say so, and nothing asks for attention."""
    assert "state:s.rejected?'REJECTED':s.state" in JS and "REJECTED:'off'" in JS and ".steps .off{" in CSS
    assert "PULSE[STEP_CLASS[s.state]]" in JS                              # a class without a pulse colour sends none
    assert "kind==='stuck'||(kind==='stopped'&&!turnedDown(ms))" in JS     # no red frame around a decision the user made
    src = "const T=s=>s;const MISSION_BADGE={BLOCKED:['확인 필요','warn'],FAILED:['실패','bad']};\n" + \
        JS[JS.index("function turnedDown(ms){"):JS.index("\n", JS.index("function missionBadge(ms){"))]
    cases = [{"status": "BLOCKED", "live": False, "steps": [{"state": "PASS"}, {"state": "REJECTED"}]},
             {"status": "BLOCKED", "live": False, "steps": [{"state": "REJECTED"}, {"state": "HUMAN_REQUIRED"}]},   # a later step waits
             {"status": "RUNNING", "live": True, "steps": [{"state": "REJECTED"}]},                                 # planned again
             {"status": "FAILED", "live": False, "steps": [{"state": "FAIL"}]},
             {"status": "BLOCKED", "live": False, "steps": []}]
    out = json.loads(_node(tmp_path, src + "\nconsole.log(JSON.stringify(" + json.dumps(cases) + ".map(ms=>[turnedDown(ms),missionBadge(ms)[0]])));"))
    assert out == [[True, "거절함"], [False, "확인 필요"], [False, "RUNNING"], [False, "실패"], [False, "확인 필요"]]


def test_the_server_marks_a_step_the_user_rejected():
    import dashboard_server as d

    class SM:
        def __init__(self, audits): self.audits = audits
        def get_transitions(self, run_id): return [{"timestamp": "2026-01-01T00:00:01"}, {"timestamp": "2026-01-01T00:00:05"}]
        def get_audit_logs(self, run_id): return self.audits
        def get_run(self, run_id): return {"current_state": "HUMAN_REQUIRED"}
    no = [{"action": "HUMAN_REJECTED", "timestamp": "2026-01-01T00:00:09"}]
    assert d._step_rejected(SM(no), "RUN-1") is True
    assert d._step_rejected(SM([{"action": "HUMAN_REJECTED", "timestamp": "2026-01-01T00:00:03"}]), "RUN-1") is False   # an older stop
    assert d._step_rejected(SM([{"action": "HUMAN_APPROVAL", "timestamp": "2026-01-01T00:00:09"}]), "RUN-1") is False
    assert d._step_rejected(object(), "RUN-1") is False                    # unreadable record: not marked
    mission = {"mission_id": "M-1", "status": "BLOCKED", "steps": [{"index": 1, "run_id": "RUN-1", "order": {}, "result": {}}]}
    assert d.mission_view(mission, SM(no))["steps"][0]["rejected"] is True
    assert d.mission_view(mission, SM([]))["steps"][0]["rejected"] is False


def test_record_lines_in_the_chat_are_put_in_words():
    import dashboard_i18n as i
    assert i.event_line("HUMAN_REJECTED: run RUN-1 will not execute") == "○ 사용자가 거절했습니다. 이 작업은 실행되지 않습니다."
    assert i.event_ko("HUMAN_REJECTED: run RUN-1 will not execute")[1] == "ev-info"        # a decision, not an alarm
    assert i.event_line("HUMAN_APPROVED(ENTRY): resuming run RUN-1 (x)").startswith("✓ ")
    assert i.event_line("[작업 1/3] ARCHITECT 계획: 계산기 고치기") == ""                  # already says more in Korean
    assert i.event_line("ARCHITECT Error: timed out after 180s") == ""                     # the detail is the point
    assert i.event_line("something nobody mapped") == ""
    assert "said=role==='SYSTEM'&&KO&&msg.content_ko" in JS and "if(said)node.title=raw.slice(0,400);" in JS   # the record stays in the tooltip


def test_the_camera_follows_the_work_and_a_cloud_can_be_entered(tmp_path):
    scene = (CONSOLE / "trinity.js").read_text(encoding="utf-8")
    assert "look(slot,pull,d,k){" in scene and "const dist=need*f*cam.d" in scene and "still=true;" in scene   # reduced motion: no camera travel
    assert HTML.count('class="cloud-hit"') == 4 and 'id="inside"' in HTML and 'id="in-back"' in HTML
    assert "$('inside').inert=true;" in JS and "enterCloud(+b.dataset.slot)" in JS and "if(work){leaveCloud();" in JS
    assert "getJSON('/ops/record?key='+encodeURIComponent(key))" in JS[JS.index("async function pollInside(){"):JS.index("function enterCloud(slot){")]
    assert "if(inside!==at||insideKey!==key)return;" in JS                 # a late answer never paints another cloud or call
    view = JS[JS.index("function paintInside(){"):JS.index("async function pollInside(){")]
    assert "innerHTML" not in view                                         # commands and the model's words go in as text
    assert "ssig=JSON.stringify([d.key,d.status,d.found,ev.length" in view  # "still going" does not outlive the call
    assert "body.inside #panel-now" in CSS and ".slot-label.aside{" in CSS
    # one AI at work: the camera leans to it; none, two, or the intro: the whole scene; inside: that cloud, whatever works
    src = JS[JS.index("const LEAN="):JS.index("function insideCall(m){")]
    script = ("const T=s=>s,ROLES=['ARCHITECT','MAKER','INSPECTOR'],CORE=3,CORE_DIVE=.13;let calls=[],cls={has:false};"
              "const Trinity={look(...a){calls.push(a);}},document={body:{classList:{contains:()=>cls.has}},querySelectorAll:()=>[]};\n"
              + src + "\nconst w=(...r)=>({working:r.map(role=>({role}))});\n"
              "aimCamera(w('MAKER'));aimCamera(w());aimCamera(w('MAKER','INSPECTOR'));cls.has=true;aimCamera(w('ARCHITECT'));cls.has=false;"
              "aimCamera({working:[],phase:'VERIFYING'});inside=2;aimCamera(w('MAKER'));inside=3;aimCamera(w());console.log(JSON.stringify(calls));")
    assert json.loads(_node(tmp_path, script)) == [[1, .42, .78, 1.6], [-1], [-1], [-1], [3, 1, .84, 1.6], [2, 1, .085, 1.9], [3, 1, .13, 1.9]]


def test_the_core_shows_the_tests_tribunal_runs_itself():
    scene = (CONSOLE / "trinity.js").read_text(encoding="utf-8")
    assert "const to=slot===3?[0,0,0]:SLOTS[slot];" in scene              # the core is a place the camera can go
    assert 'data-slot="3" aria-label="TRIBUNAL 핵 안으로 들어가기"' in HTML and 'id="in-output"' in HTML
    assert "if(inside===3){if(m.logLost)return undefined;const run=(m.log||[]).find(r=>r.event==='verify');return run?run.key:null;}" in JS
    core = JS[JS.index("function paintCore(){"):JS.index("function tickInside(){")]
    assert "innerHTML" not in core and "out.textContent=" in core          # test output goes in as text
    assert "T('결과는 실행이 끝나면 나옵니다.')" in core                    # a run in progress has no record to stream: said, not faked
    assert "d.kind==='ai'&&d.run_id&&!orders.has(d.run_id)" in JS          # the order is fetched for calls only


def test_elapsed_time_and_time_of_day_are_two_functions(tmp_path):
    """The record's clock once shadowed the elapsed-time one of the same name: the labels showed a date."""
    assert JS.count("function clock(") == 1 and JS.count("function clockAt(") == 1
    src = JS[JS.index("function clock(sec){"):JS.index("\n", JS.index("function clock(sec){"))]
    assert _node(tmp_path, "const T=s=>s;" + src + "\nconsole.log(clock(75)+' '+clock(3725))") == "01:15 1:02:05"


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


def test_a_result_without_a_mission_can_be_read_and_decided_on_the_stage(tmp_path):
    """A task approved at its very start runs on its own: no mission, so no card. Its result is listed under the card.
    Whether a run belongs to a mission is the server's word (in_mission): the page sees only the newest few missions."""
    src = JS[JS.index("function looseResults(){"):JS.index("async function decideResult(runId,kind,extra){")]
    script = ("let status={results:[{run_id:'RUN-1',in_mission:true},{run_id:'RUN-OLD'},{run_id:'RUN-9',in_mission:false}],"
              "blocked_results:[{run_id:'RUN-B',in_mission:false,result_state:'APPLY_BLOCKED'}]};\n" + src +
              "\nconsole.log(JSON.stringify(looseResults().map(r=>r.run_id)));status=null;console.log(JSON.stringify(looseResults()));")
    assert _node(tmp_path, script).split("\n") == ['["RUN-9","RUN-B"]', "[]"]      # RUN-OLD (no word from the server) is not offered
    assert "activity" not in src
    assert "openResult({loose:true,id:r.run_id,deliverableRun:r.run_id" in JS and "paintAttention(m);paintDelivery(m);paintLoose(m);return;}" in JS   # also with no mission at all
    panel = JS[JS.index("function paintResult(){"):JS.index("function looseResults(){")]
    assert "decideResult(mine.ms.id,'apply',state==='blocked'?{on_conflict:'skip'}:{})" in panel and "APPLY_BLOCKED:'blocked'" in panel


def test_the_server_says_whether_a_run_belongs_to_a_mission(tmp_path, monkeypatch):
    import dashboard_server as d
    monkeypatch.setattr(d, "DIRECTOR_ROOT", tmp_path)
    (tmp_path / "runs" / "RUN-M").mkdir(parents=True)
    (tmp_path / "runs" / "RUN-M" / "mission_base.json").write_text('{"mission_id": "MSN-1", "base_worktree": null}', encoding="utf-8")
    (tmp_path / "runs" / "RUN-S").mkdir()
    (tmp_path / "runs" / "RUN-BAD").mkdir()
    (tmp_path / "runs" / "RUN-BAD" / "mission_base.json").write_text("{not json", encoding="utf-8")
    assert d._run_in_mission("RUN-M") is True and d._run_in_mission("RUN-S") is False and d._run_in_mission("RUN-NONE") is False
    assert d._run_in_mission("RUN-BAD") is True and d._run_in_mission("../x") is True and d._run_in_mission(None) is True   # in doubt: not offered on its own
    assert "ap.in_mission===false" in JS


def test_a_new_file_counts_its_lines_as_added(tmp_path):
    """Found on a real result: 4 new files read "+0줄". A new file is shown whole, without "+" marks."""
    src = JS[JS.index("function diffBody(text){"):JS.index("async function openResult(ms){")]
    out = _node(tmp_path, src + """
console.log(JSON.stringify([diffLines("(new file)\\nimport re\\n\\ndef f():\\n    return 1\\n"), diffLines("(new file)\\n"),
  diffLines("diff --git a/a b/a\\n--- a/a\\n+++ b/a\\n@@ -1 +1,2 @@\\n-x\\n+y\\n+z\\n"), diffLines("(new binary/unreadable file)"), diffLines("")]));""")
    assert json.loads(out) == [[4, 0], [0, 0], [2, 1], [0, 0], [0, 0]]


def test_a_task_called_done_with_nothing_passed_says_so_and_can_be_cleared():
    """Found in a real run: the ARCHITECT declared the goal met (a test meant to fail), no step passed, the card read
    "완료" with nothing to apply and two working copies nobody could remove from the screen."""
    assert "(ms.status==='DONE'&&!ms.deliverable&&ms.steps.length&&!ms.steps.some(s=>s.state==='PASS'))" in JS
    assert "검증을 통과한 단계가 없어 적용할 결과물이 없습니다" in JS
    assert "if(ms.status!=='DONE')row.append(again)" in JS and "if(!ms.deliverable&&ms.leftover){" in JS


def test_a_test_run_cut_off_by_the_time_limit_says_so(tmp_path):
    """Found in a real run: three rounds that each ran out of time read "테스트 결과 없음" in the record."""
    from core import work_log
    assert work_log._timed_out({"exit_code": -1, "output": "Command timed out after 10.0 seconds: HARD_TIMEOUT: Exceeded 10.0s"})
    assert not work_log._timed_out({"exit_code": 1, "output": "1 failed"}) and not work_log._timed_out({"exit_code": -1, "output": "boom"})
    assert not work_log._timed_out(None) and not work_log._timed_out({})
    src = "const T=(s,...a)=>s.replace(/\\{(\\d)\\}/g,(m,i)=>a[i]);\n" + JS[JS.index("function testLine(t){"):JS.index("\n", JS.index("function testLine(t){"))] \
        + "\n" + JS[JS.index("function verifyOutcome(r){"):JS.index("function logLine(r){")]
    out = _node(tmp_path, src + """
console.log(JSON.stringify([verifyOutcome({known:true,ran:true,timed_out:true,passed:false,counts:{passed:0,failed:0,total:0}}),
  verifyOutcome({known:true,ran:true,timed_out:false,passed:false,counts:{passed:1,failed:1,total:2}}), verifyOutcome({known:false})]));""")
    assert json.loads(out) == [["시간 초과 · 제한 시간 안에 끝나지 않음", "bad"], ["테스트 2개 중 1개 실패", "bad"], ["기록 없음", "off"]]


def test_a_step_that_is_not_finished_is_named_in_words(tmp_path):
    """Found on a stopped task: "2단계 · DECIDING"."""
    start = JS.index("const AT_STAGE=")
    src = ("const T=(s,...a)=>s.replace(/\\{(\\d)\\}/g,(m,i)=>a[i]);const STATE_KO={PASS:'통과',FAIL:'실패'};const testLine=()=>'';\n"
           + JS[start:JS.index("function orderDetails(runId){")])
    out = _node(tmp_path, src + """
console.log(JSON.stringify([stepNote({index:2,state:'DECIDING'},true), stepNote({index:1,state:'BUILDING'},false), stepNote({index:1,state:'PASS'},true),
  stepNote({index:3,state:'SOMETHING_NEW'},true)]));""")
    assert json.loads(out) == ["2단계 · 판단 중에 멈춤", "1단계 · 제작 중", "1단계 · 통과", "3단계 · SOMETHING_NEW"]
