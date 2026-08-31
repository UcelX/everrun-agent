#!/usr/bin/env python3
"""Deterministic protocol-level dogfood fallback; does not touch Hermes configuration."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from everrun_agent import ActionLedger, EverRunStore, Mission
from everrun_agent.models import Origin


def run(workdir: Path) -> dict[str, object]:
    workdir.mkdir(parents=True, exist_ok=True)
    db, marker = workdir / "everrun.db", workdir / "effect.txt"
    with EverRunStore(db) as store:
        store.create_mission(Mission("dogfood-ci", "prove recovery", 1))
        ledger = ActionLedger(store, "dogfood-ci")
        claim = ledger.claim("marker", {"path": "redacted"})
        transitions = ["reconcile"]
        ledger.reconcile(claim.key, occurred=False)
        retry = ledger.claim("marker", {"path": "redacted"})
        marker.write_text("once\n", encoding="utf-8")
        ledger.complete(retry.key, result={"count": 1})
        store.append_work("dogfood-ci", "effect verified", origin=Origin.EXTERNAL_AGENT)
        transitions.append("request_review")
        request = store.request_approval("dogfood-ci")
        store.approve_with_ticket(
            "dogfood-ci", request["ticket"], request["digest"], "harness-operator"
        )
        transitions.append("close_mission")
        store.complete_mission("dogfood-ci")
        transitions.append("verified_complete")
        chain = store.verify_chain("dogfood-ci")
    return {
        "transitions": transitions,
        "marker_count": len(marker.read_text().splitlines()),
        "chain_ok": chain.ok,
        "trusted_through": chain.trusted_through,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workdir", type=Path, required=True)
    report = run(parser.parse_args().workdir)
    print(json.dumps(report, sort_keys=True))
    return 0 if report["chain_ok"] and report["marker_count"] == 1 else 20


if __name__ == "__main__":
    raise SystemExit(main())
