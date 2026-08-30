"""Crash worker used by the fault-injection suite.

phase-one performs real work, fires one external side effect, then dies via
os.kill(SIGKILL) before recording completion. phase-two runs in a brand new
process and must recover without duplicating anything.
"""

from __future__ import annotations

import json
import os
import signal
import sys
from pathlib import Path

from everrun_agent import ActionLedger, EverRunStore, Mission
from everrun_agent.projection import StateProjector
from everrun_agent.reconcilers import ReconcilerRegistry, reconcile_pending
from everrun_agent.recovery import recover


def phase_one(db: Path, output: Path, effect: Path, crash_at: int, total: int) -> None:
    with EverRunStore(db) as store:
        store.create_mission(Mission("bench", "process items exactly once", total))
        ledger = ActionLedger(store, "bench")
        for index in range(crash_at):
            with output.open("a", encoding="utf-8") as handle:
                handle.write(f"{index}\n")
            store.append_work("bench", str(index))
        ledger.claim("publish", {"target": str(effect)})
        with effect.open("a", encoding="utf-8") as handle:
            handle.write("published\n")
        store.conn.commit()
    os.kill(os.getpid(), signal.SIGKILL)


def phase_two(db: Path, output: Path, effect: Path, crash_at: int, total: int) -> None:
    with EverRunStore(db) as store:
        before = recover(store, "bench")
        refused = not before.safe
        ledger = ActionLedger(store, "bench")
        registry = ReconcilerRegistry()
        registry.register("publish", lambda args: Path(args["target"]).exists())
        reconcile_pending(ledger, registry)
        state = StateProjector.project(store.events("bench"))
        done = set(state.completed)
        for index in range(total):
            if str(index) not in done:
                with output.open("a", encoding="utf-8") as handle:
                    handle.write(f"{index}\n")
                store.append_work("bench", str(index))
        final = StateProjector.project(store.events("bench"))
        lines = output.read_text(encoding="utf-8").splitlines()
        print(
            json.dumps(
                {
                    "refused_blind_resume": refused,
                    "mode_before_reconcile": before.mode.value,
                    "completed": len(final.completed),
                    "duplicates": len(lines) - len(set(lines)),
                    "chain_valid": store.verify_chain("bench").ok,
                    "side_effect_lines": len(effect.read_text(encoding="utf-8").splitlines()),
                },
                sort_keys=True,
            )
        )


def main() -> int:
    phase, db, output, effect, crash_at, total = (
        sys.argv[1],
        Path(sys.argv[2]),
        Path(sys.argv[3]),
        Path(sys.argv[4]),
        int(sys.argv[5]),
        int(sys.argv[6]),
    )
    if phase == "phase-one":
        phase_one(db, output, effect, crash_at, total)
    else:
        phase_two(db, output, effect, crash_at, total)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
