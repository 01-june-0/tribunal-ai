# 개발

테스트를 돌리는 법, 실제 작업으로 시험하는 법, 화면이 서버에 묻는 주소, 그리고 코드를 고칠 때 지키는 규칙입니다.

## 1. 테스트

```bash
.venv/bin/python -m pytest -q -p no:cacheprovider -W ignore      # 약 4분
```

- 실제 AI CLI를 부르지 않습니다. 스텁 CLI와 임시 데이터베이스로 격리되어 있고, 로컬 설정 파일(`config.local.yaml` 등)을
  읽지 않습니다.
- 전체 테스트를 두 프로세스에서 동시에 돌리지 않습니다.
- 실제 CLI를 태우는 통합 시험은 따로 선택해야 돌아갑니다: `-m integration_cli`.

### 현재 결과

2026-11-22 기준 **743개 통과, 7개 실패**입니다. 실패 7개는 원본 때부터 이어진 것으로, macOS 환경과 맞지 않는 전제 때문이며
제품 동작과는 무관합니다. 새 변경이 이 목록을 늘리지 않는 것을 기준으로 삼습니다.

| 테스트 | 실패하는 이유 |
|---|---|
| `test_v014_qualification.py::test_a2_permission_guard_hook_blocks_escapes` | `python`이라는 이름의 실행 파일을 전제 (macOS에는 `python3`만 있음) |
| `test_v0232_e2e_blockers.py::test_e_dashboard_single_instance` | 다른 프로세스의 정보를 읽는 권한이 macOS에서 거부됨 |
| `test_v0233_codex_fixes.py::test_l_resolve_cli_permission_error_no_crash` | 이 컴퓨터에 설치된 CLI가 실제로 발견되어 기대와 달라짐 |
| `test_v0246_result_center.py::test_d_open_worktree_canonical_only` | 작업 사본 폴더 열기가 이 환경에서 거부됨 |
| `test_v300h_maker_headless.py::test_exit_zero_without_task_changes_is_failed_and_settings_restore` | 임시 폴더 경로 형태가 기대와 다름 |
| `test_v300j_chat_order_path_normalization.py::test_a_unfixed_order_would_have_escalated` | 윈도우 경로를 전제 |
| `test_v302_bootstrap.py::test_snapshot_excludes_untracked_sensitive_directories` | 스냅샷 제외 목록과 테스트 픽스처가 어긋남 |

### 화면 코드의 테스트

프런트엔드에는 빌드 단계가 없습니다. 화면 코드의 테스트는 두 가지 방식입니다.

- 소스에 특정 코드가 있는지 확인하는 테스트(회귀 방지).
- `node`로 함수 일부를 잘라 실제로 실행해 보는 테스트(`tests/test_stage_ux.py`의 `_node`). `node`가 없으면 건너뜁니다.

### 번역

화면 문구는 한국어가 원문이고 영어 사전이 `console/i18n.js`에 있습니다. 화면 코드에 새 문구를 넣으면 사전에도 넣어야 하고,
`tests/test_console_i18n.py`가 빠진 문구와 쓰이지 않는 사전 항목을 잡습니다.

## 2. 실제 작업으로 시험하기

테스트 모음은 AI를 부르지 않으므로, 실제 흐름은 연습용 프로젝트에서 작업을 돌려 확인합니다. **구독 사용량을 씁니다.**

준비: 아무 폴더에 작은 git 프로젝트를 하나 만들고(`src/`, `tests/`, 통과하는 테스트 하나), 그 경로가 `bridge.allowed_roots`
아래에 있게 합니다.

```bash
sh start-companion.sh
.venv/bin/python director.py do -p <연습용 프로젝트> --profile quick --no-apply "src/calc.py에 clamp(value, low, high)를 추가하고 테스트도 추가해"
```

- `--no-apply`로 결과물을 작업 사본에 남기고, 한눈에 탭에서 변경 내용을 본 뒤 **폐기**합니다. 폐기하지 않으면 다음 작업이 그
  결과물 위에서 시작합니다.
- 이미 원본에 적용한 결과물은 폐기할 수 없습니다. 적용된 파일을 직접 지우고 작업 사본(`git worktree remove --force`)과 실행
  브랜치를 정리합니다.
- 엔진 코드(`core/`, `agents/`)를 고쳤으면 콘솔을 다시 켜야 적용됩니다. 화면 코드(`console/`)는 새로 고침으로 충분합니다.

특정 상황을 만드는 과제의 예:

| 보고 싶은 것 | 과제 |
|---|---|
| 시작 전 승인 | 유료 서비스의 자격증명을 다루고 "시작 전에 사람 승인이 필요하다"고 명시한 과제 |
| 제작 후 승인 | *기존 파일*에 `order_send`라는 이름의 함수를 추가하는 과제 (돈 관련 코드 검사에 걸림) |
| 자동 수정 여러 회차 | 통과할 수 없는 테스트를 글자 그대로 넣게 하는 과제 (예: `assert add(0.1, 0.2) == 0.3`) |
| 실시간 테스트 출력 | 테스트 하나가 몇 초씩 걸리게 하는 과제 |

같은 과제라도 ARCHITECT의 판단은 실행마다 달라질 수 있습니다.

## 3. 화면이 쓰는 주소

콘솔 서버는 `127.0.0.1`에만 열리고, 모든 요청에 로컬 출처 검사를 합니다. 아래는 화면이 실제로 쓰는 것들입니다.

### 읽기

| 주소 | 내용 |
|---|---|
| `/ops/activity` | 작업과 단계, 지금 일하는 AI, 역할별 작업량, 통합 기록 목록 |
| `/ops/record?key=call-N \| tr-N \| au-N` | 기록 한 줄의 상세 (AI 호출 / Tribunal의 상태 전환 / 내 결정). 실행 중인 테스트는 출력 끝부분 포함 |
| `/ops/call?id=N` | 진행 중인 호출 안에서 한 일 (짧게 자른 형태) |
| `/status` | 현재 실행, 승인 요청, 결과물, 처리할 항목 |
| `/chat/messages?after_id=N` | 그 뒤의 대화 |
| `/run/inspect?run_id=…` | 실행의 지시서 |
| `/run/approval?run_id=…` | 실행의 승인 상태 |
| `/result?run_id=…` | 결과물의 바뀐 파일과 변경 내용, 테스트 근거 |
| `/ops/roles`, `/ops/ai` | 역할 배정, 모델 · 한도 · 계정 |
| `/ops/digest` | 요약 |
| `/classic` | 자세히 탭 화면 |
| `/ops/hello` | 이 설치의 콘솔인지 확인하는 응답 |

### 상태를 바꾸는 요청

브리지 토큰과 중복 방지용 요청 번호가 필요합니다.

| 주소 | 하는 일 |
|---|---|
| `/chat`, `/chat/new` | ARCHITECT에게 지시, 새 대화 |
| `/project` | 프로젝트 선택 |
| `/run/approve`, `/run/reject` | 멈춘 실행의 승인 · 거절 |
| `/ops/mission/decide` | 작업의 결과물 적용 · 폐기, 이어서 시도, 다시 계획 |
| `/result/apply`, `/result/discard` | 작업 기록 없이 끝난 결과물의 적용 · 폐기 |
| `/result/open_worktree`, `/result/open_project` | 폴더 열기 |
| `/ops/roles`, `/ops/ai`, `/ops/ai/refresh`, `/ops/ai/account` | 역할 배정, 모델 설정, 한도 다시 조회, 로그인 · 계정 변경 · 로그아웃 창 열기 |
| `/providers/refresh` | AI 상태 다시 확인 (모델을 부르지 않음) |
| `/ops/missions/stop`, `/ops/shutdown` | 작업 정지, 콘솔 끄기 |
| `/ops/pick-folder` | 폴더 선택 창 |
| `/bridge/missions`, `/bridge/orders` | `director do`와 다른 로컬 프로그램이 목표를 넘기는 입구 |

## 4. 고칠 때 지키는 것

- **화면에 거짓을 쓰지 않는다.** 기록에 없는 값은 "기록 없음", 추정은 `~`. 파일의 내용을 어느 호출 · 회차의 것이라고 말하려면
  그 시간 범위 안에 쓰인 것이어야 한다.
- **글자는 글자로 넣는다.** 모델의 말, 파일 이름, 명령, 테스트 출력은 `textContent`로만 화면에 넣는다. `innerHTML`을 쓰지 않는다.
- **지켜봐도 결과가 같아야 한다.** 화면을 위한 관찰 코드는 실행 결과 · 시간 제한 · 실패 처리를 바꾸지 않는다. 관찰 코드의 오류는
  삼키고 실행은 계속한다.
- **안전 장치는 의심스러우면 멈추는 쪽으로.** 범위 검사와 돈 관련 코드 검사를 느슨하게 만드는 변경은 통과시킬 조건을 좁게 잡고,
  우회 경우를 테스트로 남긴다.
- **계정 정보를 읽지 않는다.** 로그인 토큰과 비밀번호 파일을 열지 않는다. 계정과 한도는 각 CLI의 명령으로만 묻는다.
- **추적하는 파일에 개인 경로나 계정을 넣지 않는다.** 컴퓨터마다 다른 값은 로컬 설정 파일에 둔다.
- **화면 크기 단위.** `console/stage.css`는 글자 6단계(12 / 13 / 15 / 18 / 26 / 44px)와 간격 4 · 6 · 8 · 12 · 16 · 20 · 24,
  모서리 4 · 8 · 12 · 16 · 20만 쓴다.
- **이름.** 화면에 보이는 이름은 한눈에 / 자세히 / 전체 화면, 작업 / 단계 / 회차. 코드 안의 id와 파일 이름(`stage.js`,
  `#workshop`, `body.broadcast`, `mission`)은 예전 그대로다.
