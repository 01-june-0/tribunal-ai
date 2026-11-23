# 설정

설정은 세 곳에 나뉘어 있습니다.

| 층 | 파일 | git | 용도 |
|---|---|---|---|
| 기본 | `config.yaml`, `companion.json` | 올림 | 모든 컴퓨터에 공통인 값 |
| 이 컴퓨터 전용 | `config.local.yaml`, `companion.local.json` | 올리지 않음 | 모델, 포트처럼 컴퓨터마다 다른 값 |
| 콘솔에서 고른 값 | `data/role_settings.json`, `data/cli_settings.json` | 올리지 않음 | 역할 배정, 모델 · 추론 강도 · 한도 경고 |

`config.local.yaml`은 `config.yaml`을 통째로 덮어쓰는 파일이 아닙니다. CLI의 모델과 호출 옵션(`cli_models`, `cli_options`)만 읽습니다.
그 밖의 항목(시간 제한, 안전 상한, 자율 설정 등)은 `config.yaml`에서만 정합니다. 역할 배정과 모델 · 추론 강도는 콘솔에서 고른 값이
있으면 그것이 먼저 적용됩니다.
`data/`, `runs/`, 로컬 설정 파일은 모두 `.gitignore`에 들어 있습니다.

## 1. config.yaml

### 역할

```yaml
architect: {provider: claude}                    # 설계 · 판단
maker:     {provider: codex, mode: proposal}     # 제작 — 파일 전체를 JSON으로 제안
inspector: {provider: antigravity}               # 감리
```

`provider`는 `claude` / `codex` / `antigravity` 중 하나입니다. 실행 파일은 자동으로 찾습니다(`executable: null`). 그 CLI가 없는
컴퓨터에서는 다른 것으로 바꾸면 되고, CLI 두 개로도 돌아갑니다. 콘솔의 역할 메뉴에서 바꾸면 그 선택이 다음 호출부터 적용됩니다.

AI 하나를 쓸 수 없게 되면(한도 소진, 로그인 풀림 등) 그 AI가 맡던 역할을 살아 있는 AI로 옮깁니다. 감리는 가능하면 제작과 다른
AI에 둡니다. 옮긴 사실은 감사 기록에 남습니다. 대리 판단(`autonomy.architect_proxy`)을 끈 상태에서 콘솔의 역할 메뉴로 직접 배정했다면
바꾸지 않고, 그 CLI를 쓸 수 없으면 멈춰서 알립니다.

### 시간 제한

```yaml
timeouts: {architect: 300, maker: 600, inspector: 300, no_progress: 180, heartbeat: 30}   # 초
```

`no_progress`는 출력이 없는 채로 기다리는 최대 시간입니다. Claude의 설계 · 감리 호출은 답을 한 번에 내놓는 방식이라 이 감시를
적용하지 않고, 전체 시간 제한만 적용합니다.

### 안전 상한

```yaml
safety:
  max_files_changed: 15
  max_diff_lines: 1500
  approved_commands: [python, pytest, npm, cargo, go, make]
```

### 검증

```yaml
verification:
  build_command: null
  test_command: "python -m pytest tests/"
  lint_command: null
  timeout_sec: 120        # 빌드 · 테스트 · 린트 각각. 느린 테스트 모음이면 올림 (10~3600)
```

프로젝트마다 다른 명령이 필요하면 프로젝트 안이 아니라 여기에 둡니다. MAKER가 검증을 약하게 바꿀 수 없게 하기 위해서입니다.

```yaml
projects:
  "/absolute/path/to/my_service":
    verification:
      build_command: ["npm", "run", "build"]
      test_command: "python -m pytest -q"
```

### 프로젝트 자동 준비

```yaml
bootstrap: {enabled: true}
```

폴더가 없으면 만들고, git이 없으면 초기화하고, 현재 작업 상태를 비공개 스냅샷으로 떠서 작업 사본을 만듭니다. 사용자의 HEAD와
인덱스는 바꾸지 않고, 의존성을 설치하지 않습니다.

스냅샷에는 git이 추적하는 파일과 함께 **아직 추적하지 않는 파일도 들어갑니다**(소스 · 설정 · 데이터 형식이고 2MB 이하인 것).
빠지는 것은 가상환경 · 의존성 · 도구 폴더(`.venv`, `node_modules`, `.claude` 등)와, 경로에 `secret`, `credential`, `token`, `.env`,
`private_key`가 들어간 파일입니다. 이름으로만 거르므로, 다른 이름의 민감한 파일을 추적하지 않은 채 프로젝트에 두었다면 작업 사본에
복사되어 AI가 읽을 수 있습니다. 막는 방법은 두 가지입니다.

- `.gitignore`에 넣기 — 무시되는 파일은 스냅샷에 들어가지 않습니다.
- 제외 목록에 적기 — 프로젝트 안이 아니라 이 설정 파일에 두므로 MAKER가 풀 수 없습니다.

```yaml
bootstrap:
  enabled: true
  snapshot_exclude: ["*.csv"]                 # 모든 프로젝트에 적용
projects:
  "/absolute/path/to/my_service":
    snapshot_exclude: ["data/private/**"]     # 이 프로젝트에만
```

패턴은 `.gitignore`와 같은 뜻으로 읽습니다.

- 슬래시가 없으면(`*.csv`, `private`) 어느 깊이에서든 그 이름의 파일, 또는 그 이름의 폴더와 그 아래 전부.
- 슬래시가 있으면(`data/private/**`, `exports/*.csv`, `**/tmp/**`) 프로젝트 맨 위부터 비교. `*`는 한 단계 안에서만, `**`는 여러 단계에 걸침.
- 폴더가 맞으면 그 아래 전부가 빠집니다. 대소문자는 구분하지 않습니다.
- 읽을 수 없는 패턴이나 목록이 아닌 값이 있으면 아무것도 빼지 않고 넘어가는 대신 실행을 멈춥니다.

제외 목록은 아직 추적하지 않는 파일에만 적용됩니다. 앞 단계의 작업 사본에서 이어받는 파일에도 적용하지 않습니다(앞 단계가 만든 결과물이 이름 때문에
사라지면 안 되기 때문입니다). git이 이미 추적하는 파일은 항상 들어갑니다. 어떤 파일이 들어가고 무엇이 왜
빠졌는지는 실행마다 기록되어, 콘솔의 기록에서 제작 호출이나 마침 줄을 누르면 보입니다.

### 자율

```yaml
autonomy:
  enabled: true
  architect_proxy: true        # ARCHITECT가 사용자를 대신해 결정. 돈 · 자격증명 · 비가역 행동만 사람에게
  max_repairs: 3               # 한 단계의 자동 수정 횟수
  fast_repair: true            # 테스트가 실패하면 감리 · 판단을 건너뛰고 바로 수정
  maker_attempts: 3            # 제작 재시도. 마지막 시도는 다른 AI로
  inspector_tests: true        # 감리 AI가 테스트를 제안하고 Tribunal이 실행
  max_steps: 6                 # 한 작업의 단계 수
  max_consecutive_failures: 3
  resume_on_start: true        # 콘솔을 다시 켜면 진행 중이던 작업을 이어 함 (정지한 작업은 그대로)
  auto_apply: on_pass          # off | on_done | on_pass
```

`auto_apply`는 통과한 결과물을 원본에 자동으로 적용할지를 정합니다. `off`는 항상 내가 적용, `on_done`은 ARCHITECT가 목표 달성을
선언했을 때만, `on_pass`는 통과한 결과물이면 언제나입니다. 어느 경우든 그 사이 사람이 고친 파일은 덮어쓰지 않고, 파일을 지우지
않습니다. 명령줄의 `--no-apply`는 이 설정과 상관없이 결과물을 작업 사본에 남겨 둡니다.

### 프로필

요청 크기에 따른 예산입니다. 안전 장치와 범위 검사는 어느 프로필에서나 같습니다.

| 프로필 | 단계 | 자동 수정 | 제작 재시도 | 감리 테스트 |
|---|---|---|---|---|
| `quick` | 2 | 1 | 2 | 끔 |
| `standard` | 6 | 3 | 3 | 켬 |
| `deep` | 12 | 3 | 3 | 켬 |

### 브리지

```yaml
bridge:
  allowed_roots: ["~/Developer"]        # 이 아래의 git 프로젝트만 대상으로 받음
  denied: ["~/Developer/tribunal-ai"]   # Tribunal 자신의 폴더는 대상이 될 수 없음
```

`director do`와 다른 로컬 프로그램이 목표를 넘기는 입구입니다. 요청에는 브리지 토큰이 필요합니다(3절).

## 2. 이 컴퓨터 전용 설정

### config.local.yaml

```yaml
cli_models:
  codex: <모델 이름>            # `codex exec -m …` 로 전달. 없으면 CLI의 기본 모델

cli_options:
  claude_light: true            # 기본 켬: MCP 서버 · 스킬 없이 읽기 도구만 (호출당 입력 약 51,000 → 8,000 토큰)
  claude_model: sonnet          # 선택: `claude --model`
  claude_effort: medium         # 선택: low | medium | high | xhigh | max
  codex_light: true             # 기본 켬: 플러그인 · 메모리 · 훅 · 연결 앱 없이 (감리 1회 약 52,000 → 7,000 토큰)
  codex_reasoning_effort: high  # 선택: minimal | low | medium | high | xhigh
```

이 파일이 있는 이유: 그러지 않으면 Codex는 `~/.codex/config.toml`이 가리키는 모델로 돌고, 로그인한 요금제가 그 모델을 제공하지
않으면 모든 Codex 호출이 몇 초 만에 실패합니다. 여기서 정하면 평소 쓰는 Codex 설정은 건드리지 않습니다.

콘솔의 **AI 설정**에서 고른 모델과 추론 강도가 있으면 이 파일보다 먼저 적용됩니다.

### companion.local.json

```json
{"port": 8200}
```

콘솔 포트입니다. 정하지 않으면 기본 8081을 쓰고, 그 포트가 다른 프로그램에 잡혀 있으면 다음 빈 포트를 자동으로 씁니다.
여기서(또는 환경 변수 `TRIBUNAL_PORT`로) 직접 정한 포트는 몰래 바꾸지 않습니다. 잡혀 있으면 서버가 멈추고 그렇게 말합니다.
실제로 떠 있는 주소는 `data/companion.port`에 기록되어, 실행 스크립트와 `director do`가 그것을 보고 콘솔을 찾습니다.

`companion.json`의 `allowed_projects`는 외부 주문 입구(`/bridge/orders`)가 받는 프로젝트 목록입니다. 목록에 있는 프로젝트만 받습니다.

## 3. 콘솔 서버의 보호 장치

- 항상 `127.0.0.1`에만 열립니다.
- 모든 요청에 로컬 출처 검사를 합니다: 요청의 Host가 `localhost` 계열의 이 포트여야 하고, Origin이 있으면 그것도 같아야 합니다.
- `/ops/*`와 `/bridge/*`의 상태를 바꾸는 요청(역할 · 모델 설정, 계정, 작업 정지, 콘솔 끄기, 폴더 선택, 목표 넘기기)은 여기에 더해
  브리지 토큰(`data/bridge.token`, 처음 실행할 때 생성)을 요구합니다.
- 채팅, 프로젝트 선택, 승인 · 거절, 결과물 적용 · 폐기는 로컬 출처 검사와 중복 방지용 요청 번호로 보호합니다. 토큰은 요구하지 않습니다.
- 다른 프로그램이 같은 포트에서 듣고 있을 수 있으므로, 토큰을 보내기 전에 상대가 이 설치의 콘솔인지 확인합니다. 확인되지 않은
  상대와 프록시로는 토큰을 보내지 않습니다.
- 호출 안에서 한 일, 기록 상세처럼 명령과 경로가 담기는 읽기 주소도 이 컴퓨터에서 온 요청에만 답합니다.

## 4. 환경 변수

| 변수 | 용도 |
|---|---|
| `TRIBUNAL_PORT` | 콘솔 포트를 직접 지정 |
| `TRIBUNAL_DB_PATH` | 데이터베이스와 그 옆의 기록(작업, 잠금, 호출 흔적)을 다른 곳에 둠. 절대 경로여야 함. 데모 콘솔이 씀 |
| `*_API_KEY` | 있어도 무시됨. CLI를 부르기 전에 지움 |

## 5. 명령줄

```bash
python director.py do [-p 프로젝트] [--profile quick|standard|deep] [--no-apply] "목표"
python director.py mission -p 프로젝트 -g "목표" [--max-steps N] [--profile …] [--mission-id ID [--replan "이유"]]
python director.py run -p 프로젝트 -g "목표" [--architect-provider claude|codex|mock]
python director.py status [-r 실행번호]
python director.py resume 실행번호
python director.py clean-worktrees -p 프로젝트 [--dry-run] [--purge-reviewed]
```

- `do`는 가장 짧은 길입니다. 콘솔이 떠 있으면 거기에 작업을 넘기고, 진행은 한눈에 탭에서 보입니다. `-p`를 생략하면 현재 폴더가
  git 저장소일 때 그 폴더를 씁니다.
- `mission`은 작업을 직접 돌리고, `run`은 단계 하나만 돌립니다.
- `resume`은 멈춘 실행 하나를 끝까지 돌립니다(그 실행이 속한 작업은 콘솔의 **이어서 시도**로 이어 갑니다).
- `clean-worktrees`는 더 필요 없는 작업 사본과 실행 브랜치를 정리합니다: 적용 · 폐기한 결과물, 닫힌 작업, 실패로 끝난 실행.
  결정을 기다리는 결과물과 충돌 파일을 건너뛰어 일부러 남겨 둔 작업 사본은 `--purge-reviewed`를 줘야 지웁니다. `--dry-run`으로
  먼저 목록만 볼 수 있습니다.
