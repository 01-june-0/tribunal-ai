# 직접 실행 모드 계획

Tribunal AI를 Claude Code · Codex · Antigravity처럼 **실제 개발 도구로 쓸 수 있게** 만드는 계획입니다. 지금 Tribunal은
안전을 위해 아무것도 설치하지 않고, 제작 AI는 명령을 실행하지 못한 채 파일 내용을 JSON으로만 돌려줍니다. 그래서 라이브러리가
필요한 프로젝트("react로", "pygame으로")는 끝까지 가지 못합니다. 이 계획은 그 제한을 풀고, 대신 **설치할 때 사용자 동의**를
받습니다.

진행 상황은 [CHANGELOG.md](CHANGELOG.md)에 남기고, 이 문서는 계획이 바뀔 때 고칩니다.

| 단계 | 상태 |
|---|---|
| 1. 시안 | **끝남 (2026-11-26)** — 동의 화면 · 권한 메뉴, 사용자 확인 |
| 2. 엔진 | **만듦 (2026-11-26)** — `agents/agent_maker.py`, `core/cli_runner.py` `AgentCliRunner`, `core/cli_models.py`, 범위 검사 완화(`core/safety.py`), 설치물 `.gitignore`, 작업 폴더의 `.venv` 우선(`core/pythons.py`), `node_modules`가 있으면 `npm test`(`core/verifier.py`), 적용 때 프로젝트에 설치(`core/project_setup.py`). 가짜 CLI로 시험 |
| 3. 지키기 | **만듦 (2026-11-26)** — `core/agent_guard.py`(대리 실행 파일, 전체 경로 호출 찾기), 단계 뒤 멈춤(`GUARD_APPROVAL_REQUIRED`), 승인하면 그 명령을 허용하고 단계를 다시 돌림(`BUILDING`으로 재개). 이 맥에서 대리 실행 파일이 거절 · 기록 · 통과하는 것을 시험 |
| 4. 화면 | **만듦 (2026-11-26)** — 처음 실행 도우미 첫 단계의 동의, AI 설정의 권한, 콘솔 승인 카드, 설치 한 줄(sh · PowerShell)의 동의 질문, Windows 설치 파일의 동의 페이지(`tribunal consent --accept`) |
| 5. 실제 CLI 작업 | **확인 (2026-11-26, 이 맥)** — 미션 "pygame으로 벽돌깨기"(설계 Claude · 제작 Codex · 감리 Antigravity): Codex가 작업 폴더에 `.venv`를 만들어 pygame 2.6.1 · pytest를 설치하고 `.gitignore`를 씀, 승인 대기 없이 테스트 9개 통과로 끝남(충돌 테스트 2개를 고치는 데 자동 수정 4회). 가로채기: Codex · Claude · Antigravity를 직접 실행 모드로 돌려 `brew install` · `npm install -g` · `git push`를 시키자 셋 모두 거절(종료 코드 126)되고 기록됨(Claude는 push를 스스로 안 함). 이때 Claude가 키체인을 읽는 `security`까지 가로채 로그인이 풀리는 문제를 찾아 뺌. 승인 → 단계 다시 돌리기도 확인(2026-11-27, Codex): `brew install --dry-run cowsay`가 필요한 작업이 `GUARD_APPROVAL_REQUIRED`로 멈추고(파일에 거절 종료 코드 126), 승인하자 그 명령만 허용 목록에 들어가 단계가 다시 돌며 실제로 실행(종료 코드 0)된 뒤 테스트·감리·판정을 거쳐 PASS. 거절하면 아무것도 더 실행되지 않고 HUMAN_REQUIRED로 끝남. 미션 안에서도 확인(2026-11-27): 같은 작업의 미션이 BLOCKED로 멈추고, 콘솔의 승인 함수(`approve_run`)로 승인하자 그 단계가 다시 돌아 PASS, 미션이 이어져 DONE으로 끝남 |
| 6. 개발 도구로 넓히기 | 아직 |

## 1. 정한 것 (2026-11-26)

| 항목 | 결정 |
|---|---|
| 순서 | 의존성만 대신 설치하는 중간 단계를 건너뛰고 **바로 직접 실행 모드**로 |
| 제작 AI | 작업 폴더(worktree) 안에서 파일 읽기 · 쓰기, 명령 실행, 패키지 설치, 테스트 실행을 직접 함 |
| 계속 사람에게 묻는 것 | ① 시스템 전체 설치 ② 돈 · 자격 증명 ③ 되돌릴 수 없는 작업. **권한 설정 메뉴에서 항목마다 켜고 끌 수 있음**(기본: 모두 켬) |
| 항목과 관계없이 유지 | 작업 폴더 분리(적용 전에는 프로젝트를 건드리지 않음), `.git` · Tribunal 내부 폴더 보호 |
| 동의 받는 곳 | Windows 설치 파일의 동의 화면 + 설치 한 줄의 확인 + **처음 실행 도우미**(`.dmg` · AppImage는 설치 단계가 없어 여기서만 막을 수 있음). 체크하지 않으면 진행되지 않음 |
| 동의 기록 | 약관 버전과 함께 저장. 약관이 바뀌면 다시 물음 |

## 2. 권한 메뉴(켜고 끄기)가 가능한가: 가능

세 CLI 모두 사람에게 묻지 않고 실행하는 옵션이 있습니다(이 맥에서 `--help`로 확인).

| CLI | 직접 실행 모드에서 쓸 옵션 |
|---|---|
| Claude Code | `--permission-mode bypassPermissions` (또는 `--dangerously-skip-permissions`), 도구 제한(`--tools Read,Grep,Glob`) 해제 |
| Codex | `exec --dangerously-bypass-approvals-and-sandbox` (지금은 `--sandbox read-only`) |
| Antigravity | `--dangerously-skip-permissions`, `--mode auto` (지금은 `--sandbox`) |

이렇게 열면 CLI는 아무것도 묻지 않으므로, "묻는 항목"은 Tribunal이 따로 지킵니다. 세 CLI에 똑같이 쓰는 방법은 다음과 같습니다.

- **명령 가로채기(①③):** 제작 AI가 실행하는 셸의 PATH 맨 앞에 Tribunal의 폴더를 두고, 그 안에 `sudo` · `brew` · `apt` ·
  `apt-get` · `winget` · `choco` 같은 시스템 설치 명령, 전역 설치(`npm -g`, 가상환경 밖 `pip install`), 되돌릴 수 없는 명령
  (`git push`, `npm publish`, 배포 CLI)의 대리 실행 파일을 둡니다. 켜진 항목에 걸리면 실행하지 않고 "사용자 승인이 필요함"을
  돌려주며 그 요청을 기록합니다. 꺼진 항목이면 원래 명령을 그대로 실행합니다.
- **멈추고 묻기:** 단계가 끝난 뒤 기록된 요청이 있으면 작업을 사람 확인 대기(HUMAN_REQUIRED)로 멈추고, 콘솔에 "AI가
  `brew install ffmpeg`을 실행하려 합니다"처럼 보여 줍니다. 허락하면 그 명령을 허용한 채 그 단계를 다시 돌립니다. CLI가 명령을
  기다리게 하지 않는 이유는 CLI마다 명령 시간 제한(Claude Bash 기본 2분)이 있어서 기다리는 동안 끊기기 때문입니다.
- **돈 · 자격 증명(②):** 이미 있는 장치를 씁니다. 결제 SDK · 주문 코드가 추가되면 멈추는 `LIVE_MONEY_CODE`, 설계 AI가 돈 ·
  자격 증명 · 되돌릴 수 없는 결정을 사람에게 넘기는 `USER_DECISION_REQUIRED`. 메뉴에서 끄면 이 두 장치가 멈추지 않습니다.
- **로그인 셸:** CLI는 명령을 `zsh -lc`처럼 로그인 셸로 돌리는데, macOS의 `path_helper`와 `brew shellenv`가 프로필에서
  `/usr/bin`과 Homebrew를 다시 앞에 둡니다. 그래서 `ZDOTDIR`을 Tribunal의 폴더로 돌려 사용자의 zsh 파일을 그대로 읽은 뒤
  대리 실행 파일을 다시 앞에 두고, `bash -c`에는 `BASH_ENV`로 같은 일을 합니다. 이 맥에서 `zsh -lc` · `bash -lc` · `bash -c` ·
  `sh -c` 모두 대리 실행 파일이 먼저 잡히는 것을 시험했습니다.
- **커밋:** 제작 AI가 작업 폴더에서 커밋하면 모든 검사(HEAD와 비교)에서 빠지므로, 단계가 끝나면 HEAD를 원래대로 되돌립니다
  (파일은 그대로 남아 검사를 받음).
- **한계:**
  - **전체 경로로 부른 명령(2026-11-27 보강):** Claude는 명령 실행 직전 검사(hook, `--settings`)가 `/usr/bin/sudo`처럼 전체 경로로 부른 것도 막습니다(실제 호출로 확인). Codex · Antigravity는 막지 못하지만, 단계가 끝난 뒤 각 CLI의 실행 기록(Claude `stream-json`, Codex `--json`, Antigravity `run_command`)에서 찾아 "이미 실행됨"으로 묻습니다(Codex 실제 호출로 확인). 명령 줄 해석은 셸 예약어(`if … then`), 감싸는 명령(`env`, `timeout`, `nice`, `xargs` …), `eval`, `$(…)`, 백틱, `sh -c`, `cmd /c`, `powershell -Command`를 열고, 리다이렉션과 heredoc 본문은 뺍니다. `curl … | sh`는 시스템 설치로 묻습니다. hook이 오류 나면 막습니다.
    점은 동의 화면에 적었습니다.
  - 허락은 프로그램 · 옵션(순서 무관) · 나머지 인자(순서 그대로)로 맞춰 봅니다. `sudo`처럼 비밀번호가 필요한 명령은 승인 카드가 "터미널에서 직접 실행한 뒤 승인"을 안내하고, 제작 AI는 그 명령을 다시 실행하지 않고 결과만 확인합니다.
  - Tribunal이 부르는 Claude는 사용자의 `~/.claude` 설정(CLAUDE.md · hook · 플러그인)을 읽지 않습니다(`--setting-sources project,local`, 실제 호출로 확인). 프로젝트 자체의 설정은 읽습니다.
  - Windows: GitHub Actions의 Windows 실행기에서 cmd · PowerShell · Git Bash(`bash -c`) · Git Bash 로그인 셸(`bash -lc`) 네 셸 모두 `brew install` · `npm install -g` · `git push` · `pip install --user`를 대리 실행 파일이 먼저 잡아 거절함을 확인(2026-11-27, `tests.yml`의 결과표 단계). PowerShell에서는 종료 코드가 126이 아니라 1로 보이지만 거절·기록은 같음.
  - 실제 CLI(특히 Claude Code의 셸 스냅샷)로는 아직 시험하지 않았습니다.

## 3. 바꾸는 곳

| 영역 | 지금 | 바꾼 뒤 |
|---|---|---|
| 제작 AI (`agents/`) | `proposal`: 도구 없이 파일 내용을 JSON으로 받음 | 새 `agent` 모드: CLI가 작업 폴더에서 직접 고치고 설치하고 테스트함. 끝나면 요약과 실행 방법(`run`)만 JSON으로 받음. `proposal`은 설정으로 남김 |
| CLI 인자 (`core/cli_models.py`, `core/cli_runner.py`) | 읽기 전용 | 제작 AI만 위 표의 옵션. 설계 · 검사 AI는 지금처럼 읽기 전용 |
| 안전 검사 (`core/safety.py`) | 의존성 · 권한 파일을 고치면 매번 멈춤 | 멈추지 않음. 잠금 파일(`package-lock.json` 등)은 변경량 한도에서 뺌. `.git` · 내부 폴더 보호와 작업 폴더 밖으로 나가는 경로 검사는 유지 |
| 설치물 | 없음 | `node_modules` · `.venv` · 캐시 · 빌드 결과는 작업 폴더에만 두고, 차이 계산 · 검사 · 적용에서 뺌(작업 폴더의 git 제외 목록) |
| 검증 (`core/verifier.py`) | 설치 안 함, 의존성 있는 `npm test`는 건너뜀 | 제작 AI가 설치해 둔 작업 폴더에서 바로 테스트. 프로젝트 `.venv`의 Python 사용 |
| 동의 | 없음 | 설치 파일 · 설치 한 줄 · 처음 실행 도우미 (화면은 시안을 먼저 보고 정함) |
| 권한 메뉴 | 없음 | 콘솔 설정에 세 항목 켜고 끄기 (시안을 먼저 보고 정함) |

## 4. 순서

1. 시안: 동의 화면, 권한 메뉴 → 사용자 확인
2. 엔진: `agent` 모드 제작 AI, CLI 인자, 설치물 제외, 안전 검사 완화, 검증 → 가짜 CLI로 시험
3. 지키기: 명령 가로채기 + 실행 기록 확인 + 멈추고 묻기 → 시험
4. 화면: 동의(도우미 · 설치 한 줄 · Windows 설치 파일), 권한 메뉴
5. **실제 CLI로 작업 한 번**(사용자 허락 뒤): 예) "pygame으로 벽돌깨기", "Vite + React로 할 일 목록"
6. 그다음 개발 도구로 넓히기: 기존 프로젝트를 대화로 이어 고치기, 진행 로그 · 터미널 실시간 표시, git 커밋 · PR 연동

## 5. 끝났다고 볼 기준

- 외부 라이브러리가 필요한 새 프로젝트(Python 하나, Node 하나)가 사람 승인 없이 설치 · 테스트 통과 · 실행해 보기까지 감
- 켜 둔 항목(예: `brew install`)에서는 멈추고 묻고, 끄면 묻지 않음
- 동의하지 않으면 설치 · 첫 실행이 진행되지 않음
- 세 운영체제 CI 통과
