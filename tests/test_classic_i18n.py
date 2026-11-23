"""console/i18n_classic.js: the Details tab in English.

The tab is the classic page, rendered by the server in Korean; console.js translates its text where it stands. These
tests keep the dictionary complete as the Korean text grows, and pin what must NOT be translated (what people wrote).
"""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

import dashboard_i18n as K

ROOT = Path(__file__).resolve().parents[1]
CONSOLE = ROOT / "console"
HANGUL = re.compile("[가-힣]")


def exact():
    source = (CONSOLE / "i18n_classic.js").read_text(encoding="utf-8")
    start = source.index("const EXACT=") + len("const EXACT=")
    return json.loads(source[start:source.index(";\nconst RULES=")])


def translate(texts):
    if not shutil.which("node"):
        pytest.skip("node is not installed")
    script = ("global.window={};require(process.argv[1]);const tr=window.I18N_CLASSIC.tr;"
              "console.log(JSON.stringify(JSON.parse(require('fs').readFileSync(0,'utf8')).map(t=>tr(t))))")
    out = subprocess.run(["node", "-e", script, str(CONSOLE / "i18n_classic.js")], input=json.dumps(texts), capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def test_every_korean_text_of_the_tables_has_its_english():
    words = exact()
    wanted = []
    for table in (K.UI_TEXT, K.STATUS_TEXT, K.STATE_TEXT, K.RESULT_TEXT, K.ROLE_TEXT, K.SPEAKER_TEXT, K.STAGE_TEXT, K.HELP_TEXT, K.NEXT_STEP,
                  K.REASON_RECOMMENDATION):
        wanted += list(table.values())
    for title, why in K.REASON_TEXT.values():
        wanted += [title, why]
    wanted += [K._DEFAULT_RECOMMENDATION] + [text for _pattern, text, _kind in K._EVENT_RULES]
    missing = sorted({text for text in wanted if HANGUL.search(text) and text not in words})
    assert missing == [], f"add these to console/i18n_classic.js: {missing}"
    assert all(isinstance(v, str) for v in words.values())
    leftover = sorted(k for k, v in words.items() if HANGUL.search(v))
    assert leftover == [], f"these entries still hold Korean: {leftover}"


def test_the_sentences_the_server_puts_together_come_out_in_english():
    roles = {"OPENAI": "MAKER", "GOOGLE": "INSPECTOR", "ANTHROPIC": "ARCHITECT"}
    texts = [K.stage_sentence(state, roles, "3m50s") for state in
             ("PLANNING", "ORDER_READY", "BUILDING", "VERIFYING", "REVIEWING", "DECIDING", "PASS", "RECOVERED", "FAIL", "TIMEOUT",
              "HUMAN_REQUIRED", "REJECTED", "IDLE", "NONE")]
    statuses = list(K.STATUS_TEXT)
    for mode in ("NORMAL", "DEGRADED", "STOP"):
        for bad in statuses:
            for who in ("OPENAI", "GOOGLE", "ANTHROPIC"):
                texts.append(K.mode_sentence(mode, {**{d: "HEALTHY" for d in roles}, who: bad}))
    texts.append(K.mode_sentence("STOP", {"OPENAI": "AUTH_FAILED", "GOOGLE": "TIMEOUT", "ANTHROPIC": "QUOTA_EXHAUSTED"}))
    texts += [K.role_ko("ARCHITECT, INSPECTOR"), K.role_ko("MAKER"), "NONE (역할 없음)",
              # what the page's own script and the status payload put together
              "제작 중 · 4m6s", "지휘 중 · 제작", "결과물 0건", "승인 대기 2건", "적용 대기 결과물 1건", "나머지 4건 보기", "다음 단계: 최종 안전 검사",
              "5시간 30% · 주간 21%", "CODEX 복구 중", "테스트 통과  ·  감리 통과  ·  안전 검사 통과", "테스트 실패  ·  감리 실패  ·  안전 검사 실패",
              "변경 파일 3개  (추가 1 / 수정 2 / 삭제 0)",
              "변경 파일 3개  (추가 1 / 수정 2 / 삭제 0) · ※ 아직 적용하지 않은 이전 결과물 1건의 변경도 함께 적용됩니다",
              "완료 · 변경 파일 2개 · 적용 대기", "src/calc.py 변경 승인 필요", K.REASON_TEXT["HIGH_RISK"][0] + " 승인 필요", "확인하기 (읽기 전용)",
              "프로젝트: demo\n작업: RUN-1\n이 작업의 변경 파일: 2개", "프로젝트가 업데이트되었습니다 · 테스트 통과",
              "STALE RUN DETECTED (2) · 오래 멈춘 작업", "⚠ 작업 계획 수정 필요 · " + K.REASON_TEXT["SCOPE_VIOLATION"][0], "승인됨 · 작업 재개 중",
              "시스템 상태:", "결과: 폐기됨", "최근 오류: 없음", "사용량: 5시간 2% · 주간 1.7%", "역할: MAKER (제작)", "12.3초", "(상세 코드: REGRESSION)",
              K.UI_TEXT["apply_confirm_body"], K.UI_TEXT["discard_confirm_body"], "새 대화를 시작할까요?\n지금 대화는 화면에서 사라집니다. 기록은 서버에 남고, 프로젝트 선택은 그대로입니다."]
    out = translate(texts)
    still = [(before, after) for before, after in zip(texts, out) if HANGUL.search(after)]
    assert still == [], still
    by = dict(zip(texts, out))
    assert by[K.stage_sentence("BUILDING", roles, "3m50s")] == "Codex is writing the code · 3m50s"      # the name and the time survive
    assert by["결과물 0건"] == "Results (0)" and by["다음 단계: 최종 안전 검사"] == "Next step: Final safety check"
    assert by[K.role_ko("ARCHITECT, INSPECTOR")] == "ARCHITECT · INSPECTOR (Design · Inspect)"


def test_what_people_wrote_is_left_as_it_is():
    theirs = ["캡션 글자 수 검사기를 만들어줘. 플랫폼별 최대 글자 수를 넘으면 경고한다.", "12:30: 회의 메모를 정리해줘",
              "[작업 1/2] 실행 시작: src/calc.py에 clamp 함수를 추가한다", "paper-crane", "", "   ", "RUN-261123-ABCD"]
    assert translate(theirs) == theirs
    assert translate(["  사용량:  "]) == ["  Usage:  "]                       # the spacing around a text is kept


def test_the_details_tab_is_wired_to_its_dictionary():
    import companion_server
    html = (CONSOLE / "index.html").read_text(encoding="utf-8")
    scripts = re.findall(r'<script src="([^"]+)"', html)
    assert scripts.index("/i18n_classic.js") < scripts.index("/console.js") and scripts[0] == "/i18n.js"
    assert companion_server.STATIC_FILES["/i18n_classic.js"] == "i18n_classic.js"
    js = (CONSOLE / "console.js").read_text(encoding="utf-8")
    assert "english(doc);" in js and "window.I18N.lang==='en'" in js           # only while the console is in English
    assert "t==='TEXTAREA'" in js and "t==='PRE'&&!KEEP_PRE.has(e.id)" in js   # chat messages, file contents and drafts are not touched
    assert "if(now!==was)node.nodeValue=now" in js                             # an English text is written back to nothing: no loop
    assert "innerHTML" not in js[js.index("function english("):js.index("function setup(")]
    assert "'#project-name,#project-label,.pname,#rd-head,.evraw'" in js       # a folder name, a goal, a system line's original
    assert "[role=status],[role=alert],[aria-live]" in js and "nextEl.dataset.said!==nextText" in js   # nothing is read out twice


def test_the_page_as_the_server_renders_it_holds_no_text_without_english():
    """Catches Korean written straight into the page (dashboard_server.py) that the tables' test cannot see."""
    from html.parser import HTMLParser
    import dashboard_server as ds
    from core.chat_manager import ChatManager
    from core.state_machine import StateMachine
    StateMachine(); ChatManager()

    class Texts(HTMLParser):
        def __init__(self):
            super().__init__(); self.skip, self.found = [], []
        def handle_starttag(self, tag, attrs):
            a = dict(attrs)
            mine = tag in ("script", "style", "pre", "textarea", "code") or a.get("id") in ("project-name", "project-label", "rd-head") \
                or any(c in (a.get("class") or "").split() for c in ("pname", "evraw"))
            if tag not in ("br", "input", "img", "meta", "link", "hr"):
                self.skip.append(mine or bool(self.skip and self.skip[-1]))
            if not (self.skip and self.skip[-1]) or tag == "input":
                self.found += [a[k] for k in ("title", "placeholder", "aria-label") if a.get(k) and not (k == "title" and "evt" in (a.get("class") or "").split())]
        def handle_endtag(self, tag):
            if self.skip and tag not in ("br", "input", "img", "meta", "link", "hr"):
                self.skip.pop()
        def handle_data(self, data):
            if not (self.skip and self.skip[-1]) and data.strip():
                self.found.append(data.strip())
    parser = Texts(); parser.feed(ds.render_html())
    korean = sorted({t for t in parser.found if HANGUL.search(t)})
    assert korean, "the page should hold Korean text to translate"
    out = translate(korean)
    still = [(before, after) for before, after in zip(korean, out) if HANGUL.search(after)]
    assert still == [], f"add these to console/i18n_classic.js: {still}"


def test_the_ask_again_draft_comes_out_in_english():
    """It is written into the input box and sent to the ARCHITECT; in the English console it was Korean."""
    texts = []
    for code in [*K._RETRY_TEMPLATES, "HIGH_RISK", "UNKNOWN", "REGRESSION"]:
        texts += [K.retry_prompt(code, ""), K.retry_prompt(code, "src/app.py")]
    texts += ["src/a.py은(는) 수정하지 말고, " + K.REASON_TEXT["SCOPE_VIOLATION"][0] + " 부분을 작업 범위에서 제외한 뒤 기존 요청을 다시 계획해줘.",
              "수정하지 말고, 해당 문제 부분을 작업 범위에서 제외한 뒤 기존 요청을 다시 계획해줘."]       # the page's retryPromptJs
    out = translate(texts)
    assert [(a, b) for a, b in zip(texts, out) if HANGUL.search(b)] == []
    assert "src/app.py" in out[1]                                                 # the file name survives
    js = (CONSOLE / "console.js").read_text(encoding="utf-8")
    assert "'data-prompt'" in js[js.index("function english("):js.index("function setup(")]
