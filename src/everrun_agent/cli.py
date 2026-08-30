from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from .capsule import export_capsule, import_capsule
from .demo import run_crash_recovery_demo
from .models import EventType, Mission
from .projection import StateProjector
from .recovery import recover
from .store import EverRunStore


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="everrun", description="Durable mission continuity for AI agents"
    )
    p.add_argument("--db", default=".everrun_agent/relay.db")
    sub = p.add_subparsers(dest="command", required=True)
    x = sub.add_parser("init")
    x.add_argument("mission_id")
    x.add_argument("goal")
    x.add_argument("--total", type=int, default=0)
    x = sub.add_parser("complete-work")
    x.add_argument("mission_id")
    x.add_argument("item")
    x = sub.add_parser("status")
    x.add_argument("mission_id")
    x.add_argument("--json", action="store_true")
    x = sub.add_parser("verify")
    x.add_argument("mission_id")
    x = sub.add_parser("export")
    x.add_argument("mission_id")
    x.add_argument("path")
    x = sub.add_parser("import")
    x.add_argument("path")
    x = sub.add_parser("demo")
    x.add_argument("--workdir", default="everrun-demo")
    x.add_argument("--total", type=int, default=100)
    x.add_argument("--crash-at", type=int, default=40)
    return p


def main(argv: list[str] | None = None) -> int:
    a = parser().parse_args(argv)
    if a.command == "demo":
        print(
            json.dumps(
                asdict(run_crash_recovery_demo(a.workdir, a.total, a.crash_at)), sort_keys=True
            )
        )
        return 0
    db = Path(a.db)
    db.parent.mkdir(parents=True, exist_ok=True)
    with EverRunStore(db) as store:
        if a.command == "init":
            store.create_mission(Mission(a.mission_id, a.goal, a.total))
            print(a.mission_id)
            return 0
        if a.command == "complete-work":
            store.append(a.mission_id, EventType.WORK_COMPLETED, {"item": a.item})
            print(a.item)
            return 0
        if a.command == "status":
            s = StateProjector.project(store.events(a.mission_id))
            d = recover(store, a.mission_id)
            data = {
                "mission_id": s.mission_id,
                "goal": s.goal,
                "total": s.total,
                "completed": len(s.completed),
                "failed": len(s.failed),
                "mode": d.mode.value,
                "safe": d.safe,
                "next_safe_action": d.next_safe_action,
            }
            print(
                json.dumps(data, sort_keys=True)
                if a.json
                else f"{s.mission_id}: {len(s.completed)}/{s.total} | {d.mode.value} | next={d.next_safe_action}"
            )
            return 0
        if a.command == "verify":
            r = store.verify_chain(a.mission_id)
            print(json.dumps(asdict(r), sort_keys=True))
            return 0 if r.ok else 20
        if a.command == "export":
            print(export_capsule(store, a.mission_id, a.path))
            return 0
        if a.command == "import":
            print(import_capsule(store, a.path))
            return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
