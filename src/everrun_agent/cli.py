from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from .adapters import install_hooks, uninstall_hooks
from .attestation import generate_keypair, sign_capsule, verify_capsule_signature
from .capsule import export_capsule, import_capsule
from .demo import run_crash_recovery_demo
from .handoff import AgentProfile, compile_briefing, handoff
from .ledger import ActionLedger
from .models import EventType, Mission, Origin
from .projection import StateProjector
from .recovery import recover
from .store import EverRunStore

DEFAULT_DB = ".everrun/everrun.db"

EXIT_OK = 0
EXIT_UNSAFE = 20
EXIT_ERROR = 2


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        prog="everrun",
        description="Durable mission continuity for AI agents: verified state, safe recovery, no duplicate side effects.",
    )
    root.add_argument("--db", default=DEFAULT_DB, help=f"mission database (default {DEFAULT_DB})")
    sub = root.add_subparsers(dest="command", required=True)

    start = sub.add_parser("init", help="create a mission")
    start.add_argument("mission_id")
    start.add_argument("goal")
    start.add_argument("--total", type=int, default=0)

    work = sub.add_parser("complete-work", help="record one verified work item")
    work.add_argument("mission_id")
    work.add_argument("item")
    work.add_argument("--external-agent", action="store_true", help="mark as agent-reported")

    decide = sub.add_parser("record-decision", help="record a durable decision")
    decide.add_argument("mission_id")
    decide.add_argument("decision_id")
    decide.add_argument("text")

    for name, helptext in (
        ("status", "semantic state plus recovery verdict"),
        ("resume", "recovery contract and the single next safe action"),
        ("briefing", "minimal sufficient context for a fresh session"),
        ("actions", "uncertain side effects awaiting reconciliation"),
        ("verify", "re-audit the event hash chain"),
    ):
        item = sub.add_parser(name, help=helptext)
        item.add_argument("mission_id")
        item.add_argument("--json", action="store_true")
        if name == "briefing":
            item.add_argument("--context-tokens", type=int, default=16000)

    checkpoint = sub.add_parser("checkpoint", help="seal a semantic checkpoint")
    checkpoint.add_argument("mission_id")
    checkpoint.add_argument("--reason", default="manual")

    confirm = sub.add_parser("confirm", help="human confirmation of agent-reported state")
    confirm.add_argument("mission_id")

    reconcile = sub.add_parser("reconcile", help="settle one uncertain side effect")
    reconcile.add_argument("mission_id")
    reconcile.add_argument("key")
    reconcile.add_argument("--occurred", action="store_true")
    reconcile.add_argument("--external-id")

    give = sub.add_parser("handoff", help="transfer the mission to another agent")
    give.add_argument("mission_id")
    give.add_argument("to_agent")
    give.add_argument("--context-tokens", type=int, default=16000)
    give.add_argument("--from-agent")

    export = sub.add_parser("export", help="write a portable capsule")
    export.add_argument("mission_id")
    export.add_argument("path")

    load = sub.add_parser("import", help="import a capsule after verification")
    load.add_argument("path")

    keygen = sub.add_parser("keygen", help="generate an attestation key")
    keygen.add_argument("--out")

    sign = sub.add_parser("sign", help="sign a capsule")
    sign.add_argument("path")
    sign.add_argument("--key", required=True)
    sign.add_argument("--signer", required=True)

    check = sub.add_parser("verify-capsule", help="verify a signed capsule")
    check.add_argument("path")
    check.add_argument("--key", required=True)
    check.add_argument("--signer", required=True)

    hooks = sub.add_parser("hooks", help="install or remove coding-agent lifecycle hooks")
    hooks.add_argument("action", choices=("install", "uninstall"))
    hooks.add_argument("client", choices=("hermes", "claude-code", "codex"))
    hooks.add_argument("--config", default=".everrun/hooks.json")

    demo = sub.add_parser("demo", help="run the crash-recovery proof")
    demo.add_argument("--workdir", default="everrun-demo")
    demo.add_argument("--total", type=int, default=100)
    demo.add_argument("--crash-at", type=int, default=40)
    return root


def _emit(data: dict[str, object], as_json: bool, human: str) -> None:
    print(json.dumps(data, sort_keys=True) if as_json else human)


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)

    if args.command == "demo":
        print(
            json.dumps(
                asdict(run_crash_recovery_demo(args.workdir, args.total, args.crash_at)),
                sort_keys=True,
            )
        )
        return EXIT_OK
    if args.command == "keygen":
        private_key, public_key = generate_keypair()
        if args.out:
            target = Path(args.out)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(private_key, encoding="utf-8")
            target.chmod(0o600)
            print(str(target))
        else:
            print(json.dumps({"private_key": private_key, "public_key": public_key}))
        return EXIT_OK
    if args.command == "sign":
        print(
            str(
                sign_capsule(
                    args.path, Path(args.key).read_text(encoding="utf-8").strip(), args.signer
                )
            )
        )
        return EXIT_OK
    if args.command == "verify-capsule":
        key = Path(args.key).read_text(encoding="utf-8").strip()
        verify_capsule_signature(args.path, {args.signer: key})
        print(json.dumps({"verified": True, "signer": args.signer}))
        return EXIT_OK
    if args.command == "hooks":
        config = Path(args.config)
        db = Path(args.db)
        if args.action == "install":
            print(json.dumps(install_hooks(config, args.client, db), sort_keys=True))
        else:
            uninstall_hooks(config, args.client)
            print(json.dumps({"removed": args.client}))
        return EXIT_OK

    db = Path(args.db)
    db.parent.mkdir(parents=True, exist_ok=True)
    with EverRunStore(db) as store:
        if args.command == "init":
            store.create_mission(Mission(args.mission_id, args.goal, args.total))
            print(args.mission_id)
            return EXIT_OK
        if args.command == "complete-work":
            origin = Origin.EXTERNAL_AGENT if args.external_agent else Origin.DETERMINISTIC
            store.append_work(args.mission_id, args.item, origin=origin)
            print(args.item)
            return EXIT_OK
        if args.command == "record-decision":
            store.append_decision(args.mission_id, args.decision_id, args.text)
            print(args.decision_id)
            return EXIT_OK
        if args.command == "verify":
            report = store.verify_chain(args.mission_id)
            _emit(
                asdict(report),
                args.json,
                f"chain ok={report.ok} trusted_through={report.trusted_through}",
            )
            return EXIT_OK if report.ok else EXIT_UNSAFE
        if args.command in {"status", "resume", "briefing", "actions"}:
            chain = store.verify_chain(args.mission_id)
            if not chain.ok:
                _emit(
                    {"ok": False, "error": chain.error, "trusted_through": chain.trusted_through},
                    getattr(args, "json", False),
                    f"chain corrupt: {chain.error}",
                )
                return EXIT_UNSAFE
            decision = recover(store, args.mission_id)
            if args.command == "status":
                state = StateProjector.project(store.events(args.mission_id))
                _emit(
                    {
                        "mission_id": state.mission_id,
                        "goal": state.goal,
                        "total": state.total,
                        "completed": len(state.completed),
                        "failed": len(state.failed),
                        "mode": decision.mode.value,
                        "safe": decision.safe,
                        "next_safe_action": decision.next_safe_action,
                    },
                    args.json,
                    f"{state.mission_id}: {len(state.completed)}/{state.total} | {decision.mode.value} | next={decision.next_safe_action}",
                )
            elif args.command == "resume":
                _emit(
                    {
                        "mode": decision.mode.value,
                        "safe": decision.safe,
                        "next_safe_action": decision.next_safe_action,
                        "reasons": list(decision.reasons),
                        "digest": decision.digest,
                    },
                    args.json,
                    f"{decision.mode.value} | safe={decision.safe} | next={decision.next_safe_action}",
                )
            elif args.command == "briefing":
                text = compile_briefing(
                    store, args.mission_id, AgentProfile("cli", context_tokens=args.context_tokens)
                )
                _emit({"briefing": text}, args.json, text)
            else:
                pending = ActionLedger(store, args.mission_id).uncertain_details()
                _emit(
                    {"uncertain": pending},
                    args.json,
                    "\n".join(f"{row['action_key']} {row['kind']}" for row in pending) or "none",
                )
            return EXIT_OK if decision.safe else EXIT_UNSAFE
        if args.command == "checkpoint":
            saved = store.create_checkpoint(args.mission_id, reason=args.reason)
            print(json.dumps({"sequence": saved.sequence, "digest": saved.digest}))
            return EXIT_OK
        if args.command == "confirm":
            store.append(
                args.mission_id,
                EventType.REVIEW_CONFIRMED,
                {"confirmed_by": "cli-operator"},
                origin=Origin.HUMAN,
            )
            print(json.dumps({"confirmed": True}))
            return EXIT_OK
        if args.command == "reconcile":
            ActionLedger(store, args.mission_id).reconcile(
                args.key, occurred=args.occurred, external_id=args.external_id
            )
            print(json.dumps({"reconciled": args.key, "occurred": bool(args.occurred)}))
            return EXIT_OK
        if args.command == "handoff":
            capsule = handoff(
                store,
                args.mission_id,
                AgentProfile(args.to_agent, context_tokens=args.context_tokens),
                from_agent=args.from_agent,
            )
            print(
                json.dumps(
                    {
                        "to_agent": capsule.to_agent,
                        "from_agent": capsule.from_agent,
                        "next_safe_action": capsule.next_safe_action,
                        "digest": capsule.digest,
                    },
                    sort_keys=True,
                )
            )
            return EXIT_OK
        if args.command == "export":
            print(str(export_capsule(store, args.mission_id, args.path)))
            return EXIT_OK
        if args.command == "import":
            print(import_capsule(store, args.path))
            return EXIT_OK
    return EXIT_ERROR


if __name__ == "__main__":
    raise SystemExit(main())
