"""console/i18n.js: every Korean string in the stage console has an English entry, and slots survive translation."""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

CONSOLE = Path(__file__).resolve().parents[1] / "console"
HANGUL = re.compile(r"[가-힣]")


def _dictionary():
    source = (CONSOLE / "i18n.js").read_text(encoding="utf-8")
    start = source.index("const EN=") + len("const EN=")
    return json.JSONDecoder().raw_decode(source[start:])[0]


def _js_keys(name):
    text = (CONSOLE / name).read_text(encoding="utf-8")
    return {m.replace("\\n", "\n").replace("\\'", "'") for m in re.findall(r"T\('((?:[^'\\]|\\.)*)'", text)}


def test_every_string_in_the_scripts_has_an_english_entry():
    en = _dictionary()
    for name in ("stage.js", "console.js"):
        missing = sorted(k for k in _js_keys(name) if k not in en)
        assert missing == [], f"{name}: add these to console/i18n.js: {missing}"


def _stray_korean(text):
    """Korean inside any string literal that is not the argument of T(...)."""
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    text = re.sub(r"T\('(?:[^'\\\n]|\\.)*'", "T(", text)                 # the looked-up strings themselves
    text = re.sub(r"(?m)(^|[;{}\s])//[^\n]*", r"\1", text)                # line comments
    found = re.findall(r"'(?:[^'\\\n]|\\.)*'|\"(?:[^\"\\\n]|\\.)*\"|`(?:[^`\\]|\\.)*`", text)
    return [m for m in found if HANGUL.search(m)]


def test_no_korean_literal_escapes_the_lookup():
    """A Korean string outside T(...) would stay Korean in the English console. Allowed: number units used only in
    Korean mode, and the halt reason that is sent to the server rather than shown."""
    allowed = {"'억'", "'만'", "'console 작업 정지 버튼'"}
    for name in ("stage.js", "console.js"):
        stray = [m for m in _stray_korean((CONSOLE / name).read_text(encoding="utf-8")) if m not in allowed]
        assert stray == [], f"{name}: wrap in T(...): {stray}"


def test_the_stray_literal_check_really_catches_them():
    assert _stray_korean("x=T('가')+'나'") == ["'나'"]
    assert _stray_korean("a(T('가'),'나');f(T('a'),'b',\"다\");g(`라`)") == ["'나'", '"다"', "`라`"]
    assert _stray_korean("x=T('가 {0}',n) // 주석 '마'\n/* '바' */") == []


def test_every_static_string_in_the_page_has_an_english_entry():
    en = _dictionary()
    html = (CONSOLE / "index.html").read_text(encoding="utf-8")
    texts = {t.strip() for t in re.findall(r">([^<>]+)<", html) if HANGUL.search(t)}
    attrs = {v for _, v in re.findall(r'\b(title|placeholder|aria-label)="([^"]*)"', html) if HANGUL.search(v)}
    assert sorted(k for k in texts | attrs if k not in en) == []


def test_slots_are_the_same_on_both_sides_and_english_has_no_korean():
    for key, value in _dictionary().items():
        assert sorted(re.findall(r"\{\d\}", key)) == sorted(re.findall(r"\{\d\}", value)), key
        assert not HANGUL.search(value), key
        assert value.count("<") == key.count("<"), key                # markup, where present, is kept as is


def test_i18n_loads_first_and_is_served():
    html = (CONSOLE / "index.html").read_text(encoding="utf-8")
    scripts = re.findall(r'<script src="([^"]+)"', html)
    assert scripts[0] == "/i18n.js" and 'id="btn-lang"' in html
    import companion_server
    assert companion_server.STATIC_FILES["/i18n.js"] == "i18n.js"


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node")
def test_lookup_behaviour_in_both_languages():
    script = r"""
const fs=require('fs');
function load(lang){
  const store={};
  global.location={search:'?lang='+lang,href:'http://x/?lang='+lang};
  global.localStorage={getItem:k=>store[k]||null,setItem:(k,v)=>{store[k]=v;}};
  global.navigator={language:'ko-KR'};
  global.document={documentElement:{},body:null,getElementById:()=>null};
  global.window={};
  eval(fs.readFileSync(process.argv[1],'utf8'));
  return window.I18N;
}
const en=load('en'),ko=load('ko');
console.log(JSON.stringify([en.lang,en.t('보내기'),en.t('도구 {0}회',3),en.t('없는 문구 {0}',1),ko.lang,ko.t('보내기'),ko.t('도구 {0}회',3),
  en.t('{0} 미션 · 실제 기록 {1} → {2}배속','p','1m',8),en.t('약 {0} 남음 (추정)','$&')]));
"""
    out = subprocess.run(["node", "-e", script, str(CONSOLE / "i18n.js")], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    assert json.loads(out.stdout) == ["en", "Send", "3 tool calls", "없는 문구 1", "ko", "보내기", "도구 3회",
                                      "p mission · real record 1m → 8× speed", "about $& left (estimate)"]
