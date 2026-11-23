"""Every AI in every role, for real: can each CLI act as ARCHITECT, MAKER and INSPECTOR?

    .venv/bin/python scripts/test_role_cli_smoke.py                       # all 3 AIs x 3 roles = 9 calls
    .venv/bin/python scripts/test_role_cli_smoke.py --providers openai --roles maker,inspector

Spends subscription quota (one small call per pair). Worth running after a CLI update or before giving an AI a role it
has not held. The AIs run in parallel, one call at a time each. Every call works in a throw-away folder; the code a
MAKER writes is run in a separate Python process, never in this one. Prints one JSON line per check; the exit code
is 1 when any check failed.
"""
import argparse
import concurrent.futures
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main(argv=None) -> int:
    from core.role_checks import PROVIDERS, ROLES, check, plan
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--providers", default=",".join(PROVIDERS), help="comma separated: " + ", ".join(PROVIDERS))
    parser.add_argument("--roles", default=",".join(ROLES), help="comma separated: " + ", ".join(ROLES))
    args = parser.parse_args(argv)
    pairs = plan([r for r in args.roles.split(",") if r], [p for p in args.providers.split(",") if p])

    from director import load_config
    from core.orchestrator import Orchestrator
    orch = Orchestrator(config=load_config())

    def one_ai(provider):                                   # one AI's checks one after another: never two calls at once
        return [check(orch, role, provider) for role, p in pairs if p == provider]

    failed = 0
    providers = list(dict.fromkeys(p for _r, p in pairs))
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(providers) or 1) as pool:
        for results in pool.map(one_ai, providers):
            for result in results:
                failed += not result["ok"]
                print(json.dumps(result, ensure_ascii=False), flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
