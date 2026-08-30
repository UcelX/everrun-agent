from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from everrun_agent import (
    ActionLedger,
    EventType,
    EverRunStore,
    Mission,
    RecoveryMode,
    StateProjector,
    UncertainAction,
    checkpoint,
    recover,
)


def test_event_chain_detects_tampering(tmp_path: Path) -> None:
    db = tmp_path / "relay.db"
    with EverRunStore(db) as store:
        store.create_mission(Mission("m1", "Ship safely", 3))
        store.append("m1", EventType.WORK_COMPLETED, {"item": "a"})
        assert store.verify_chain("m1").ok
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            store.raw_execute(
                "UPDATE events SET payload = ? WHERE mission_id = ? AND sequence = 2",
                ('{"item":"evil"}', "m1"),
            )
        assert store.verify_chain("m1").ok


def test_projection_rebuilds_semantic_state(tmp_path: Path) -> None:
    with EverRunStore(tmp_path / "relay.db") as store:
        store.create_mission(Mission("m1", "Process files", 2))
        store.append("m1", EventType.DECISION_RECORDED, {"id": "d1", "text": "Use UTF-8"})
        store.append("m1", EventType.WORK_COMPLETED, {"item": "a"})
        store.append("m1", EventType.WORK_FAILED, {"item": "b", "reason": "bad"})
        one = StateProjector.project(store.events("m1"))
        two = StateProjector.project(store.events("m1"))
        assert one == two
        assert one.completed == ("a",)
        assert one.failed == ("b",)
        assert one.decisions[0].text == "Use UTF-8"


def test_sqlite_roundtrip_and_sequence(tmp_path: Path) -> None:
    db = tmp_path / "relay.db"
    with EverRunStore(db) as store:
        store.create_mission(Mission("m1", "Persist", 1))
        store.append("m1", EventType.WORK_COMPLETED, {"item": "a"})
    with EverRunStore(db) as reopened:
        assert [e.sequence for e in reopened.events("m1")] == [1, 2]
        assert reopened.get_mission("m1").goal == "Persist"


def test_checkpoint_detects_modified_payload(tmp_path: Path) -> None:
    with EverRunStore(tmp_path / "relay.db") as store:
        store.create_mission(Mission("m1", "Seal", 1))
        cp = checkpoint(store, "m1")
        assert cp.verify()
        altered = cp.replace_payload(cp.payload.replace("Seal", "Fake"))
        assert not altered.verify()


def test_completed_action_is_idempotent(tmp_path: Path) -> None:
    with EverRunStore(tmp_path / "relay.db") as store:
        store.create_mission(Mission("m1", "Deploy", 1))
        ledger = ActionLedger(store, "m1")
        first = ledger.claim("deploy", {"commit": "abc"})
        ledger.complete(first.key, external_id="dep-1", result={"url": "https://example.test"})
        again = ledger.claim("deploy", {"commit": "abc"})
        assert not again.fresh
        assert again.external_id == "dep-1"


def test_started_action_blocks_blind_retry(tmp_path: Path) -> None:
    with EverRunStore(tmp_path / "relay.db") as store:
        store.create_mission(Mission("m1", "Deploy", 1))
        ledger = ActionLedger(store, "m1")
        ledger.claim("deploy", {"commit": "abc"})
        with pytest.raises(UncertainAction):
            ledger.claim("deploy", {"commit": "abc"})


def test_recovery_requires_reconciliation_first(tmp_path: Path) -> None:
    with EverRunStore(tmp_path / "relay.db") as store:
        store.create_mission(Mission("m1", "Deploy", 1))
        ledger = ActionLedger(store, "m1")
        claim = ledger.claim("deploy", {"commit": "abc"})
        decision = recover(store, "m1")
        assert decision.mode is RecoveryMode.RECONCILE
        assert decision.next_safe_action == f"reconcile:{claim.key}"
        assert not decision.safe
