# 역할 이름 (2026-11-21 변경)

세 역할의 이름이 바뀌었습니다. 화면에 보이는 이름과 코드·설정·기록에 쓰는 식별자가 모두 새 이름입니다.

| 이전 | 지금 | 하는 일 |
|---|---|---|
| HEAD · 지휘 | ARCHITECT · 설계 | 요청을 작업 지시서로 만들고 통과 여부를 판단 |
| BUILDER · 구현 | MAKER · 제작 | 지시서대로 코드를 작성 |
| REVIEWER · 검수 | INSPECTOR · 감리 | 결과물을 독립적으로 살핌 |

흐름 표시줄의 단계 이름도 `설계 → 제작 → 테스트 → 감리 → 판단`으로 바뀌었습니다. 내부 상태 값(`PLANNING`, `BUILDING`,
`VERIFYING`, `REVIEWING`, `DECIDING`)은 그대로입니다.

## 이전 이름으로 저장된 것

`core/role_names.py` 한 곳에서만 이전 이름을 압니다.

- 데이터베이스: 콘솔이 시작할 때 역할 값과 열 이름(`head_provider`, `reviewer_state`)을 새 이름으로 옮깁니다.
- `data/role_settings.json`, `config.yaml` / `config.local.yaml`: 이전 키(`head`, `builder`, `reviewer`, `head_proxy`,
  `builder_attempts` …)도 그대로 읽습니다.
- 이전 실행 기록(`runs/<id>/builder.json` 등)과 미션 기록: 읽을 때 새 이름으로 바꿔 읽습니다. 파일은 고치지 않습니다.
- 명령줄: `--head-provider`는 `--architect-provider`의 다른 이름으로 계속 쓸 수 있습니다.
- 대화 기록의 본문과 실행 기록의 문장은 고치지 않습니다(예전 알림 문구도 그대로 인식합니다).

`git`의 `HEAD`(현재 커밋)는 역할 이름과 무관하므로 바뀌지 않았습니다.

이 날짜 이전의 `docs/` 문서는 당시 이름(HEAD / BUILDER / REVIEWER)으로 쓰여 있습니다.
