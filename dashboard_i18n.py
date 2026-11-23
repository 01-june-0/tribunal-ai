"""
Dashboard presentation language layer (ko-KR first). Internal enums, audit keys, DB values and API fields stay
English; only what the user sees is translated here. Everything is a plain mapping so another language can be
plugged in later by replacing the dictionaries.
"""
import re
from typing import Dict, Tuple, List, Optional

LANG = "ko-KR"

UI_TEXT: Dict[str, str] = {
    "app_subtitle": "AI 개발 오케스트레이션 시스템",
    "system_mode": "시스템 상태",
    "project": "프로젝트",
    "last_run": "최근 작업",
    "current_run": "현재 작업",
    "architect_chat": "ARCHITECT 대화",
    "recovery": "복구 상태",
    "results": "결과물",
    "pending_actions": "승인 대기",
    "details": "상세보기",
    "inspect": "확인하기",
    "new_chat": "새 대화",
    "view_changes": "변경사항 보기",
    "test_results": "테스트 결과",
    "open_worktree": "작업 결과 폴더 열기",
    "open_project": "프로젝트 폴더 열기",
    "apply_verify": "프로젝트에 적용하고 검증",
    "discard": "결과 폐기",
    "approve_resume": "승인하고 계속",
    "reject": "거절",
    "cancel": "취소",
    "close": "닫기",
    "change": "변경",
    "select_project": "프로젝트 선택",
    "no_project": "대화용 폴더 미선택",
    "chat_ready": "입력 가능",
    "director_core": "TRIBUNAL AI CORE",
    "core_sub": "3개의 AI 코어를 지휘합니다",
    "my_todo": "내가 할 일",
    "nothing_todo": "없음",
    "architect_ready": "ARCHITECT에게 작업을 요청하세요.",
    "director_ready": "TRIBUNAL AI 준비됨",
    "safe": "안전",
    "human_required": "사용자 확인 필요",
    "human_required_sub": "이 작업을 계속하려면 다음 내용을 확인해주세요.",
    "human_approval_required": "사용자 승인이 필요합니다.",
    "not_approvable": "승인할 수 없는 안전 문제",
    "not_approvable_sub": "이 문제는 승인으로 우회할 수 없습니다.",
    "reason": "이유",
    "file": "파일",
    "why": "설명",
    "stage": "단계",
    "maker": "Maker",
    "technical_reason": "Technical reason",
    "safe_no_action": "안전 · 처리할 항목 없음",
    "result_ready": "결과물이 준비되었습니다.",
    "result_applied": "프로젝트에 적용되었습니다 ✓",
    "result_discarded": "결과가 폐기되었습니다.",
    "apply_blocked": "현재 결과를 적용할 수 없습니다.",
    "apply_rolled_back": "적용에 실패해 적용 전 상태로 복구했습니다.",
    "changed_files": "변경 파일",
    "tests": "테스트",
    "review": "감리",
    "safety": "안전 검사",
    "pass": "통과",
    "fail": "실패",
    "apply_confirm_title": "프로젝트에 결과를 적용할까요?",
    "apply_confirm_body": "적용 후 테스트를 다시 실행합니다.\n커밋이나 Push는 자동으로 하지 않습니다.\n문제가 발생하면 적용 전 상태로 자동 복구합니다.",
    "apply_confirm_ok": "적용하고 검증",
    "discard_confirm_title": "이 결과를 폐기할까요?",
    "discard_confirm_body": "- 원본 프로젝트는 변경되지 않습니다.\n- 작업 기록과 검증 증거는 보존됩니다.\n- 작업 결과 폴더는 삭제될 수 있습니다.",
    "discard_confirm_ok": "폐기",
    "architect_working": "ARCHITECT가 작업 중입니다…",
    "architect_busy_other": "ARCHITECT가 다른 요청을 처리 중입니다…",
    "send": "보내기",
    "input_placeholder": "Enter = 전송, Shift+Enter = 줄바꿈",
    "run_id": "작업 ID",
    "elapsed": "진행 시간",
    "started": "시작 시각",
    "next_step": "다음 단계",
    "state": "상태",
    "role": "역할",
    "latency": "최근 응답 시간",
    "version": "CLI 버전",
    "last_error": "최근 오류",
    "quota": "사용량",
    "worktree": "작업 결과 폴더",
    "result_state": "결과",
    "view_result": "결과 확인",
    "run_pass_ready": "작업이 완료되었습니다 · 결과물이 준비되었습니다",
}

STATUS_TEXT: Dict[str, str] = {           # provider / mode statuses
    "HEALTHY": "정상", "RECOVERING": "복구 중", "DEGRADED": "일부 기능 제한", "STOP": "실행 중지", "NORMAL": "정상",
    "QUOTA_EXHAUSTED": "사용량 초과", "QUOTA_LOW": "사용량 부족", "AUTH_FAILED": "인증 실패", "TIMEOUT": "응답 없음",
    "UNAVAILABLE": "사용 불가", "CONFIG_ERROR": "설정 오류", "UNKNOWN": "확인 안 됨",
}

STATE_TEXT: Dict[str, str] = {            # run states
    "IDLE": "대기 중", "PLANNING": "설계 중", "ORDER_READY": "제작 준비 완료", "BUILDING": "제작 중",
    "VERIFYING": "테스트·검증 중", "REVIEWING": "감리 중", "DECIDING": "최종 판단 중", "PASS": "완료",
    "FAIL": "실패", "FAILED": "실패", "RECOVERED": "복구 완료", "TIMEOUT": "시간 초과", "HUMAN_REQUIRED": "사용자 확인 필요", "NONE": "작업 없음",
    "REJECTED": "거절한 작업",              # display only: a HUMAN_REQUIRED run the user rejected (dashboard_server.build_status_payload)
}

RESULT_TEXT: Dict[str, str] = {
    "READY": "적용 대기", "APPLIED": "적용 완료", "DISCARDED": "폐기됨", "APPLY_BLOCKED": "적용할 수 없음",
    "APPLY_FAILED_ROLLED_BACK": "적용 실패 · 복구됨", "APPLY_VERIFY_FAILED_ROLLED_BACK": "검증 실패 · 복구됨",
}

# the same words the stage uses for the three roles
ROLE_TEXT: Dict[str, str] = {"ARCHITECT": "설계", "MAKER": "제작", "INSPECTOR": "감리", "BACKUP": "예비 AI", "NONE": "역할 없음"}
# who is speaking in the chat (the role code stays in the CSS class)
SPEAKER_TEXT: Dict[str, str] = {"USER": "나", "ARCHITECT": "ARCHITECT", "SYSTEM": "시스템", "ERROR": "오류"}

STAGE_TEXT: Dict[str, str] = {"ARCHITECT": "설계", "BUILD": "제작", "VERIFY": "테스트·안전 검증", "REVIEW": "감리", "DECIDE": "최종 판단"}

PROVIDER_LABEL: Dict[str, Tuple[str, str, str]] = {   # domain -> (display name, vendor, sentence subject)
    "OPENAI": ("CODEX", "OpenAI", "Codex"), "GOOGLE": ("ANTIGRAVITY", "Google", "Antigravity"), "ANTHROPIC": ("CLAUDE", "Anthropic", "Claude"),
}

REASON_TEXT: Dict[str, Tuple[str, str]] = {   # code -> (short title, explanation)
    "SENSITIVE_FILE_IN_SCOPE": ("의존성·환경 설정 파일 변경 승인 필요", "실행 환경이나 의존성에 영향을 줄 수 있는 파일이 작업 범위에 포함되어 있습니다. 수정 전에 확인이 필요합니다."),
    "LIVE_MONEY_CODE": ("돈을 움직일 수 있는 코드", "주문이나 결제를 실행할 수 있는 코드가 추가되었습니다. 테스트가 이 코드를 실행하기 전에, 이 파일에 한해 사용자가 허용해야 합니다."),
    "DEPENDENCY_CONFIGURATION_MODIFIED": ("의존성 설정 파일 변경", "의존성 설정 파일이 실제로 변경되었습니다. 이 파일에 한해 승인하면 검증이 계속됩니다."),
    "AMBIGUOUS_SCOPE": ("작업 범위가 불명확함", "허용 경로가 비어 있거나 프로젝트 전체입니다. 범위를 확인하고 승인해주세요."),
    "HIGH_RISK": ("고위험 작업", "ARCHITECT가 이 작업을 고위험으로 판단했습니다. 사람이 승인해야 실행됩니다."),
    "EXPLICIT_HUMAN_APPROVAL_REQUESTED": ("ARCHITECT가 승인을 요청함", "ARCHITECT가 실행 전에 사용자 승인을 명시적으로 요청했습니다."),
    "DESTRUCTIVE_CHANGE": ("삭제가 포함된 작업", "파일 삭제가 포함된 작업은 승인으로 우회할 수 없습니다."),
    "PROTECTED_PATH_IN_SCOPE": ("보호 경로가 작업 범위에 포함됨", "보호된 경로는 AI가 수정할 수 없으며 승인으로 우회할 수 없습니다."),
    "PROTECTED_PATH_INSIDE_ALLOWED": ("허용 범위 안에 보호 경로 존재", "허용 경로 아래에 보호 경로가 있습니다. 승인으로 우회할 수 없습니다."),
    "GIT_INTERNALS_IN_SCOPE": ("Git 내부 관리 파일이 작업 범위에 포함되었습니다.", "Git 내부 관리 영역(.git)은 프로젝트의 Git 상태를 관리하는 보호 영역이므로 AI가 수정할 수 없습니다."),
    "CONTROL_PLANE_IN_SCOPE": ("TRIBUNAL AI 보호 파일 포함", "TRIBUNAL AI의 보호 설정 파일은 AI가 수정할 수 없습니다."),
    "CONTROL_PLANE_MODIFIED": ("보호 설정 파일 변경 감지", "TRIBUNAL AI의 보호 설정 파일 변경이 감지되었습니다."),
    "INVALID_PATH": ("잘못된 경로", "작업 범위에 허용되지 않는 경로 형식이 포함되어 있습니다."),
    "CANONICAL_CONTAINMENT": ("작업 폴더 밖 접근 가능성", "허용된 작업 폴더 밖으로 연결될 가능성이 있어 중단했습니다."),
    "ORDER_PATH_VIOLATION": ("작업 폴더 밖 경로", "허용된 작업 폴더 밖 경로가 포함되어 중단했습니다."),
    "REGRESSION": ("기존 테스트 결과 악화", "기존 테스트보다 결과가 나빠져 중단했습니다."),
    "BASELINE_MISSING": ("기준 테스트 기록 없음", "작업 전 테스트 기준 기록이 없어 안전하게 비교할 수 없습니다."),
    "BASELINE_FAILED": ("기준 테스트 실패", "작업 전 테스트가 이미 실패 상태여서 시작하지 않았습니다."),
    "WORKTREE_EVIDENCE_MISSING": ("작업 사본 확인 불가", "안전하게 검증할 작업 사본을 확인할 수 없습니다."),
    "EVIDENCE_MISSING": ("검증 증거 없음", "검증 증거가 없어 자동으로 완료하지 않았습니다."),
    "INSPECTOR_FAIL_CLOSED": ("감리 결과 신뢰 불가", "감리 결과를 신뢰할 수 없어 자동 완료하지 않았습니다."),
    "INSPECTOR_EXCEPTION": ("감리 실패", "감리 AI 호출이 실패했습니다."),
    "FINAL_GATE": ("최종 안전 검사 불충족", "최종 안전 검사에 필요한 증거가 부족해 완료하지 않았습니다."),
    "SCOPE_VIOLATION": ("작업 범위 위반", "허용된 범위 밖의 변경이 감지되었습니다."),
    "PROVIDER_STOP": ("AI 사용 불가", "사용 가능한 AI가 부족해 자동 실행을 중지했습니다."),
    "PROJECT_SELECTION_REQUIRED": ("프로젝트 미선택", "먼저 프로젝트를 선택해야 작업을 실행할 수 있습니다."),
    "BASE_COMMIT_MISMATCH": ("원본 프로젝트가 변경됨", "작업이 시작된 뒤 원본 프로젝트가 변경되었습니다. 새 작업을 실행하거나 변경사항을 먼저 정리해주세요."),
    "WORKING_TREE_DIRTY": ("원본 프로젝트에 정리되지 않은 변경 있음", "원본 프로젝트의 변경사항을 먼저 정리해야 안전하게 적용할 수 있습니다."),
    "UNTRACKED_COLLISION": ("같은 이름의 파일이 이미 있음", "결과 파일과 같은 이름의 파일이 프로젝트에 이미 있어 덮어쓰지 않았습니다."),
    "USER_DECISION_REQUIRED": ("사용자 결정 필요", "결제, 계정 정보, 되돌릴 수 없는 외부 작업처럼 ARCHITECT가 대신 정할 수 없는 사안입니다. 내용을 확인하고 직접 정해 주세요."),
    "UNKNOWN": ("자동 판단 불가", "자동 판단할 수 없는 문제가 발생했습니다. 상세 정보를 확인하세요."),
}

REASON_RECOMMENDATION: Dict[str, str] = {   # code -> what the user should do about a NON-approvable halt
    "GIT_INTERNALS_IN_SCOPE": "ARCHITECT에게 .git 영역을 제외하고 작업 계획을 다시 만들도록 요청하세요.",
    "CONTROL_PLANE_IN_SCOPE": "ARCHITECT에게 TRIBUNAL AI 보호 파일을 제외하고 작업 계획을 다시 만들도록 요청하세요.",
    "CONTROL_PLANE_MODIFIED": "ARCHITECT에게 보호 설정 파일을 제외하고 작업 계획을 다시 만들도록 요청하세요.",
    "PROTECTED_PATH_IN_SCOPE": "ARCHITECT에게 보호된 경로를 제외하고 작업 계획을 다시 만들도록 요청하세요.",
    "PROTECTED_PATH_INSIDE_ALLOWED": "ARCHITECT에게 보호된 경로를 제외하고 작업 계획을 다시 만들도록 요청하세요.",
    "CANONICAL_CONTAINMENT": "ARCHITECT에게 작업 폴더 안 경로만 사용하도록 작업 계획을 다시 만들도록 요청하세요.",
    "ORDER_PATH_VIOLATION": "ARCHITECT에게 작업 폴더 안 경로만 사용하도록 작업 계획을 다시 만들도록 요청하세요.",
    "INVALID_PATH": "ARCHITECT에게 올바른 경로 형식으로 작업 계획을 다시 만들도록 요청하세요.",
    "DESTRUCTIVE_CHANGE": "ARCHITECT에게 파일 삭제를 제외한 작업 계획을 다시 만들도록 요청하세요.",
    "SCOPE_VIOLATION": "ARCHITECT에게 허용된 범위 안에서만 작업하도록 다시 요청하세요.",
    "AMBIGUOUS_SCOPE": "ARCHITECT에게 작업 범위를 구체적으로 지정해 계획을 다시 만들도록 요청하세요.",
    "REGRESSION": "ARCHITECT에게 기존 테스트를 깨뜨리지 않도록 다시 시도하도록 요청하세요.",
    "WORKTREE_EVIDENCE_MISSING": "다시 시도하거나 TRIBUNAL AI 로그를 확인해주세요.",
    "INSPECTOR_FAIL_CLOSED": "다시 시도하거나 감리 로그를 확인해주세요.",
    "INSPECTOR_EXCEPTION": "다시 시도하거나 감리 로그를 확인해주세요.",
    "FINAL_GATE": "다시 시도하거나 검증 로그를 확인해주세요.",
    "BASELINE_MISSING": "프로젝트에 기존 테스트가 있는지 확인한 뒤 다시 시도해주세요.",
    "BASELINE_FAILED": "먼저 프로젝트의 기존 테스트를 통과시킨 뒤 다시 시도해주세요.",
    "EVIDENCE_MISSING": "다시 시도해주세요.",
    "PROVIDER_STOP": "AI 상태가 복구된 뒤 다시 시도해주세요.",
    "PROJECT_SELECTION_REQUIRED": "프로젝트를 먼저 선택해주세요.",
}
_DEFAULT_RECOMMENDATION = "ARCHITECT에게 다시 요청하거나 상세 정보를 확인하세요."

_RETRY_TEMPLATES: Dict[str, str] = {   # code -> Korean draft message pre-filled into the ARCHITECT chat input (never auto-sent)
    "GIT_INTERNALS_IN_SCOPE": "{file}은(는) 수정하지 말고, Git 내부 영역을 작업 범위에서 제외한 뒤 기존 요청을 다시 계획해줘.",
    "CONTROL_PLANE_IN_SCOPE": "{file}은(는) 수정하지 말고, TRIBUNAL AI 보호 파일을 작업 범위에서 제외한 뒤 기존 요청을 다시 계획해줘.",
    "CONTROL_PLANE_MODIFIED": "{file}은(는) 수정하지 말고, TRIBUNAL AI 보호 파일을 작업 범위에서 제외한 뒤 기존 요청을 다시 계획해줘.",
    "PROTECTED_PATH_IN_SCOPE": "{file}은(는) 수정하지 말고, 보호된 경로를 작업 범위에서 제외한 뒤 기존 요청을 다시 계획해줘.",
    "PROTECTED_PATH_INSIDE_ALLOWED": "{file}은(는) 수정하지 말고, 보호된 경로를 작업 범위에서 제외한 뒤 기존 요청을 다시 계획해줘.",
    "CANONICAL_CONTAINMENT": "작업 폴더 밖으로 연결되는 경로 없이, 작업 폴더 안에서만 접근하도록 기존 요청을 다시 계획해줘.",
    "ORDER_PATH_VIOLATION": "작업 폴더 밖 경로 없이, 작업 폴더 안 경로만 사용하도록 기존 요청을 다시 계획해줘.",
    "INVALID_PATH": "경로 형식을 프로젝트 기준 상대 경로로 바로잡아서 기존 요청을 다시 계획해줘.",
    "DESTRUCTIVE_CHANGE": "파일 삭제 없이 기존 요청을 다시 계획해줘.",
    "SCOPE_VIOLATION": "허용된 작업 범위 안에서만 변경하도록 기존 요청을 다시 계획해줘.",
    "AMBIGUOUS_SCOPE": "작업 범위(허용 경로)를 구체적으로 지정해서 기존 요청을 다시 계획해줘.",
}


def reason_recommendation(code: str) -> str:
    from core.role_names import canon_codes
    return REASON_RECOMMENDATION.get(canon_codes(str(code or "").upper()), _DEFAULT_RECOMMENDATION)


def retry_prompt(code: str, file: str = "") -> str:
    """Korean draft message for the 'ARCHITECT에게 다시 요청' button. Never sent automatically; the user reviews and
    presses Send."""
    from core.role_names import canon_codes
    code = canon_codes(str(code or "").upper())
    tmpl = _RETRY_TEMPLATES.get(code)
    if tmpl:
        return tmpl.format(file=(file or {"GIT_INTERNALS_IN_SCOPE": ".git", "CONTROL_PLANE_IN_SCOPE": "TRIBUNAL AI 설정 파일",
                                           "CONTROL_PLANE_MODIFIED": "TRIBUNAL AI 설정 파일"}.get(code, "해당 경로")))
    title, _why = reason_ko(code)
    loc = f" ({file})" if file else ""
    return f"{title}{loc} 문제를 해결해서 기존 요청을 다시 계획해줘."


HELP_TEXT: Dict[str, str] = {
    "DEGRADED": "일부 AI를 사용할 수 없지만 작업은 계속할 수 있는 상태입니다.",
    "STOP": "사용 가능한 AI가 부족해 자동 작업을 시작할 수 없는 상태입니다.",
    "RECOVERING": "AI 실행 파일은 정상이지만 사용량이 확인되지 않아 실제 호출 1회로 검증하는 상태입니다.",
    "worktree": "원본 프로젝트를 보호하기 위해 별도로 만든 작업 사본입니다.",
    "INSPECTOR": "Maker가 작성한 코드를 독립적으로 검토합니다.",
    "ARCHITECT": "요청을 분석해 작업 계획(ORDER)을 만들고 최종 판단을 내립니다.",
    "MAKER": "허용된 범위 안에서만 코드를 작성합니다.",
}

# code detection order for free-text reasons (transition details / blocks)
_REASON_PATTERNS: List[Tuple[str, str]] = [
    (r"APPROVAL_REQUIRED:\s*([A-Z_]+)", None),
    (r"Dependency configuration modified", "DEPENDENCY_CONFIGURATION_MODIFIED"),
    (r"Live money code", "LIVE_MONEY_CODE"),
    (r"Control plane modified", "CONTROL_PLANE_MODIFIED"),
    (r"CANONICAL_CONTAINMENT|resolves outside worktree|escapes worktree", "CANONICAL_CONTAINMENT"),
    (r"ORDER_PATH_VIOLATION", "ORDER_PATH_VIOLATION"),
    (r"REGRESSION|decreased from", "REGRESSION"),
    (r"WORKTREE_EVIDENCE_MISSING", "WORKTREE_EVIDENCE_MISSING"),
    (r"BASELINE_MISSING", "BASELINE_MISSING"),
    (r"BASELINE_FAILED", "BASELINE_FAILED"),
    (r"EVIDENCE_MISSING", "EVIDENCE_MISSING"),
    (r"INSPECTOR_EXCEPTION|Inspector .*unparseable|review .*fail", "INSPECTOR_FAIL_CLOSED"),
    (r"FINAL_GATE", "FINAL_GATE"),
    (r"Scope violation", "SCOPE_VIOLATION"),
    (r"PROVIDER_FAILURE|PROVIDER_STOP|SYSTEM STOP", "PROVIDER_STOP"),
    (r"PROJECT_SELECTION_REQUIRED", "PROJECT_SELECTION_REQUIRED"),
    (r"Main project changed", "BASE_COMMIT_MISMATCH"),
    (r"not clean", "WORKING_TREE_DIRTY"),
    (r"collides", "UNTRACKED_COLLISION"),
]


def t(key: str, default: Optional[str] = None) -> str:
    return UI_TEXT.get(key, default if default is not None else key)


def status_ko(raw: str) -> str:
    return STATUS_TEXT.get(str(raw or "").upper(), str(raw or ""))


def state_ko(raw: str) -> str:
    return STATE_TEXT.get(str(raw or "").upper(), str(raw or ""))


def result_ko(raw: str) -> str:
    return RESULT_TEXT.get(str(raw or "").upper(), str(raw or ""))


def role_ko(roles: str) -> str:
    """'ARCHITECT, INSPECTOR' -> 'ARCHITECT · INSPECTOR (설계 · 감리)'"""
    parts = [r.strip().upper() for r in str(roles or "").replace("·", ",").split(",") if r.strip()]
    if not parts:
        return ""
    return " · ".join(parts) + " (" + " · ".join(ROLE_TEXT.get(p, p) for p in parts) + ")"


def reason_code(text: str) -> str:
    """Best-effort technical code for a free-text halt reason."""
    from core.role_names import canon_codes
    s = canon_codes(str(text or "")).replace("Reviewer ", "Inspector ")       # wording from before the role rename
    for pat, code in _REASON_PATTERNS:
        m = re.search(pat, s)
        if m:
            return code or m.group(1)
    return "UNKNOWN"


def reason_ko(code: str) -> Tuple[str, str]:
    from core.role_names import canon_codes
    return REASON_TEXT.get(canon_codes(str(code or "").upper()), REASON_TEXT["UNKNOWN"])


def explain_reason(text: str) -> Dict[str, str]:
    code = reason_code(text)
    title, why = reason_ko(code)
    return {"code": code, "title": title, "why": why, "raw": str(text or "")}


def mode_sentence(mode: str, statuses: Dict[str, str]) -> str:
    """'일부 기능 제한 · Claude 백업 AI가 복구 중입니다. Codex와 Antigravity는 정상 사용 가능합니다.'"""
    names = {d: PROVIDER_LABEL[d][2] for d in PROVIDER_LABEL}
    ok = [names[d] for d in ("OPENAI", "GOOGLE", "ANTHROPIC") if statuses.get(d) == "HEALTHY"]
    bad = []
    for d in ("OPENAI", "GOOGLE", "ANTHROPIC"):
        st = statuses.get(d)
        if st and st != "HEALTHY":
            bad.append(f"{names[d]}{' 백업 AI가' if d == 'ANTHROPIC' else '가'} {status_ko(st)}입니다.")
    if mode == "NORMAL":
        return "3개 AI 모두 정상 사용 가능합니다."
    usable = len(ok) + (1 if any("복구 중" in b for b in bad) and mode == "DEGRADED" and len(ok) < 2 else 0)
    tail = (" " + "와 ".join(ok) + ("는" if len(ok) == 1 else "는") + " 정상 사용 가능합니다.") if ok else ""
    return " ".join(bad) + tail + (f" ({min(len(ok) + (0 if mode == 'STOP' else 1), 3) if mode == 'DEGRADED' else len(ok)}/3 AI 사용 가능)" if mode != "NORMAL" else "")


def stage_sentence(state: str, roles: Dict[str, str], elapsed: str = "") -> str:
    """'Codex가 코드를 작성하고 있습니다 · 42초'. roles: domain -> current_role string."""
    def who(role):
        for d, r in roles.items():
            if role in [x.strip().upper() for x in str(r or "").replace("·", ",").split(",")]:
                return PROVIDER_LABEL.get(d, (d, d, d))[2]
        return {"ARCHITECT": "Claude", "INSPECTOR": "Antigravity", "MAKER": "Codex"}.get(role, "AI")      # config.yaml's default roles
    s = (state or "").upper()
    txt = {
        "PLANNING": f"{who('ARCHITECT')}가 요청을 분석하고 있습니다",
        "ORDER_READY": "작업 사본을 준비하고 기준 테스트를 실행하고 있습니다",
        "BUILDING": f"{who('MAKER')}가 코드를 작성하고 있습니다",
        "VERIFYING": "테스트와 안전 검증을 실행하고 있습니다",
        "REVIEWING": f"{who('INSPECTOR')}가 변경 내용을 검토하고 있습니다",
        "DECIDING": f"{who('ARCHITECT')}가 최종 판단을 내리고 있습니다",
        "PASS": "작업이 완료되었습니다",
        "RECOVERED": "실패 작업을 복구하고 원본 프로젝트 검증을 완료했습니다",
        "FAIL": "작업이 실패했습니다",
        "TIMEOUT": "작업이 시간 초과로 중단되었습니다",
        "HUMAN_REQUIRED": "사용자 확인이 필요합니다",
        "REJECTED": "거절한 작업입니다 · 실행되지 않았습니다",
        "IDLE": "대기 중입니다",
        "NONE": t("architect_ready"),
    }.get(s, s)
    return txt + (f" · {elapsed}" if elapsed and s in ("PLANNING", "ORDER_READY", "BUILDING", "VERIFYING", "REVIEWING", "DECIDING") else "")


NEXT_STEP: Dict[str, str] = {
    "PLANNING": "작업 사본 준비 및 기준 테스트", "ORDER_READY": "제작", "BUILDING": "테스트 및 안전 검증",
    "VERIFYING": "감리", "REVIEWING": "최종 판단", "DECIDING": "최종 안전 검사", "RECOVERED": "복구 결과 확인 완료",
}


_EVENT_RULES: List[Tuple[str, str, str]] = [   # (regex on raw SYSTEM text, Korean compact text, kind)
    # Mission rows first: they quote the goal or a one-line summary, which may contain "ValueError", "failed" ...
    (r"\[(?:작업|미션) \d+/\d+\] 실행 시작", "● 작업 단계를 시작했습니다.", "ev-info"),
    (r"\[(?:작업|미션) \d+/\d+\] 결과 PASS", "✓ 작업 단계가 통과했습니다.", "ev-ok"),
    (r"\[(?:작업|미션) \d+/\d+\] 결과 ", "⚠ 작업 단계가 통과하지 못했습니다.", "ev-bad"),
    (r"\[(?:작업|미션) \d+/\d+\] 사용자 확인 요청", "● ARCHITECT가 사용자 확인 요청을 다시 검토합니다.", "ev-info"),
    (r"\[(?:작업|미션) \d+/\d+\] (?:ARCHITECT|HEAD) 계획", "● ARCHITECT가 다음 단계를 계획했습니다.", "ev-info"),
    (r"^(?:작업|미션) 시작", "● 작업을 시작했습니다.", "ev-info"),
    (r"결과물을 프로젝트에 적용했습니다", "✓ 결과물을 프로젝트에 적용했습니다.", "ev-ok"),
    (r"결과물을 자동 적용하지 않았습니다", "⚠ 결과물을 자동 적용하지 않았습니다.", "ev-bad"),
    (r"finished: PASS", "✓ 작업이 완료되었습니다.", "ev-ok"),
    (r"finished: HUMAN_REQUIRED", "⚠ 사용자 확인이 필요해 작업을 멈췄습니다.", "ev-bad"),
    (r"finished: (FAIL|TIMEOUT)", "✗ 작업이 실패했습니다.", "ev-bad"),
    (r"Starting background run", "● 작업을 시작했습니다.", "ev-info"),
    (r"HUMAN_APPROVED\(ENTRY\)|HUMAN_APPROVED:", "✓ 사용자가 작업 범위를 승인했습니다.", "ev-ok"),
    (r"HUMAN_APPROVED\(POST_BUILD\)", "✓ 사용자가 변경을 승인했습니다. 검증을 계속합니다.", "ev-ok"),
    (r"HUMAN_REJECTED", "○ 사용자가 거절했습니다. 이 작업은 실행되지 않습니다.", "ev-info"),   # the user's own decision: not an alarm
    (r"RECOVERY TRIAL", "● 복구 중인 AI를 실제 호출 1회로 검증합니다.", "ev-info"),
    (r"SYSTEM STOP", "✗ 사용 가능한 AI가 부족해 실행할 수 없습니다.", "ev-bad"),
    (r"PROJECT_SELECTED", "✓ 프로젝트를 선택했습니다.", "ev-ok"),
    (r"PROJECT_SELECTION_REJECTED|PROJECT_SELECTION_REQUIRED", "✗ 프로젝트 선택이 유효하지 않습니다.", "ev-bad"),
    (r"NEW_CHAT", "✓ 새 대화를 시작했습니다.", "ev-ok"),
    (r"RESULT_APPLIED", "✓ 결과물이 프로젝트에 적용되었습니다.", "ev-ok"),
    (r"RESULT_ROLLED_BACK", "✗ 적용에 실패해 적용 전 상태로 복구했습니다.", "ev-bad"),
    (r"RESULT_BLOCKED", "⚠ 결과를 적용할 수 없습니다.", "ev-bad"),
    (r"RESULT_DISCARDED", "○ 결과물이 폐기되었습니다.", "ev-info"),
    (r"HUMAN_REQUIRED|APPROVAL_REQUIRED", "⚠ 사용자 확인이 필요합니다.", "ev-bad"),
    (r"BUSY", "⚠ 다른 작업이 진행 중입니다.", "ev-bad"),
    (r"(?:ARCHITECT|HEAD) Error|(?<![A-Za-z0-9_])Error(?![A-Za-z0-9_])|(?<![A-Za-z0-9_])failed(?![A-Za-z0-9_])", "✗ 오류가 발생했습니다.", "ev-bad"),
]


def event_ko(raw: str) -> Tuple[str, str]:
    for pat, text, kind in _EVENT_RULES:
        if re.search(pat, str(raw or "")):
            return text, kind
    return "· 시스템 알림", "ev-info"


_ERROR_TEXT = "✗ 오류가 발생했습니다."


def event_line(raw: str) -> str:
    """The Korean sentence for a raw SYSTEM message, or "" when the raw text says more than the sentence would
    (a message already in Korean, an unknown one, or an error whose detail is the point)."""
    if re.search("[가-힣]", str(raw or "")):       # already written for the user (a step's plan, a result with its reason)
        return ""
    text, _kind = event_ko(raw)
    return "" if text in ("· 시스템 알림", _ERROR_TEXT) else text


def i18n_bundle() -> Dict[str, object]:
    """Everything the page script needs to render Korean labels client-side."""
    return {
        "lang": LANG, "ui": UI_TEXT, "status": STATUS_TEXT, "state": STATE_TEXT, "result": RESULT_TEXT, "role": ROLE_TEXT, "speaker": SPEAKER_TEXT,
        "stage": STAGE_TEXT, "help": HELP_TEXT, "next": NEXT_STEP,
        "provider": {d: {"name": v[0], "vendor": v[1], "subject": v[2]} for d, v in PROVIDER_LABEL.items()},
        "events": [[p, txt, k] for p, txt, k in _EVENT_RULES],
        "reasons": {k: {"title": v[0], "why": v[1], "recommendation": REASON_RECOMMENDATION.get(k, _DEFAULT_RECOMMENDATION)} for k, v in REASON_TEXT.items()},
    }
