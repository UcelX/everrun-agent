from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from .models import ChainReport, Checkpoint, Event, EventType, Mission, Origin, RestoredMission


@runtime_checkable
class StorageBackend(Protocol):
    """Contract every EverRun storage backend must satisfy.

    SQLite is the shipped implementation. A PostgreSQL backend can be added
    later without touching the kernel as long as it honours this contract:
    append-only events, atomic sequencing, immutable checkpoints, and
    anchor-verified chains.
    """

    def create_mission(self, mission: Mission) -> None: ...

    def get_mission(self, mid: str) -> Mission: ...

    def append(
        self,
        mid: str,
        typ: EventType,
        payload: dict[str, Any],
        origin: Origin = Origin.DETERMINISTIC,
    ) -> Event: ...

    def events(self, mid: str) -> list[Event]: ...

    def verify_chain(self, mid: str) -> ChainReport: ...

    def create_checkpoint(self, mission_id: str, reason: str = "manual") -> Checkpoint: ...

    def restore(
        self, mission_id: str, checkpoint_sequence: int | None = None
    ) -> RestoredMission: ...
