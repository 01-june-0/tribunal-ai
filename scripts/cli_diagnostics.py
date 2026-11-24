"""Check the three AI CLIs as the next run will use them: version, then one real call per AI in its assigned role.

    .venv/bin/python scripts/cli_diagnostics.py

Spends a little subscription quota (one small call per assigned role, so three calls). The roles come from
config.yaml plus the role chosen in the console, exactly as a run reads them. Every call works in a throw-away
folder; the code a MAKER writes is run in a separate Python process. The report is written to
data/cli_diagnostics.json (`GET /ops/state` returns it) and printed here.
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.paths import data_dir  # noqa: E402

REPORT = data_dir() / "cli_diagnostics.json"
EXECUTABLES = {"claude": "claude", "openai": "codex", "antigravity": "agy"}
NAMES = {"claude": "Claude", "openai": "Codex", "antigravity": "Antigravity"}
ROLE_KO = {"architect": "설계", "maker": "제작", "inspector": "감리"}


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    from director import load_config
    from core.env_utils import probe_version, resolve_cli
    from core.orchestrator import Orchestrator
    from core.role_checks import check, current_assignment

    config = load_config()
    roles = current_assignment(config)
    report = {"checked_at": datetime.now(timezone.utc).isoformat(), "roles": roles, "providers": {}, "checks": []}
    for alias, exe_name in EXECUTABLES.items():
        exe = resolve_cli(exe_name)
        report["providers"][alias] = {"executable": exe, "version": probe_version(exe, 10) if exe else None,
                                      "state": "INSTALLED" if exe else "MISSING"}
        print(f"{NAMES[alias]:<12} {'설치됨 ' + str(report['providers'][alias]['version'] or '') if exe else '설치되지 않음'}", flush=True)
    orch = Orchestrator(config=config)
    failed = 0
    for role, alias in roles.items():
        if report["providers"][alias]["state"] == "MISSING":
            result = {"role": role, "provider": alias, "ok": False, "seconds": 0, "detail": "CLI not installed"}
        else:
            print(f"{ROLE_KO[role]}({role}) · {NAMES[alias]} 확인 중…", flush=True)
            result = check(orch, role, alias)
        report["checks"].append(result)
        if report["providers"][alias]["state"] not in ("MISSING", "FAILED"):      # one AI may hold two roles: a failure sticks
            report["providers"][alias]["state"] = "VERIFIED" if result["ok"] else "FAILED"
        failed += not result["ok"]
        print(f"  {'통과' if result['ok'] else '실패'} · {result['seconds']}초 · {result['detail'][:200]}", flush=True)
        REPORT.parent.mkdir(parents=True, exist_ok=True)
        REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"결과: {len(roles) - failed}/{len(roles)} 통과 · {REPORT}", flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
