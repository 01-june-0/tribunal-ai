"""Workshop (the /classic page and its overlay): what the page says must be true, readable and usable."""
import json
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import dashboard_i18n
import dashboard_server as ds
from core import usage
from core.chat_manager import ChatManager
from core.state_machine import StateMachine

ROOT = Path(ds.__file__).resolve().parent


@pytest.fixture
def page():
    StateMachine(); ChatManager()
    return ds.render_html()


# ---------------------------------------------------------------- system notices
@pytest.mark.parametrize("raw,kind,text", [
    ("[미션 1/2] 실행 시작: Create clamp(). It raises ValueError if low > high.", "ev-info", "● 작업 단계를 시작했습니다."),
    ("[미션 2/3] 결과 PASS - tests failed earlier but pass now", "ev-ok", "✓ 작업 단계가 통과했습니다."),
    ("[작업 2/3] 결과 PASS - written after the wording change", "ev-ok", "✓ 작업 단계가 통과했습니다."),
    ("작업 시작 MSN-2: add a page", "ev-info", "● 작업을 시작했습니다."),
    ("[미션 2/3] 결과 HUMAN_REQUIRED - needs a look", "ev-bad", "⚠ 작업 단계가 통과하지 못했습니다."),
    ("미션 시작 MSN-1: fix the Error page", "ev-info", "● 작업을 시작했습니다."),
    ("[미션 2/3] ARCHITECT 계획: retry the failed step", "ev-info", "● ARCHITECT가 다음 단계를 계획했습니다."),
    ("결과물을 자동 적용하지 않았습니다: TypeError in hook", "ev-bad", "⚠ 결과물을 자동 적용하지 않았습니다."),
    ("ARCHITECT Error: boom", "ev-bad", "✗ 오류가 발생했습니다."),
    ("Run RUN-1 failed", "ev-bad", "✗ 오류가 발생했습니다."),
    ("the goal mentions ValueError and unfailed things", "ev-info", "· 시스템 알림"),     # a word inside a word is not an error
])
def test_system_notices_are_labelled_by_what_happened(raw, kind, text):
    assert dashboard_i18n.event_ko(raw) == (text, kind)
    label = next((lab for pat, lab, cls in ds.EVENT_LABELS if re.search(pat, raw)), None)
    assert (label == "ERROR") is (text == "✗ 오류가 발생했습니다.")              # the English badge agrees


def test_the_script_side_rules_are_the_same_as_the_server_side(page):
    js = page[page.index("var EVENT_LABELS = ["):]
    js = js[:js.index("];")]
    for pattern, label, _ in ds.EVENT_LABELS:                              # every server-side rule exists in the page script too
        assert "'" + label + "'" in js, label
    assert "실행 시작/" in js and "\\b" not in js                          # \\b means different things in Python and in a browser


def test_the_browser_labels_each_notice_the_way_the_server_does(page, tmp_path):
    """Run the page's own rule list in node against the same lines the server-side rules are tested with."""
    import json, shutil, subprocess
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    js = page[page.index("var EVENT_LABELS = ["):]
    js = js[:js.index("];") + 2]
    lines = ["[미션 1/3] 실행 시작: fix the Error page", "미션 시작 MSN-1: fix the Error page", "[미션 2/3] ARCHITECT 계획: retry the failed step", "ARCHITECT Error: boom", "Run RUN-1 failed",
             "the goal mentions ValueError and unfailed things", "오류Error처리", "BUSY now", "결과물을 적용했습니다 RUN-1"]
    script = js + "\nvar lines=" + json.dumps(lines, ensure_ascii=False) + ";\n" \
        "console.log(JSON.stringify(lines.map(function(l){for(var i=0;i<EVENT_LABELS.length;i++){if(EVENT_LABELS[i][0].test(l))return EVENT_LABELS[i][1];}return null;})));"
    path = tmp_path / "rules.js"
    path.write_text(script, encoding="utf-8")
    got = json.loads(subprocess.run([node, str(path)], capture_output=True, text=True, check=True, timeout=30).stdout)
    want = [next((lab for pat, lab, cls in ds.EVENT_LABELS if re.search(pat, line)), None) for line in lines]
    assert got == want
    assert got[3] == got[4] == "ERROR" and "ERROR" not in (got[0], got[1], got[2], got[5])


# ---------------------------------------------------------------- what the page says
def test_page_has_a_language_names_its_inputs_and_shows_no_internal_placeholders(page):
    assert '<html lang="ko">' in page
    assert 'id="project-input"' in page and 'aria-label="프로젝트 폴더 경로"' in page
    assert 'aria-label="ARCHITECT에게 보낼 메시지"' in page
    assert 'role="dialog" aria-modal="true"' in page                       # the result window
    for leftover in ("raw status:", "(read-only)", "click to expand", "New chat refused", "New chat failed", "역할 변경 버튼"):
        assert leftover not in page, leftover
    for name in ("OPENAI", "GOOGLE", "ANTHROPIC"):
        cell = re.search(rf'id="prov-{name}-error">([^<]*)<', page).group(1)
        assert cell not in ("NONE", "UNKNOWN")
    assert "#pending-list, #results-list { list-style: none;" in page       # the result list is not squeezed by a default indent


def test_chat_badge_says_ready_not_waiting_to_apply(page):
    assert dashboard_i18n.UI_TEXT["chat_ready"] == "입력 가능"
    badge = re.search(r'id="chat-badge"[^>]*>([^<]*)<', page).group(1)
    assert badge != dashboard_i18n.RESULT_TEXT["READY"]
    assert "ko(I18N.ui, 'chat_ready')" in page and "ko(I18N.result, 'READY'));" not in page


def test_no_project_is_a_hint_not_an_error(page):
    assert dashboard_i18n.UI_TEXT["no_project"] == "대화용 폴더 미선택"
    assert ".proj-none { color: var(--amber); }" in page


def test_local_time_label_and_plain_words():
    stamp = "2026-11-20T12:53:18.965539"
    expected = datetime(2026, 11, 20, 12, 53, 18, tzinfo=timezone.utc).astimezone().strftime("%m/%d %H:%M:%S")
    assert ds.local_time_label(stamp) == expected and ds.local_time_label(stamp + "Z") == expected
    assert ds.local_time_label(None) == "" and ds.local_time_label("not a time") == "not a time"
    assert ds._plain("UNKNOWN") == "알 수 없음" and ds._plain("NONE") == "없음" and ds._plain("codex-cli 0.171") == "codex-cli 0.171"


def test_script_guards_korean_input_and_asks_before_a_new_chat(page):
    assert "!ev.isComposing && ev.keyCode !== 229" in page                 # Enter that commits a syllable does not send
    assert "window.confirm('새 대화를 시작할까요?" in page
    assert "ev.key === 'Escape' && resultModalOpen" in page
    assert "li.tabIndex = 0; li.setAttribute('role', 'button');" in page


def test_bottom_bar_agrees_with_waiting_results(monkeypatch):
    StateMachine(); ChatManager()
    real = ds.build_status_payload

    def waiting():
        st = real()
        st.update(pending_result_count=3, todo="적용 대기 결과물 3건")
        return st
    monkeypatch.setattr(ds, "build_status_payload", waiting)
    html = ds.render_html()
    assert "안전 · 적용 대기 결과물 3건" in html and dashboard_i18n.UI_TEXT["safe_no_action"] not in re.search(r'id="alert-text"[^>]*>([^<]*)<', html).group(1)


# ---------------------------------------------------------------- results built on earlier results
def test_builds_on_lists_earlier_unapplied_runs(tmp_path, monkeypatch):
    from core.result_manager import ResultManager, RESULT_APPLIED
    rm = ResultManager.__new__(ResultManager)
    files = {"RUN-C": {"source_snapshot.json": {"base_worktree": "/p/.director_worktrees/RUN-B"}},
             "RUN-B": {"mission_base.json": {"base_worktree": "/p/.director_worktrees/RUN-A"}},
             "RUN-A": {"source_snapshot.json": {"base_ref": "abc"}}}
    states = {"RUN-B": "DISCARDED", "RUN-A": "READY"}
    rm._load = lambda run_id, name: files.get(run_id, {}).get(name)
    rm.sm = type("SM", (), {"get_result_state": staticmethod(lambda rid: {"state": states.get(rid)})})()
    assert rm.builds_on("RUN-C") == ["RUN-B", "RUN-A"]                      # a discarded one still travels in the worktree
    states["RUN-A"] = RESULT_APPLIED
    assert rm.builds_on("RUN-C") == ["RUN-B"] and rm.builds_on("RUN-A") == []
    states["RUN-B"] = RESULT_APPLIED                                        # an applied one already carried everything older
    states["RUN-A"] = "READY"
    assert rm.builds_on("RUN-C") == []
    states["RUN-B"] = "DISCARDED"
    files["RUN-B"]["result_state.json"] = {"state": RESULT_APPLIED}        # the file says applied even if the table lags
    assert rm.builds_on("RUN-C") == []
    del files["RUN-B"]["result_state.json"]
    states["RUN-A"] = "READY"
    files["RUN-A"]["source_snapshot.json"] = {"base_worktree": "/p/.director_worktrees/RUN-C"}     # a loop must end
    assert rm.builds_on("RUN-C") == ["RUN-B", "RUN-A"]
    rm._load = lambda *a: (_ for _ in ()).throw(OSError("unreadable"))
    assert rm._builds_on_safe("RUN-C") == []


def test_confirm_text_mentions_the_earlier_results(page):
    assert "function chainNote(res, sep)" in page and "이전 결과물 ' + n + '건의 변경도 함께 적용됩니다" in page
    assert "'\\n이 작업의 변경 파일: ' + res.changed_count + '개' + chainNote(res, '\\n')" in page


# ---------------------------------------------------------------- "today" in the usage table
@pytest.mark.skipif(not hasattr(time, "tzset"), reason="needs time.tzset")
def test_today_starts_at_local_midnight(monkeypatch):
    try:
        with monkeypatch.context() as m:                                    # only the time zone is undone, not the test database
            m.setenv("TZ", "America/New_York")                              # far from UTC, so a UTC "today" would fail here
            time.tzset()
            _check_today_window()
    finally:
        time.tzset()


def _check_today_window():
    midnight = datetime.combine(datetime.now().date(), datetime.min.time()).astimezone(timezone.utc).replace(tzinfo=None)
    assert midnight.hour in (4, 5)                                          # New York midnight in UTC

    def call(at):
        rid = usage.call_started(["claude", "--print"], "p")
        with usage._conn() as conn:
            conn.execute("UPDATE ai_usage SET started_at=?, status='OK', duration_sec=1 WHERE id=?", (at.isoformat(), rid))
    call(midnight + timedelta(minutes=1))
    call(midnight - timedelta(minutes=1))
    out = usage.summary()
    assert out["today"]["total"]["calls"] == 1 and out["all"]["total"]["calls"] == 2


# ---------------------------------------------------------------- the overlay (console/console.js, console/console.css)
def test_overlay_puts_the_working_area_first_and_leaves_roles_to_the_stage():
    js = (ROOT / "console" / "console.js").read_text(encoding="utf-8")
    css = (ROOT / "console" / "console.css").read_text(encoding="utf-8")
    for gone in ("ANTIGRAVITY / DEVELOPMENT WORKSPACE", "role-cycle", "method:'POST',headers:{'Content-Type':'application/json','X-Tribunal-Token':csrf}", "TRIAD 연구 배정", "9/30", "대화로 이동"):
        assert gone not in js, gone
    assert "역할은 한눈에 탭의 역할 메뉴에서 지정합니다" in js
    assert "main.after(doc.getElementById('corestrip'),doc.getElementById('role-notice'))" in js    # order in the page itself,
    assert "#ai-activity{order" not in css and ".role-notice{order" not in css and "#corestrip{order" not in css    # so keyboard and screen-reader order match what is seen
    assert "main.before(alertBar)" in js                                    # alerts (approve / reject) stay above the working area
    assert "\n.director-v2 .role-notice{color:#a5bbcd;font-size:12px;line-height:1.6;margin:8px 2px 18px}\n" in css
    assert "min-height:440px;height:calc(100vh" in css                      # a short window still shows the chat form
    assert "@media(max-width:1023px){.director-v2 #main>.panel{max-height:none}" in css      # the chat form is not clipped at 801-1023px
    assert "role-cycle" not in css and "calc(100vh - 430px)" not in css
    assert "결과물 {0}건이 적용을 기다립니다" in js
    for gone in ("ai-activity", "refreshActivity", "/ops/activity", "lastMissionProject"):      # mission, workload and call lists: stage only
        assert gone not in js and gone not in css, gone
    assert "#chat-action-card,.director-v2 #todo-approve-btn,.director-v2 #todo-reject-btn,.director-v2 #alert-approve-btn,.director-v2 #alert-reject-btn{display:none!important}" in css   # approve / reject once


# ---------------------------------------------------------------- readability and structure (second pass)
def test_nothing_in_the_workshop_is_set_smaller_than_12px(page):
    css = (ROOT / "console" / "console.css").read_text(encoding="utf-8")
    for text in (page, css):
        assert not re.search(r"font-size:\s*(?:\d|1[01])(?:\.\d+)?px", text)
        assert not re.search(r"font:[^;}]*?(?<![\d.])(?:\d|1[01])(?:\.\d+)?px\s*/", text) and not re.search(r"font:\s*(?:\d|1[01])(?:\.\d+)?px", text)


def test_chat_names_the_speaker_in_korean_and_roles_use_the_stage_words(page):
    assert dashboard_i18n.SPEAKER_TEXT["USER"] == "나" and dashboard_i18n.i18n_bundle()["speaker"]["USER"] == "나"
    assert "(I18N.speaker || {})[m.role] || m.role" in page
    assert dashboard_i18n.role_ko("ARCHITECT, MAKER, INSPECTOR") == "ARCHITECT · MAKER · INSPECTOR (설계 · 제작 · 감리)"
    cm = ChatManager(); sid = ds.active_session_id()
    cm.add_message(sid, "USER", "hello there")
    html = ds.render_html()
    assert "<strong>나</strong><pre>hello there</pre>" in html and "class='msg msg-USER'" in html


def test_any_ai_without_a_role_is_the_spare_one():
    roles = {"OPENAI": {"role": "BACKUP"}, "ANTHROPIC": {"role": "ARCHITECT, MAKER, INSPECTOR"}, "GOOGLE": {"role": "BACKUP"}}
    nodes = ds._node_activity("IDLE", roles)["nodes"]
    assert nodes["OPENAI"]["backup"] and nodes["GOOGLE"]["backup"] and not nodes["ANTHROPIC"]["backup"]
    for not_spare in ("NONE", "UNKNOWN", ""):                               # down, or not decided yet
        assert not ds._node_activity("IDLE", {"OPENAI": {"role": not_spare}})["nodes"]["OPENAI"]["backup"]


def test_page_regions_and_announcements(page):
    for part in ('<div id="hdr" role="banner">', '<div id="main" role="main">', '<div id="corestrip" role="region" aria-label="AI 상태">',
                 '<div id="chat-box" role="log" aria-live="polite" tabindex="0"', '<span id="alert-text" role="status"'):
        assert part in page, part
    js = (ROOT / "console" / "console.js").read_text(encoding="utf-8")
    css = (ROOT / "console" / "console.css").read_text(encoding="utf-8")
    assert "if(nextEl.dataset.said!==nextText){nextEl.dataset.said=nextText;nextEl.textContent=nextText;}" in js      # announced only when it changes
    assert ".director-v2 #hdr h1{position:absolute;width:1px;height:1px" in css and "#hdr h1{display:none}" not in css


def test_phone_width_keeps_the_stop_buttons_on_screen():
    css = (ROOT / "console" / "stage.css").read_text(encoding="utf-8")
    phone = css[css.index("@media(max-width:760px){\n  #stage{"):]
    phone = phone[:phone.index("\n}")]
    # The action row scrolls sideways from tablet width down, so the stop buttons come first from there on - found at
    # 768px, where "시스템 중지" (and in English "Halt work" too) had slid out of view.
    tablet = css[css.index("@media(max-width:1180px){"):]
    tablet = tablet[:tablet.index("\n}")]
    assert "#btn-broadcast,#btn-lang{order:1}" in tablet and "overflow-x:auto" in tablet
    assert "#topbar{background:#04060cf2}" in tablet                          # the page scrolls under the bar there
    assert ".brand{display:none}" in phone
    assert "overflow-x:auto" in phone and "display:none}   /*" not in phone   # nothing is taken away from a touch screen


# ---------------------------------------------------------------- AI cards at the bottom of the details tab
def test_ai_cards_show_real_usage_and_close_their_details(page, monkeypatch):
    from core import cli_limits, cli_settings
    monkeypatch.setattr(cli_settings, "load", lambda: {"antigravity": {"model": None}, "usage_poll_minutes": 5})
    monkeypatch.setattr(cli_limits, "snapshot", lambda model, interval: {
        "claude": {"plan": "team", "five_hour": {"used_percent": 30.0}, "weekly": {"used_percent": 21.5}},
        "openai": {"plan": None, "five_hour": None, "weekly": {"used_percent": 8.0}},
        "antigravity": {"state": "unavailable"}})
    assert ds._usage_line("ANTHROPIC") == "5시간 30% · 주간 21.5% · 요금제 team"
    assert ds._usage_line("OPENAI") == "주간 8%"
    assert ds._usage_line("GOOGLE") == "UNKNOWN" and ds._usage_line("NOPE") == "UNKNOWN"
    monkeypatch.setattr(cli_limits, "snapshot", lambda *a: (_ for _ in ()).throw(RuntimeError("cli gone")))
    assert ds._usage_line("ANTHROPIC") == "UNKNOWN"                        # the card never breaks the status payload
    assert "function closeNodeDetails(except)" in page and "e.key !== 'Escape'" in page
    css = (ROOT / "console" / "console.css").read_text(encoding="utf-8")
    short = css[css.index("/* AI cards on a short window"):]
    assert ".director-v2 .node table{display:block" in short and "table{display:none}" not in short     # state and role stay visible
    assert ".director-v2 .node tr:nth-child(n+3){display:none}" in short
