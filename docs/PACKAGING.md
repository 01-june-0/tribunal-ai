# 배포 계획

Tribunal AI를 저장소를 받아 돌리는 프로젝트에서, **처음 바이브코딩을 하는 비개발자도 설치해서 쓰는 프로그램**으로 만드는
계획입니다. 단계마다 할 일, 끝났다고 볼 기준, 확인하는 방법을 적어 두고 그 순서대로 진행합니다.

진행 상황은 [CHANGELOG.md](CHANGELOG.md)에 남기고, 이 문서는 계획이 바뀔 때 고칩니다.

| 단계 | 상태 |
|---|---|
| 0. 기반 정리 | **끝남 (2026-11-24)** — `core/paths.py`, `core/pythons.py`, `pyproject.toml`, `tribunal` 명령. uv로 설치한 설치본(Python 3.9)이 저장소 없이 콘솔을 켜고 작업 하나를 끝까지 통과 |
| 1. 세 운영체제 자동 시험 | **끝남 (2026-11-24)** — `.github/workflows/tests.yml`: macOS · Windows · Linux(3.13)와 Linux(3.9)에서 테스트 모음 통과, 패키지를 만들어 설치하고 `tribunal doctor` 실행. 첫 Windows 실행의 실패 40개를 고침(제품 문제: SQLite 연결이 닫히지 않음, 경로 줄이기, 시간대 정보, 출력 인코딩) |
| 2~5 | 아직 |

## 1. 정한 것 (2026-11-24)

| 항목 | 결정 |
|---|---|
| 대상 | 바이브코딩을 처음 접하는 비개발자까지 |
| 형태 | 웹(브라우저로 여는 콘솔)과 앱(독립된 창) 둘 다. 같은 코드에서 나옴 |
| 운영체제 | macOS, Windows, Linux |
| 바탕 | `uv`로 설치하는 패키지 하나(`tribunal` 명령). 그 위에 설치 한 줄, 처음 실행 도우미, 나중에 앱 설치 파일 |
| AI CLI 안내 | 공식 설치 명령을 보여 주고, 사용자가 확인한 뒤 새 터미널 창에서 실행. 로그인도 같은 방식(이미 있는 AI 설정의 로그인 기능) |
| 비용 안내 | 처음 실행 도우미의 첫 화면과 README에 분명히 적음 (6절) |
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
| **3. 설치 한 줄 + 바로 가기** | 운영체제별 설치 스크립트(uv 설치 → Tribunal 설치 → 바로 가기), 지우기 스크립트 | 한 줄 붙여 넣기로 설치하고 아이콘으로 열림, 지우기도 한 줄 | 깨끗한 환경에서 설치 · 실행 · 삭제 |
| **4. 앱 창** | `tribunal app` (pywebview). 창을 닫으면 서버도 끝남 | 브라우저 없이 같은 화면이 창으로 열림 | 세 운영체제 |
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

콘솔이 처음 열리면, 또는 필요한 것이 빠져 있으면 나오는 단계별 화면입니다. 언제든 다시 열 수 있습니다.

1. **비용 안내** — 6절의 내용. "이해했습니다"를 눌러야 다음으로.
2. **git** — 있으면 통과. 없으면 운영체제별 공식 설치 방법을 보여 주고 확인 뒤 실행(Windows는 Git for Windows).
3. **AI CLI** — 셋 각각 설치 여부와 버전. 없으면 그 회사의 공식 설치 명령을 보여 주고, 확인을 받은 뒤 새 터미널 창에서 실행.
   설치 명령은 회사가 바꿀 수 있으므로 코드 한 곳에 모아 두고, 공식 안내 페이지 링크를 함께 보여 줌.
4. **로그인** — 지금 AI 설정의 로그인 기능 그대로. 둘 이상 준비되면 진행 가능, 나머지는 "나중에".
5. **연습 프로젝트** — 빈 연습 폴더를 만들고 첫 작업 예시("무엇을 만들까요? 예: 계산기 창 앱을 만들어줘")를 보여 줌.

원칙: Tribunal은 사용자의 확인 없이 아무것도 설치하지 않고, 실행할 명령은 그대로 보여 주며, 비밀번호 · 토큰을 묻거나 읽지 않습니다.

## 6. 비용 안내 (도우미 첫 화면과 README에 들어갈 내용)

- **Tribunal AI는 무료입니다**(MIT 라이선스). 종량제 API 요금을 쓰지 않습니다.
- **대신 AI 회사의 구독이 필요합니다.** Tribunal은 각 회사의 코딩 CLI를 사용자의 구독 로그인으로 부립니다.
  - Claude Code — Anthropic 구독
  - Codex — OpenAI(ChatGPT) 구독
  - Antigravity — Google 구독 또는 제공되는 사용 한도
  - 최소 두 개가 있어야 작업이 돌아갑니다(만드는 AI와 검토하는 AI가 달라야 하므로). 셋이면 하나가 한도에 걸려도 이어 갑니다.
- **작업마다 구독 한도를 씁니다.** 작업 하나에 AI 호출이 여러 번 들어가고, 자동 수정이 많을수록 더 씁니다. AI 설정에서 남은 한도를
  볼 수 있습니다.
- **요금과 한도는 각 회사가 정하고 바꿉니다.** Tribunal에 적힌 금액은 없고, 각 회사의 요금 안내를 따릅니다.

## 7. 라이선스와 공개 (2026-11-24 점검)

- **라이선스**: MIT. 원본 AI DEV DIRECTOR의 저작권 표시(DAVZD)와 이 프로젝트의 저작권 줄이 `LICENSE`에 함께 있습니다.
- **함께 쓰는 패키지**: PyYAML · pydantic · pytest · urllib3 등 MIT, click · psutil · idna 등 BSD, requests Apache-2.0, certifi MPL-2.0.
  0~4단계는 사용자 컴퓨터에 따로 설치되므로 따로 할 일이 없고, 5단계에서 설치 파일에 함께 묶을 때 각 고지문을 동봉합니다.
- **화면 코드**: 외부 라이브러리 · 글꼴 · 가져온 코드 없음.
- **이름**: Claude · Codex · Antigravity는 각 회사의 이름을 설명하는 데만 쓰고, 로고는 쓰지 않습니다.
- **각 서비스의 약관**: Tribunal은 각 CLI를 공식 명령으로 부를 뿐이지만, 구독을 자동으로 쓰는 방식이 각 회사 약관에 맞는지는 공개
  안내에 "각 서비스의 이용 약관을 따르세요"로 적습니다.
- **공개 전 점검**: 추적 파일과 커밋 기록 전체에 비밀 값 · 이 컴퓨터의 경로 · 실제 이메일 없음. 커밋 작성자 이메일은 공개(사용자 결정).

## 8. 열린 위험

- **Windows는 아직 한 번도 실제로 돌려 보지 않았습니다.** 1단계의 자동 시험이 첫 확인입니다.
- **AI CLI의 설치 방법과 로그인 방식은 회사가 바꿀 수 있습니다.** 도우미의 안내 문구와 명령은 한곳에 모아 고치기 쉽게 둡니다.
- **세 CLI 중 Antigravity는 로그인 · 로그아웃 명령과 계정 표시가 없습니다.** 도우미는 "터미널에서 열기"로 안내합니다.
- **비개발자는 오류 메시지를 읽기 어렵습니다.** 도우미와 실행해 보기의 오류는 무엇을 하면 되는지 한 줄로 말해야 합니다.
