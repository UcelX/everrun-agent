from __future__ import annotations

from pathlib import Path

import pytest

from everrun_agent import ActionLedger, EventType, EverRunStore, Mission
from everrun_agent.capsule import import_capsule


def test_mission_and_start_event_are_atomic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with EverRunStore(tmp_path / "everrun.db") as store:
        monkeypatch.setattr(
            store,
            "_insert_event",
            lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("fault")),
        )
        with pytest.raises(RuntimeError, match="fault"):
            store.create_mission(Mission("m1", "atomic", 1))
        assert store.conn.execute("SELECT count(*) FROM missions").fetchone()[0] == 0


def test_action_claim_and_event_are_atomic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    with EverRunStore(tmp_path / "everrun.db") as store:
        store.create_mission(Mission("m1", "atomic claim", 1))
        ledger = ActionLedger(store, "m1")
        monkeypatch.setattr(
            store,
            "_insert_event",
            lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("fault")),
        )
        with pytest.raises(RuntimeError, match="fault"):
            ledger.claim("deploy", {"commit": "abc"})
        assert store.conn.execute("SELECT count(*) FROM actions").fetchone()[0] == 0


def test_action_completion_and_event_are_atomic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with EverRunStore(tmp_path / "everrun.db") as store:
        store.create_mission(Mission("m1", "atomic complete", 1))
        ledger = ActionLedger(store, "m1")
        claim = ledger.claim("deploy", {"commit": "abc"})
        monkeypatch.setattr(
            store,
            "_insert_event",
            lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("fault")),
        )
        with pytest.raises(RuntimeError, match="fault"):
            ledger.complete(claim.key, external_id="dep-1")
        row = store.conn.execute(
            "SELECT status FROM actions WHERE action_key=?", (claim.key,)
        ).fetchone()
        assert row[0] == "started"


def test_checkpoint_and_anchor_are_atomic_and_immutable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with EverRunStore(tmp_path / "everrun.db") as store:
        store.create_mission(Mission("m1", "atomic checkpoint", 1))
        monkeypatch.setattr(
            store,
            "_insert_event",
            lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("fault")),
        )
        with pytest.raises(RuntimeError, match="fault"):
            store.create_checkpoint("m1")
        assert store.conn.execute("SELECT count(*) FROM checkpoints").fetchone()[0] == 0


def test_invalid_capsule_import_rolls_back(tmp_path: Path) -> None:
    capsule = tmp_path / "bad.rly"
    capsule.write_text(
        '{"body":{"format":"everrun-agent-capsule-v1","mission":{"mission_id":"bad","goal":"x","total":1},"events":[]},"digest":"bad"}',
        encoding="utf-8",
    )
    with EverRunStore(tmp_path / "everrun.db") as store:
        with pytest.raises(ValueError, match="invalid capsule"):
            import_capsule(store, capsule)
        assert store.conn.execute("SELECT count(*) FROM missions").fetchone()[0] == 0


def test_deleted_chain_tail_is_detected(tmp_path: Path) -> None:
    with EverRunStore(tmp_path / "everrun.db") as store:
        store.create_mission(Mission("m1", "tail guard", 2))
        store.append("m1", EventType.WORK_COMPLETED, {"item": "a"})
        store.raw_execute("DROP TRIGGER IF EXISTS events_no_delete")
        store.raw_execute("DELETE FROM events WHERE mission_id='m1' AND sequence=2")
        assert not store.verify_chain("m1").ok
