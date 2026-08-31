from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .ledger import ActionLedger
from .models import EventType, Mission
from .projection import StateProjector
from .recovery import recover
from .store import EverRunStore


@dataclass(frozen=True)
class DemoResult:
    completed: int
    unique_outputs: int
    duplicates: int
    chain_valid: bool
    side_effect_count: int


def run_crash_recovery_demo(root: str | Path, total: int = 100, crash_at: int = 40) -> DemoResult:
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    db = root / "everrun-demo.db"
    out = root / "output.txt"
    effect = root / "side-effect.txt"
    if db.exists():
        db.unlink()
    for suffix in ("-wal", "-shm"):
        p = Path(str(db) + suffix)
        p.unlink(missing_ok=True)
    out.unlink(missing_ok=True)
    effect.unlink(missing_ok=True)
    with EverRunStore(db) as store:
        store.create_mission(Mission("demo", "Process unique items", total))
        ledger = ActionLedger(store, "demo")
        for i in range(crash_at):
            with out.open("a", encoding="utf-8") as handle:
                handle.write(f"{i}\n")
            store.append("demo", EventType.WORK_COMPLETED, {"item": str(i)})
        claim = ledger.claim("publish", {"target": "side-effect.txt"})
        effect.write_text("published\n", encoding="utf-8")
        # simulated process death: effect happened, completion record did not
    with EverRunStore(db) as store:
        decision = recover(store, "demo")
        assert decision.next_safe_action == f"reconcile:{claim.key}"
        ledger = ActionLedger(store, "demo")
        ledger.reconcile(
            claim.key, effect.exists(), external_id="side-effect.txt", result={"digest": "observed"}
        )
        state = StateProjector.project(store.events("demo"))
        done = set(state.completed)
        for i in range(total):
            if str(i) not in done:
                with out.open("a", encoding="utf-8") as handle:
                    handle.write(f"{i}\n")
                store.append("demo", EventType.WORK_COMPLETED, {"item": str(i)})
        lines = out.read_text().splitlines()
        final = StateProjector.project(store.events("demo"))
        return DemoResult(
            len(final.completed),
            len(set(lines)),
            len(lines) - len(set(lines)),
            store.verify_chain("demo").ok,
            len(effect.read_text().splitlines()),
        )
