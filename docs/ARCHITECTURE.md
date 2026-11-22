# 구조

Tribunal AI가 목표 한 줄을 어떻게 검증된 코드로 바꾸는지, 무엇이 그것을 지키는지, 무엇이 어디에 기록되는지를 설명합니다.

## 1. 등장인물

| 이름 | 누구 | 하는 일 |
|---|---|---|
| **ARCHITECT · 설계** | AI (기본 Claude) | 목표를 지시서로 만들고, 결과가 통과인지 판단하고, 다음 단계를 계획 |
| **MAKER · 제작** | AI (기본 Antigravity) | 지시서대로 바꿀 파일의 내용을 제안 |
| **INSPECTOR · 감리** | AI (기본 Codex) | 결과물을 읽기 전용으로 독립 검토, 필요하면 테스트를 제안 |
| **TRIBUNAL** | 이 프로그램 | 범위 검사, 작업 사본 관리, 테스트 실행, 기록. AI가 아님 |
| **나** | 사용자 | 지시, 승인 · 거절, 결과물 적용 · 폐기 |

세 AI는 각자의 공식 CLI(`claude`, `codex`, `agy`)로만 불립니다. 어느 AI가 어느 역할을 맡을지는 설정과 콘솔에서 바꿀 수 있고,
한 AI가 여러 역할을 맡을 수도 있습니다.

## 2. 한 단계의 흐름

실행(run) 하나가 단계 하나입니다. 상태는 아래 순서로만 앞으로 갑니다.

```
IDLE → PLANNING → ORDER_READY → BUILDING → VERIFYING → REVIEWING → DECIDING → PASS
 대기     설계        제작 준비      제작        테스트       감리        판단       통과
                                     ▲                                    │
                                     └────────── 수정 지시 ───────────────┘
어느 지점에서든:  FAIL (실패) · TIMEOUT (시간 초과) · HUMAN_REQUIRED (사용자 확인)
```

1. **설계** — ARCHITECT가 지시서(ORDER)를 씁니다. 목표, 바꿀 수 있는 경로, 건드리면 안 되는 경로, 파일 수와 변경 줄 수 상한,
   완료 기준이 들어갑니다.
2. **시작 전 검사** — 지시서가 돈 · 자격증명처럼 사람이 정해야 하는 일을 건드리면 여기서 멈춰 승인을 기다립니다.
3. **시작 전 기준 테스트** — 손대기 전에 테스트를 한 번 돌려 기준을 잡습니다.
4. **제작** — MAKER가 파일 전체 내용을 JSON으로 제안하면, Tribunal이 경로를 검사한 뒤 작업 사본에 씁니다. MAKER가 직접 파일을
   쓰지 않습니다.
5. **변경 검사** — 범위 검사와 "돈을 움직일 수 있는 코드" 검사를 테스트 실행 *전에* 합니다 (4절).
6. **테스트** — Tribunal이 설정된 명령을 작업 사본에서 직접 실행합니다.
7. **감리** — INSPECTOR가 변경 내용과 테스트 증거를 보고 판정합니다. 지적은 P0 / P1 / P2로 나뉩니다.
8. **판단** — ARCHITECT가 통과 또는 수정 지시를 냅니다. 수정 지시면 제작으로 돌아갑니다(한 회차).
9. **마침 검사** — 통과 판단이 나와도 Tribunal이 증거를 다시 확인합니다. 테스트가 실패했거나 감리가 통과가 아니면 통과를 거부합니다.

### 자동 수정과 빠른 수정

수정 회차는 `autonomy.max_repairs`까지 돕니다. **빠른 수정**(`autonomy.fast_repair`, 대리 판단 모드에서만)이 켜져 있으면, 테스트가
실패한 회차는 감리와 판단을 건너뛰고 곧바로 MAKER에게 돌아갑니다. 실패가 분명한데 AI 두 번을 더 부르지 않기 위해서입니다.
이렇게 건너뛴 회차는 수정 횟수 한도에 넣지 않습니다.

### 감리 AI의 독립 테스트

MAKER는 자기 코드의 테스트도 자기가 씁니다. 약한 테스트로 약한 코드가 통과하는 것을 막기 위해, INSPECTOR가 테스트 파일을
제안할 수 있고(`autonomy.inspector_tests`) Tribunal이 그것을 버리는 사본에서 실행합니다. 실패하면 P1 지적이 됩니다. 이 테스트는
증거일 뿐 결과물에 들어가지 않습니다 (`core/inspector_tests.py`).

## 3. 작업

채팅 한 줄(또는 `director do`)이 **작업**(mission)이 됩니다. ARCHITECT가 단계를 하나씩 계획하고, 각 단계는 직전에 통과한 작업
사본에서 시작하며, 실제 증거를 보고 다음 단계를 다시 계획합니다 (`core/mission.py`).

- 단계 수 상한과 수정 횟수는 프로필(`quick` / `standard` / `deep`)로 정합니다.
- 작업 상태: 진행 중, 완료, 단계 한도 도달, 확인 필요(막힘), 실패, 정지.
- 콘솔을 다시 켜면 진행 중이던 작업은 이어서 하고, 정지한 작업은 그대로 둡니다.

## 4. 안전 장치

| 장치 | 내용 | 위치 |
|---|---|---|
| 종량제 금지 | CLI를 부르기 전에 모든 `*_API_KEY`를 환경에서 제거 | `core/env_utils.py` |
| 작업 사본 격리 | 원본 프로젝트의 현재 상태를 비공개 스냅샷으로 떠서 git worktree를 만듦. 원본의 HEAD와 인덱스는 건드리지 않음 | `core/bootstrap.py`, `core/git_manager.py` |
| 범위 검사 | 허용 경로 밖, 보호 경로, 경로 탈출, 파일 수 · 줄 수 상한, 무단 삭제 | `core/safety.py` |
| 대리 판단의 한계 | 돈, 실계좌 주문, 실제 자격증명, 되돌릴 수 없는 외부 행동, 보안 위반은 사람에게 | `core/autopilot.py` |
| 돈 관련 코드 검사 | 주문 제출 · 결제 SDK · 결제 호출이 추가되면 테스트가 그 코드를 실행하기 *전에* 멈춤 | `core/autopilot.py` |
| 감리 실패 시 닫힘 | 감리 응답이 없거나 깨지면 실패로 처리 | `core/orchestrator.py` |
| 프로세스 트리 종료 | 시간 초과나 정지 때 CLI와 그 자식까지 종료 | `core/process_runner.py` |
| 검증 명령은 프로젝트 밖에 | 프로젝트별 검증 명령을 `config.yaml`에 두어 MAKER가 약화시킬 수 없음 | `config.yaml` |
| 적용은 덮어쓰지 않음 | 그 사이 사람이 고친 파일은 충돌로 보고하고, 건너뛰고 나머지만 적용할지 묻음. 삭제는 하지 않음 | `core/result_manager.py` |

### 돈 관련 코드 검사가 통과시키는 경우

`order_send` 같은 이름만으로 멈추면 무관한 코드도 걸립니다. 그래서 다음 조건을 **모두** 만족하면 그 이름을 이번 변경이 직접 만든
함수로 보고 통과시킵니다. 하나라도 어긋나면 예전처럼 멈춥니다.

- 완전히 새로 만든 파이썬 파일이고 문법 분석이 된다.
- 동적으로 이름을 바꾸는 장치(`globals`, `setattr`, `exec` 등)와 `import *`가 없다.
- 그 이름을 객체나 모듈을 거쳐 부르지 않는다 (`mt5.order_send(...)`는 항상 멈춤).
- 파일 안에서 그 이름이 가리키는 것이 꾸밈 없는 최상위 함수 정의 하나뿐이거나, 그런 정의를 가진 이번 변경의 다른 새 파일에서
  `from … import`로 가져온 것 하나뿐이다.

기존 파일을 수정한 경우는 항상 이름만으로 멈춥니다. 검사가 추가된 줄만 보기 때문에, 보이지 않는 기존 줄이 그 이름을 실제 주문
함수에 연결했을 수 있어서입니다.

## 5. 결과물

통과한 단계는 **결과물**을 남깁니다. 결과물은 작업 사본에 있고, 원본에는 아직 아무 변화가 없습니다.

| 상태 | 뜻 |
|---|---|
| 적용 대기 | 변경 내용을 보고 적용하거나 폐기할 수 있음 |
| 적용됨 | 원본 프로젝트에 반영됨. 적용 뒤 테스트를 다시 돌려 확인 |
| 적용 보류 | 충돌 등으로 적용하지 못함. 충돌 파일만 건너뛰고 다시 시도할 수 있음 |
| 폐기됨 | 작업 사본을 지움. 실행 기록은 남음 |

`autonomy.auto_apply`로 통과한 결과물을 자동으로 적용하게 할 수도 있습니다 ([CONFIGURATION.md](CONFIGURATION.md)).

## 6. 기록

모든 것은 이 컴퓨터 안에만 남습니다.

| 어디 | 무엇 |
|---|---|
| `data/director.db` | 실행과 상태 전환, 감사 기록(누가 무엇을 결정했나), AI 호출 장부, 대화 |
| `data/missions/` | 작업별 단계와 결과 |
| `runs/<실행 번호>/` | 그 실행의 지시서, 제작 결과, 테스트 결과, 감리, 판단, 수정 회차 기록, 마침 검사, 결과물 요약 |
| `runs/<실행 번호>/verification_live.log` | 테스트가 도는 동안의 출력 (화면용) |
| 각 CLI의 세션 기록 | 호출 안에서 쓴 도구와 한 말. Tribunal은 읽기만 함 |

**AI 호출 장부**(`core/usage.py`)는 모든 CLI 호출의 역할, 단계, 시작과 끝, 걸린 시간, 토큰, 종료 코드, 명령줄이 요청한 모델과
추론 강도를 한곳에서 기록합니다. 토큰은 CLI가 알려 주면 그 값을, 아니면 글자 수로 추정한 값을 쓰고 둘을 구분해 둡니다.

**통합 기록**(`core/work_log.py`)은 위 기록들을 시간순 한 줄기로 합쳐 콘솔에 줍니다. 값을 호출이나 회차에 연결하는 규칙은
엄격합니다.

- 실행 폴더의 파일은 그 호출 · 회차의 시간 범위 안에 쓰였을 때만 그 호출 · 회차의 것으로 봅니다.
- 앞 회차의 테스트 · 감리 · 판단은 그 회차가 불러온 수정 기록에서 읽습니다.
- Tribunal이 ARCHITECT의 판단을 바꿔 저장했으면 "Tribunal이 바꾼 최종 판단"으로 구분합니다.
- 연결할 수 없는 값은 비워 두고, 화면은 "기록 없음"이라고 씁니다. 추정해서 채우지 않습니다.

## 7. 지켜봐도 결과는 같다

테스트 출력을 화면에 실시간으로 보내는 경로는 실행 결과에 영향을 주지 않게 만들었습니다.

- 출력을 읽는 쪽은 받은 조각을 대기열에 넣기만 하고, 파일에 쓰는 일은 별도 스레드가 합니다. 대기열이 차면 화면용 줄만 빠집니다.
- 판정에 쓰는 결과 텍스트는 지켜볼 때와 아닐 때 똑같이 줄 단위로 모읍니다.
- 모든 검증은 같은 환경(`PYTHONUNBUFFERED=1` 포함)에서 돕니다.

## 8. 파일 구조

```
director.py            명령줄 진입점 (run / mission / do / status / resume / clean-worktrees)
companion_server.py    콘솔 서버: 정적 파일, /ops/* 와 /bridge/* 주소
dashboard_server.py    자세히 탭 화면, 채팅, 상태, 승인 · 결과 처리
dashboard_i18n.py      자세히 탭의 문구

agents/                역할 어댑터
  claude_architect.py  codex_architect.py  google_roles.py      설계 · 판단
  proposal_maker.py    antigravity_maker.py                     제작
  claude_inspector.py  codex_inspector.py                       감리

core/
  orchestrator.py      한 단계의 흐름
  mission.py           작업(여러 단계)
  autopilot.py         대리 판단의 한계, 돈 관련 코드 검사
  safety.py            범위 검사
  verifier.py          빌드 · 테스트 · 린트 실행
  inspector_tests.py   감리 AI의 독립 테스트
  result_manager.py    결과물 보기 · 적용 · 폐기
  bootstrap.py  project_inventory.py  git_manager.py            프로젝트 준비와 작업 사본
  process_runner.py    모든 외부 명령 실행 (시간 제한, 프로세스 트리 종료)
  cli_runner.py        읽기 전용 CLI 호출 (제작 제안, Google 역할)
  provider_manager.py  AI 상태와 장애 시 교체
  state_machine.py     실행 상태, 감사 기록
  usage.py             AI 호출 장부
  call_activity.py     호출 안에서 한 일 (CLI 세션 기록 읽기)
  work_log.py          통합 기록
  cli_models.py  cli_settings.py  cli_limits.py  cli_accounts.py   모델 · 한도 · 계정
  role_settings.py  role_names.py                                역할 배정과 옛 이름 호환
  order_bridge.py  companion_config.py  chat_manager.py  db_path.py  env_utils.py  file_lock.py

schemas/               지시서 · 제작 결과 · 감리 결과 · 판단 · 출처 기록 (pydantic)
console/               한눈에 · 자세히 두 탭의 프런트엔드 (의존성 없는 정적 파일)
scripts/               데모 콘솔, 폴더 선택, CLI 진단, 전송 실패 재시도
tests/                 스텁 CLI로 격리된 테스트
```

## 9. 옛 이름

세 역할은 원래 HEAD / BUILDER / REVIEWER였습니다. 옛 이름으로 저장된 데이터베이스 값, 설정 키, 실행 기록은
`core/role_names.py` 한 곳에서 새 이름으로 바꿔 읽습니다. 파일을 고치지는 않습니다. 명령줄의 `--head-provider`도
`--architect-provider`의 다른 이름으로 계속 쓸 수 있습니다. git의 `HEAD`(현재 커밋)는 역할 이름과 무관합니다.
