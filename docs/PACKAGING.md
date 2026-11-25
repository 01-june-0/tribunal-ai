# 배포 계획

Tribunal AI를 저장소를 받아 돌리는 프로젝트에서, **처음 바이브코딩을 하는 비개발자도 설치해서 쓰는 프로그램**으로 만드는
계획입니다. 단계마다 할 일, 끝났다고 볼 기준, 확인하는 방법을 적어 두고 그 순서대로 진행합니다.

진행 상황은 [CHANGELOG.md](CHANGELOG.md)에 남기고, 이 문서는 계획이 바뀔 때 고칩니다.

| 단계 | 상태 |
|---|---|
| 0. 기반 정리 | **끝남 (2026-11-24)** — `core/paths.py`, `core/pythons.py`, `pyproject.toml`, `tribunal` 명령. uv로 설치한 설치본(Python 3.9)이 저장소 없이 콘솔을 켜고 작업 하나를 끝까지 통과 |
| 1. 세 운영체제 자동 시험 | **끝남 (2026-11-24)** — `.github/workflows/tests.yml`: macOS · Windows · Linux(3.13)와 Linux(3.9)에서 테스트 모음 통과, 패키지를 만들어 설치하고 `tribunal doctor` 실행. 첫 Windows 실행의 실패 40개를 고침(제품 문제: SQLite 연결이 닫히지 않음, 경로 줄이기, 시간대 정보, 출력 인코딩) |
| 2. 처음 실행 도우미 | **만듦 (2026-11-24)** — `core/setup.py`, `console/setup.js`. 이 맥에서 실제 상태와 바꾼 응답(설치 안 됨 · npm 없음)으로 화면을 확인. 끝났다고 볼 기준(아무것도 없는 계정에서 도우미만 따라 첫 작업까지)은 아직 확인하지 않음 |
| 3. 설치 한 줄 + 바로 가기 | **만듦 (2026-11-25)** — `install.sh` · `install.ps1` · `uninstall.sh` · `uninstall.ps1`, `core/shortcuts.py`(`tribunal shortcut`). 이 맥에서 임시 폴더에 설치 · 다시 설치(업데이트) · 짧은 PATH로 아이콘 실행 · 지우기를 확인. GitHub Actions `installer` 작업이 깨끗한 macOS · Windows · Linux에서 설치 두 번 · 짧은 PATH로 아이콘 실행(Windows는 창 없는 `pythonw.exe`) · 콘솔 응답 · 지우기(기록은 남음)까지 통과(2026-11-25). 사람이 실제 화면에서 아이콘을 눌러 본 적은 아직 없음 |
| 4. 앱 창 | **만듦 (2026-11-25)** — `tribunal app`(`core/app_window.py`, pywebview). 바로 가기와 설치 마지막 단계가 창으로 엶. 이 맥에서 창 열기 · 콘솔 그리기 · 닫기 버튼과 Cmd+Q로 닫으면 콘솔도 꺼짐 · 다시 열어도 페이지 설정이 남음을 확인. GitHub Actions `installer` 작업에서 깨끗한 macOS · Windows가 아이콘으로 실제 창(Windows는 Edge WebView2)을 열어 콘솔이 그려지고 닫히면 콘솔도 꺼짐, Linux는 브라우저로 엶까지 통과(2026-11-25). 사람이 Windows 화면에서 직접 써 본 적과, 작업 중에 닫을 때의 확인 창을 실제 작업으로 띄워 본 적은 아직 없음 |
| 5 | 아직 |

## 1. 정한 것 (2026-11-24)

| 항목 | 결정 |
|---|---|
| 대상 | 바이브코딩을 처음 접하는 비개발자까지 |
| 형태 | 웹(브라우저로 여는 콘솔)과 앱(독립된 창) 둘 다. 같은 코드에서 나옴 |
| 운영체제 | macOS, Windows, Linux |
| 바탕 | `uv`로 설치하는 패키지 하나(`tribunal` 명령). 그 위에 설치 한 줄, 처음 실행 도우미, 나중에 앱 설치 파일 |
| AI CLI 안내 | 공식 설치 명령을 보여 주고, 사용자가 확인한 뒤 새 터미널 창에서 실행. 로그인도 같은 방식(이미 있는 AI 설정의 로그인 기능) |
| 비용 안내 | 처음 실행 도우미의 첫 화면과 README에 분명히 적음 (8절) |
| 저장소 | 공개(`github.com/01-june-0/tribunal-ai`). MIT 라이선스 유지 |

## 2. 구조

```
 [겉면 2] 앱 설치 파일      .dmg / Windows 설치 파일 / AppImage — 더블클릭으로 설치, 창으로 열림
 [겉면 1] 설치 한 줄        운영체제별로 붙여 넣는 한 줄 + 바탕화면 바로 가기 + 처음 실행 도우미
 [바탕]   패키지            uv tool install → `tribunal`(웹) · `tribunal app`(창) · `tribunal doctor`(점검)
```

- `uv`가 Python까지 받아 주므로 사용자가 Python을 따로 설치하지 않습니다.
- 웹과 앱은 같은 콘솔 서버를 씁니다. 앱은 그 화면을 브라우저 대신 창(pywebview)에 띄울 뿐입니다.

### 묶는 것과 묶을 수 없는 것

| 프로그램에 들어감 | 사용자 컴퓨터에 있어야 함 (도우미가 안내) |
|---|---|
| Tribunal 엔진, 콘솔 화면, 기본 설정, 보조 스크립트 | git |
| Python 실행 환경과 패키지(uv가 관리) | AI CLI 셋(`claude`, `codex`, `agy`) 중 둘 이상과 각 구독 로그인 |
| | 사용자 프로젝트의 도구(pytest, npm 등). 테스트는 그 프로젝트 환경에서 돌아야 함 |

## 3. 단계

| 단계 | 할 일 | 끝났다고 볼 기준 | 확인 방법 |
|---|---|---|---|
| **0. 기반 정리** | 데이터 위치 분리, 실행 파일 경로 정리, 패키지 구조 (4절) | 이 맥에서 `uv tool install`로 설치한 `tribunal`이 저장소 없이 동작하고, 저장소에서 돌리는 지금 방식도 그대로 동작 | 전체 테스트 + 설치본으로 가짜 CLI 작업 한 번 |
| **1. 세 운영체제 자동 시험** | GitHub Actions로 macOS · Windows · Linux에서 테스트 모음 실행 | 세 운영체제에서 모두 통과(또는 실패 원인을 고침) | Actions 결과 |
| **2. 처음 실행 도우미** | 점검 화면: 비용 안내 → git → AI CLI 설치 → 로그인 → 연습 프로젝트 (5절) | 아무것도 없는 사용자 계정에서 도우미만 따라 첫 작업까지 갈 수 있음 | 새 macOS 사용자 계정 · Linux 컨테이너 · (가능하면) Windows |
| **3. 설치 한 줄 + 바로 가기** | 운영체제별 설치 스크립트(uv 설치 → Tribunal 설치 → 바로 가기), 지우기 스크립트 (6절) | 한 줄 붙여 넣기로 설치하고 아이콘으로 열림, 지우기도 한 줄 | 깨끗한 환경에서 설치 · 실행 · 삭제 |
| **4. 앱 창** | `tribunal app` (pywebview). 창을 닫으면 서버도 끝남 (7절) | 브라우저 없이 같은 화면이 창으로 열림 | 세 운영체제 |
| **5. 설치 파일과 서명** | `.dmg` · Windows 설치 파일 · AppImage, 서명과 공증, 자동 업데이트, 동봉 고지문 | 경고 없이 설치되고 새 버전을 알려 줌 | 사용자가 생긴 뒤 진행 (Apple 개발자 계정 연 $99 필요) |

0~4단계는 비용이 들지 않습니다. 5단계는 쓰는 사람이 생긴 뒤에 시작합니다.

## 4. 0단계 상세

### 데이터 위치

지금은 기록과 설정을 저장소 폴더 기준으로 찾습니다. 설치본은 그 폴더에 쓸 수 없으므로 데이터 위치를 한 곳에서 정합니다.

| 어떻게 실행했나 | 데이터 위치 |
|---|---|
| 저장소에서 직접 (지금 방식) | 지금처럼 저장소의 `data/`, `runs/`, `config.local.yaml` — 기존 기록이 그대로 이어짐 |
| 설치본 | macOS `~/Library/Application Support/Tribunal AI`, Windows `%APPDATA%\Tribunal AI`, Linux `~/.local/share/tribunal-ai` |
| 포터블 (나중에) | 프로그램 옆 폴더 |
| `TRIBUNAL_HOME`을 지정 | 그 폴더 (시험용 · 고급 사용자) |

저장소 기준으로 경로를 만드는 곳(지금 확인한 것):

- `core/db_path.py` (`SOURCE_ROOT`) — 데이터베이스
- `core/result_manager.py` `run_dir`, `core/orchestrator.py` `_get_run_dir`, `core/work_log.py` `_runs_dir`, `dashboard_server.py`(recovery) — `runs/`
- `core/role_settings.py` — `data/role_settings.json`
- `core/cli_models.py` — `config.local.yaml`
- `core/companion_config.py`, `companion_server.py` — 포트 · 토큰 · 정적 파일
- `director.py` `load_config` — `config.yaml`
- `core/bootstrap.py` `SOURCE_ROOT` — "Tribunal 자기 폴더는 프로젝트로 고를 수 없음" 검사 (설치본에서도 유지)

`config.yaml`은 기본값으로 패키지에 들어가고, 사용자가 바꾼 값은 데이터 위치의 설정 파일에 둡니다.

### 실행 파일 경로

묶인 프로그램에서는 "지금 실행 중인 Python"(`sys.executable`)이 Python이 아니라 앱 실행 파일일 수 있습니다. 쓰임을 두 가지로 나눕니다.

- **Tribunal 자신의 Python**이 필요한 곳(보조 스크립트): `companion_server.py`(폴더 선택), `core/role_checks.py`
- **사용자 프로젝트의 Python**이 필요한 곳(테스트 · 실행): `core/verifier.py`, `agents/antigravity_maker.py`, `agents/mock_architect.py`

뒤쪽은 프로젝트의 가상환경 → `python3`/`python` 순으로 찾고, 제작 AI에게 알려 주는 "Python 버전"도 Tribunal이 아니라 프로젝트의
Python 기준으로 바꿉니다(실행해 보기에서 Tribunal 3.13 / 시스템 3.9가 어긋났던 문제와 같은 종류).

### 패키지 구조

- `pyproject.toml`: 이름 `tribunal-ai`, 명령 `tribunal`(웹), `tribunal app`(창, 4단계), `tribunal doctor`(점검), `tribunal stop`
- 콘솔 정적 파일(`console/`), 기본 설정, 보조 스크립트를 패키지 데이터로 포함
- 기존 `director.py` 명령(`do`, `mission`, `run`, `status` …)은 `tribunal`의 하위 명령으로도 쓸 수 있게
- 저장소에서 직접 돌리는 방법(`start-companion.sh` 등)은 개발용으로 계속 유지

## 5. 처음 실행 도우미 (2단계)

단계별 화면입니다. 처음 받은 사본(비용 안내를 읽은 기록도, 실행 기록도 없음)에서는 콘솔이 열릴 때 스스로 나오고, 그 뒤에는
**AI 설정 → 시작하기 도우미**로 엽니다. 일부러 AI 둘만 쓰는 사람에게 매번 뜨지 않도록, 빠진 것이 있다고 스스로 열리지는 않습니다.

1. **비용 안내** — 8절의 내용. "이해했습니다"를 눌러야 다음으로.
2. **git** — 있으면 통과. 없으면 운영체제별 공식 설치 방법을 보여 주고 확인 뒤 실행(Windows는 Git for Windows).
3. **AI CLI** — 셋 각각 설치 여부와 버전. 없으면 그 회사의 공식 설치 명령을 보여 주고, 확인을 받은 뒤 새 터미널 창에서 실행.
   설치 명령은 회사가 바꿀 수 있으므로 코드 한 곳(`core/setup.py`의 `COMMANDS`)에 모아 두고, 공식 안내 페이지 링크를 함께 보여 줌.
   세 회사 모두 Node.js가 필요 없는 자체 설치기가 있어 그것을 기본으로 씁니다(2026-11-24 공식 안내 기준). Codex는 "다른 방법: npm"도
   고를 수 있고, 그때 npm이 없으면 같은 방식으로 Node.js 설치를 먼저 안내합니다(macOS는 Homebrew가 있을 때 `brew install node`,
   Windows는 winget, 그 밖에는 공식 내려받기 페이지).
   페이지는 항목 이름과 보여 준 명령만 보내고, 서버는 자기 목록의 명령과 같을 때만 실행합니다. Linux는 터미널을 여는 방법이
   배포판마다 달라 명령을 보여 주고 붙여 넣게 합니다.
4. **로그인** — 지금 AI 설정의 로그인 기능 그대로. 둘 이상 준비되면 진행 가능, 나머지는 "나중에".
5. **연습 프로젝트** — 홈 폴더에 `Tribunal 연습`(영어 화면은 `Tribunal Practice`)을 만들어 프로젝트로 고르고, 첫 작업 예시를
   보여 줌. 같은 이름의 폴더가 이미 있고 비어 있지도 git 프로젝트도 아니면 `Tribunal 연습 2`처럼 다음 이름을 씁니다.
   「이 작업 시작하기」는 한눈에 탭의 입력창과 같은 길로 보냅니다.

원칙: Tribunal은 사용자의 확인 없이 아무것도 설치하지 않고, 실행할 명령은 그대로 보여 주며, 비밀번호 · 토큰을 묻거나 읽지 않습니다.

## 6. 설치 한 줄과 바로 가기 (3단계)

| | macOS · Linux | Windows |
|---|---|---|
| 한 줄 | `curl -LsSf https://raw.githubusercontent.com/01-june-0/tribunal-ai/main/install.sh \| sh` | `powershell -ExecutionPolicy ByPass -c "irm https://raw.githubusercontent.com/01-june-0/tribunal-ai/main/install.ps1 \| iex"` |
| 바로 가기 | macOS `~/Applications/Tribunal AI.app`(Spotlight · Launchpad), Linux `~/.local/share/applications/tribunal-ai.desktop`(앱 메뉴) | 시작 메뉴와 바탕화면의 `Tribunal AI.lnk` |
| 지우기 | 같은 주소의 `uninstall.sh` | 같은 주소의 `uninstall.ps1` |

- 순서: uv가 없으면 Astral의 공식 설치기로 설치 → `uv tool install --force --reinstall --managed-python --python 3.13 <GitHub 압축본>`
  (git 없이 받음, Python도 uv가 받음) → `tribunal shortcut` → 콘솔 열기. 다시 붙여 넣으면 켜진 콘솔을 끄고 최신 버전으로 바꿉니다.
- 바로 가기는 설치본의 Python으로 `-I -m tribunal_cli app --from-shortcut`을 실행합니다. `-I`는 아이콘이 시작되는 폴더(홈 폴더)의
  같은 이름 파일을 불러오지 않게 합니다. Windows는 창 없는 `pythonw.exe`로 시작하고, 콘솔 서버는 `python.exe`로 띄웁니다.
- 아이콘으로 연 프로그램은 짧은 PATH를 받으므로(macOS `/usr/bin:/bin:/usr/sbin:/sbin`), 시작하기 전에 로그인 셸의 PATH와 설치기가
  쓰는 폴더를 더합니다. 실패하면 터미널 대신 오류 창(macOS 알림 창, Windows 메시지 창, Linux zenity · kdialog · notify-send)에
  이유와 기록 위치를 보여 줍니다.
- 지우기는 콘솔 끄기 → 바로 가기 지우기 → `uv tool uninstall tribunal-ai` 순서이고, 기록 · 프로젝트 · 연습 폴더 · uv · AI CLI는
  남깁니다. 바로 가기는 Tribunal 표시가 있는 파일만 지우고, 같은 이름의 다른 파일은 건드리지 않습니다.
- Windows 스크립트는 `irm | iex`와 Windows PowerShell 5.1에서 읽히도록 영어(ASCII)로 씁니다. 두 설치 스크립트 모두 내용 전체를
  함수에 넣고 마지막 줄에서 부르므로, 내려받다 끊긴 스크립트는 아무것도 실행하지 않습니다.
- 확인 방법: GitHub Actions의 `installer` 작업이 세 운영체제에서 이 커밋으로 설치(두 번) → 짧은 PATH로 아이콘 실행 → 콘솔 응답 →
  지우기 → 바로 가기 · 명령이 없어지고 기록은 남는지까지 봅니다.
- 아이콘: 시안 C(삼각형, 2026-11-25 사용자 결정). 원본 `console/icons/tribunal.svg`에서 `scripts/make_icons.py`(맥에서, Chrome · sips ·
  iconutil)로 `tribunal.icns` · `tribunal.ico` · `tribunal-512.png`를 만들어 함께 커밋합니다. macOS 앱 번들의 `CFBundleIconFile`,
  Windows `.lnk`의 아이콘 위치, Linux `.desktop`의 `Icon=`, 앱 창(Dock · 작업 표시줄), 콘솔 탭(`/icon.svg`)에 씁니다.

## 7. 앱 창 (4단계)

`tribunal app`은 브라우저와 같은 콘솔 화면(`http://127.0.0.1:<포트>`)을 창 하나로 엽니다. 바로 가기와 설치 스크립트의 마지막
단계(`tribunal app --detach`)가 이것을 씁니다. `tribunal`(브라우저로 열기)은 그대로입니다.

| | 창 | 비고 |
|---|---|---|
| macOS | WebKit (pywebview + pyobjc) | 메뉴 막대는 "Tribunal AI"와 편집(복사 · 붙여넣기) · 보기 메뉴. Dock 그림은 앱 아이콘(pywebview 6.2부터). Dock은 아이콘(바로 가기 `Tribunal AI.app`)으로 열면 이름 "Tribunal AI"와 앱 아이콘을 보여 줌. 설치 마지막 단계도 그 앱을 엶. 터미널에서 `tribunal app`으로 띄우면 "python3.13"으로 보임 |
| Windows | Edge WebView2 (pywebview + pythonnet) | WebView2가 없으면 창 대신 브라우저로 엶(그때 pywebview는 IE로 넘어가는데, 콘솔이 돌지 않기 때문) |
| Linux | 없음 → 브라우저 | 창 라이브러리가 시스템의 GTK · Qt를 써야 하는데 설치본(uv가 만든 환경)에서는 보이지 않음 |

- pywebview(6.2 이상)는 macOS · Windows에서만 설치됩니다(`pyproject.toml`의 운영체제 조건). 6.2부터 Dock · 창 아이콘을 씁니다.
- **누가 콘솔을 끄나**: 창이 콘솔을 켰으면 그 창이 주인입니다(`data/app-owner.json`). 마지막 앱 창이 닫힐 때 주인이면 콘솔을
  끕니다. 이미 켜져 있던 콘솔(브라우저 · `tribunal start`로 켬)은 그대로 둡니다. 비정상 종료로 남은 주인 기록은 다음 창이 지웁니다.
- **작업 중에 닫으면**(사용자 결정, 2026-11-25): "작업이 진행 중입니다. 창을 닫으면 작업을 정지하고 콘솔을 끕니다" 확인 창. 확인하면
  작업 정지 버튼과 같은 정지(AI 프로세스 종료, 기록 · 작업 사본은 남아 나중에 이어 하기)를 한 뒤 콘솔을 끄고, 취소하면 창이 그대로
  있습니다. 작업 중인지 알 수 없을 때(응답 없음)도 묻습니다. 정지가 실패하면 콘솔을 끄지 않고 켜 둡니다.
- 모든 닫기(닫기 버튼, Cmd+Q, Alt+F4)는 한 번 보류한 뒤 따로 판단하고 닫습니다. macOS에서 보류하지 않은 Cmd+Q는 콘솔을 끄기 전에
  프로그램을 끝내 버리고, 닫기 처리 안에서 확인 창을 열면 스스로를 기다리며 멈추기 때문입니다(pywebview 6.2 코드로 확인).
- 페이지 설정(언어 · 시작 연출을 본 기록 등)은 창을 다시 열어도 남습니다(`private_mode=False`).
- 자동 시험: `tribunal app --smoke`(또는 `TRIBUNAL_APP_SMOKE=1`)는 창을 열어 콘솔이 그려졌는지 확인하고 스스로 닫습니다. 콘솔의
  보안 정책(CSP)이 `eval`을 막아 pywebview의 `evaluate_js` 대신 `run_js`로 읽습니다. 3분이 지나면 스스로 끝납니다.
- 남은 것: 창 두 개를 거의 동시에 닫으면 콘솔이 켜진 채 남을 수 있음(드묾, 다음에 열고 닫으면 꺼짐).

## 8. 비용 안내 (도우미 첫 화면과 README에 들어갈 내용)

- **Tribunal AI는 무료입니다**(MIT 라이선스). 종량제 API 요금을 쓰지 않습니다.
- **대신 AI 회사의 구독이 필요합니다.** Tribunal은 각 회사의 코딩 CLI를 사용자의 구독 로그인으로 부립니다.
  - Claude Code — Anthropic 구독
  - Codex — OpenAI(ChatGPT) 구독
  - Antigravity — Google 구독 또는 제공되는 사용 한도
  - 최소 두 개가 있어야 작업이 돌아갑니다(만드는 AI와 검토하는 AI가 달라야 하므로). 셋이면 하나가 한도에 걸려도 이어 갑니다.
- **작업마다 구독 한도를 씁니다.** 작업 하나에 AI 호출이 여러 번 들어가고, 자동 수정이 많을수록 더 씁니다. AI 설정에서 남은 한도를
  볼 수 있습니다.
- **요금과 한도는 각 회사가 정하고 바꿉니다.** Tribunal에 적힌 금액은 없고, 각 회사의 요금 안내를 따릅니다.

## 9. 라이선스와 공개 (2026-11-24 점검)

- **라이선스**: MIT. 원본 AI DEV DIRECTOR의 저작권 표시(DAVZD)와 이 프로젝트의 저작권 줄이 `LICENSE`에 함께 있습니다.
- **함께 쓰는 패키지**: PyYAML · pydantic · pytest · urllib3 등 MIT, click · psutil · idna 등 BSD, requests Apache-2.0, certifi MPL-2.0. 앱 창(4단계): pywebview BSD-3, pyobjc · pythonnet · bottle · proxy_tools MIT.
  0~4단계는 사용자 컴퓨터에 따로 설치되므로 따로 할 일이 없고, 5단계에서 설치 파일에 함께 묶을 때 각 고지문을 동봉합니다.
- **화면 코드**: 외부 라이브러리 · 글꼴 · 가져온 코드 없음.
- **이름**: Claude · Codex · Antigravity는 각 회사의 이름을 설명하는 데만 쓰고, 로고는 쓰지 않습니다.
- **각 서비스의 약관**: Tribunal은 각 CLI를 공식 명령으로 부를 뿐이지만, 구독을 자동으로 쓰는 방식이 각 회사 약관에 맞는지는 공개
  안내에 "각 서비스의 이용 약관을 따르세요"로 적습니다.
- **공개 전 점검**: 추적 파일과 커밋 기록 전체에 비밀 값 · 이 컴퓨터의 경로 · 실제 이메일 없음. 커밋 작성자 이메일은 공개(사용자 결정).

## 10. 열린 위험

- **Windows는 아직 한 번도 실제로 돌려 보지 않았습니다.** 1단계의 자동 시험이 첫 확인입니다.
- **AI CLI의 설치 방법과 로그인 방식은 회사가 바꿀 수 있습니다.** 도우미의 안내 문구와 명령은 한곳에 모아 고치기 쉽게 둡니다.
- **세 CLI 중 Antigravity는 로그인 · 로그아웃 명령과 계정 표시가 없습니다.** 도우미는 "터미널에서 열기"로 안내합니다.
- **비개발자는 오류 메시지를 읽기 어렵습니다.** 도우미와 실행해 보기의 오류는 무엇을 하면 되는지 한 줄로 말해야 합니다.
