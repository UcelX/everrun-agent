from __future__ import annotations

from pathlib import Path

import pytest

from everrun_agent import EventType, EverRunStore, Mission, StateProjector
from everrun_agent.environment import EnvironmentSnapshot, validate_environment

from .helpers.tamper import tamper


def test_checkpoint_restore_replays_events_after_checkpoint(tmp_path: Path) -> None:
    with EverRunStore(tmp_path / "everrun.db") as store:
        store.create_mission(Mission("m1", "Recover all work", 3))
        store.append("m1", EventType.WORK_COMPLETED, {"item": "a"})
        saved = store.create_checkpoint("m1", reason="milestone")
        store.append("m1", EventType.WORK_COMPLETED, {"item": "b"})
        restored = store.restore("m1", checkpoint_sequence=saved.sequence)
        assert restored.checkpoint.sequence == saved.sequence
        assert restored.replayed_events == 2  # checkpoint event + work b
        # state is point-in-time AS OF the checkpoint; current_state is present-time.
        assert restored.state.completed == ("a",)
        assert restored.current_state is not None
        assert restored.current_state.completed == ("a", "b")


def test_environment_drift_propagates_to_dependent_facts() -> None:
    old = EnvironmentSnapshot({"dataset": "v3", "repo": "abc"})
    new = EnvironmentSnapshot({"dataset": "v4", "repo": "abc"})
    result = validate_environment(
        old, new, {"finding:f1": ("dataset",), "decision:d1": ("finding:f1",)}
    )
    assert result.changed == ("dataset",)
    assert result.stale == ("finding:f1", "decision:d1")
    assert not result.safe


def test_concurrent_stores_allocate_unique_sequences(tmp_path: Path) -> None:
    import concurrent.futures

    db = tmp_path / "everrun.db"
    with EverRunStore(db) as store:
        store.create_mission(Mission("m1", "Concurrent", 20))

    def append(i: int) -> int:
        with EverRunStore(db) as store:
            return store.append("m1", EventType.WORK_COMPLETED, {"item": str(i)}).sequence

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        sequences = list(pool.map(append, range(20)))
    assert len(set(sequences)) == 20
    with EverRunStore(db) as store:
        assert store.verify_chain("m1").ok
        assert len(StateProjector.project(store.events("m1")).completed) == 20


def test_schema_version_is_migrated_and_rejected_if_newer(tmp_path: Path) -> None:
    db = tmp_path / "everrun.db"
    with EverRunStore(db) as store:
        assert store.schema_version == 2
    tamper(db, "UPDATE metadata SET value='999' WHERE key='schema_version'")
    with pytest.raises(RuntimeError, match="newer schema"):
        EverRunStore(db)
