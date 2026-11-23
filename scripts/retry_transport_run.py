"""Run again a step that stopped on a CLI transport failure (the connection to the AI broke, not the work itself).

    .venv/bin/python scripts/retry_transport_run.py RUN-...

Only a run whose recorded failure is a transport error is reopened (core.state_machine.reopen_transport_failure);
anything else is left unchanged. The run then goes through the normal pipeline from where it stopped - tests,
inspection and the final checks included. A task (mission) the run belongs to is continued from the console
("이어서 시도") as usual.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1 or not argv[0].startswith("RUN-"):
        print(__doc__.strip().splitlines()[2].strip(), file=sys.stderr)
        return 2
    from director import load_config
    from core.orchestrator import Orchestrator
    orch = Orchestrator(load_config())
    run_id = argv[0]
    if not orch.sm.reopen_transport_failure(run_id):
        print("연결 오류로 멈춘 실행이 아닙니다. 아무것도 바꾸지 않았습니다.", file=sys.stderr)
        return 1
    print(orch.resume(run_id), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
