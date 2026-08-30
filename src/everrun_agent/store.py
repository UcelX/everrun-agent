from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType
from typing import Any, Self

from .crypto import canonical, event_digest
from .environment import EnvironmentSnapshot
from .models import (
    ChainReport,
    Checkpoint,
    ConcurrentWriteError,
    Event,
    EventType,
    Mission,
    Origin,
    RestoredMission,
)

SCHEMA_VERSION = 2
MISSION_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
MAX_GOAL_CHARS = 8192
MAX_TOTAL = 10_000_000
MAX_PAYLOAD_CHARS = 65536
MAX_ITEM_CHARS = 4096


def validate_mission_id(mission_id: str) -> str:
    if not MISSION_ID_PATTERN.match(mission_id or ""):
        raise ValueError(
            "mission_id must be 1-128 chars of letters, digits, dot, underscore, or hyphen"
        )
    return mission_id


class EverRunStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.conn = sqlite3.connect(self.path, timeout=30)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=FULL")
        self.conn.execute("PRAGMA busy_timeout=30000")
        self._schema()

    def _schema(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS missions(mission_id TEXT PRIMARY KEY,goal TEXT NOT NULL,total INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS events(mission_id TEXT NOT NULL,sequence INTEGER NOT NULL,event_type TEXT NOT NULL,payload TEXT NOT NULL,created_at TEXT NOT NULL,previous_hash TEXT,digest TEXT NOT NULL,origin TEXT NOT NULL DEFAULT 'deterministic',PRIMARY KEY(mission_id,sequence));
            CREATE TABLE IF NOT EXISTS chain_heads(mission_id TEXT PRIMARY KEY,event_count INTEGER NOT NULL,head_digest TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS checkpoints(mission_id TEXT NOT NULL,sequence INTEGER NOT NULL,payload TEXT NOT NULL,digest TEXT NOT NULL,reason TEXT NOT NULL DEFAULT 'manual',PRIMARY KEY(mission_id,sequence));
            CREATE TABLE IF NOT EXISTS actions(mission_id TEXT NOT NULL,action_key TEXT NOT NULL,kind TEXT NOT NULL,args TEXT NOT NULL,status TEXT NOT NULL,external_id TEXT,result TEXT,PRIMARY KEY(mission_id,action_key));
            CREATE TRIGGER IF NOT EXISTS events_no_update BEFORE UPDATE ON events BEGIN SELECT RAISE(ABORT,'events are append-only'); END;
            CREATE TRIGGER IF NOT EXISTS events_no_delete BEFORE DELETE ON events BEGIN SELECT RAISE(ABORT,'events are append-only'); END;
            CREATE TRIGGER IF NOT EXISTS checkpoints_no_update BEFORE UPDATE ON checkpoints BEGIN SELECT RAISE(ABORT,'checkpoints are immutable'); END;
            CREATE TRIGGER IF NOT EXISTS checkpoints_no_delete BEFORE DELETE ON checkpoints BEGIN SELECT RAISE(ABORT,'checkpoints are immutable'); END;
            """
        )
        columns = {row[1] for row in self.conn.execute("PRAGMA table_info(checkpoints)")}
        if "reason" not in columns:
            self.conn.execute(
                "ALTER TABLE checkpoints ADD COLUMN reason TEXT NOT NULL DEFAULT 'manual'"
            )
        row = self.conn.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone()
        if row and int(row[0]) > SCHEMA_VERSION:
            raise RuntimeError(f"database uses newer schema {row[0]}")
        self.conn.execute(
            "INSERT INTO metadata(key,value) VALUES('schema_version',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (str(SCHEMA_VERSION),),
        )
        # Backfill anchors for databases created before schema v2.
        for row in self.conn.execute(
            "SELECT mission_id,COUNT(*) AS n FROM events GROUP BY mission_id"
        ):
            head = self.conn.execute(
                "SELECT digest FROM events WHERE mission_id=? ORDER BY sequence DESC LIMIT 1",
                (row[0],),
            ).fetchone()
            if head:
                self.conn.execute(
                    "INSERT OR IGNORE INTO chain_heads VALUES(?,?,?)", (row[0], row[1], head[0])
                )
        self.conn.commit()

    @property
    def schema_version(self) -> int:
        row = self.conn.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone()
        if not row:
            raise RuntimeError("schema version missing")
        return int(row[0])

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        self.conn.close()

    @contextmanager
    def transaction(self) -> Iterator[None]:
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            yield
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

    def _insert_event(
        self,
        mid: str,
        typ: EventType,
        payload: dict[str, Any],
        origin: Origin = Origin.DETERMINISTIC,
    ) -> Event:
        row = self.conn.execute(
            "SELECT sequence,digest FROM events WHERE mission_id=? ORDER BY sequence DESC LIMIT 1",
            (mid,),
        ).fetchone()
        seq = row["sequence"] + 1 if row else 1
        prev = row["digest"] if row else None
        now = datetime.now(UTC).isoformat()
        digest = event_digest(mid, seq, typ.value, payload, now, prev, origin.value)
        self.conn.execute(
            "INSERT INTO events(mission_id,sequence,event_type,payload,created_at,previous_hash,digest,origin) VALUES(?,?,?,?,?,?,?,?)",
            (mid, seq, typ.value, canonical(payload), now, prev, digest, origin.value),
        )
        self.conn.execute(
            "INSERT INTO chain_heads VALUES(?,?,?) ON CONFLICT(mission_id) DO UPDATE SET event_count=excluded.event_count,head_digest=excluded.head_digest",
            (mid, seq, digest),
        )
        return Event(mid, seq, typ, payload, now, prev, digest, origin)

    def create_mission(self, mission: Mission) -> None:
        validate_mission_id(mission.mission_id)
        if not mission.goal.strip():
            raise ValueError("mission goal must not be empty")
        if len(mission.goal) > MAX_GOAL_CHARS:
            raise ValueError(f"mission goal exceeds {MAX_GOAL_CHARS} characters")
        if mission.total < 0 or mission.total > MAX_TOTAL:
            raise ValueError(f"mission total must be between 0 and {MAX_TOTAL}")
        with self.transaction():
            self.conn.execute(
                "INSERT INTO missions VALUES(?,?,?)",
                (mission.mission_id, mission.goal, mission.total),
            )
            self._insert_event(
                mission.mission_id,
                EventType.MISSION_STARTED,
                {"goal": mission.goal, "total": mission.total},
            )

    def get_mission(self, mid: str) -> Mission:
        row = self.conn.execute("SELECT * FROM missions WHERE mission_id=?", (mid,)).fetchone()
        if not row:
            raise KeyError(mid)
        return Mission(row["mission_id"], row["goal"], row["total"])

    def append(
        self,
        mid: str,
        typ: EventType,
        payload: dict[str, Any],
        origin: Origin = Origin.DETERMINISTIC,
    ) -> Event:
        validate_mission_id(mid)
        if len(canonical(payload)) > MAX_PAYLOAD_CHARS:
            raise ValueError(f"event payload exceeds {MAX_PAYLOAD_CHARS} characters")
        try:
            with self.transaction():
                return self._insert_event(mid, typ, payload, origin)
        except sqlite3.IntegrityError as exc:
            raise ConcurrentWriteError(str(exc)) from exc

    def events(self, mid: str) -> list[Event]:
        rows = self.conn.execute(
            "SELECT * FROM events WHERE mission_id=? ORDER BY sequence", (mid,)
        ).fetchall()
        return [
            Event(
                row["mission_id"],
                row["sequence"],
                EventType(row["event_type"]),
                json.loads(row["payload"]),
                row["created_at"],
                row["previous_hash"],
                row["digest"],
                Origin(row["origin"]),
            )
            for row in rows
        ]

    def verify_chain(self, mid: str) -> ChainReport:
        events = self.events(mid)
        head = self.conn.execute(
            "SELECT event_count,head_digest FROM chain_heads WHERE mission_id=?", (mid,)
        ).fetchone()
        if (
            not events
            or events[0].sequence != 1
            or events[0].event_type is not EventType.MISSION_STARTED
        ):
            return ChainReport(False, 0, "missing mission start")
        previous = None
        trusted = 0
        for expected_sequence, event in enumerate(events, start=1):
            expected = event_digest(
                event.mission_id,
                event.sequence,
                event.event_type.value,
                event.payload,
                event.created_at,
                previous,
                event.origin.value,
            )
            if (
                event.sequence != expected_sequence
                or event.previous_hash != previous
                or event.digest != expected
            ):
                return ChainReport(False, trusted, f"invalid event {event.sequence}")
            trusted = event.sequence
            previous = event.digest
        if not head or head["event_count"] != len(events) or head["head_digest"] != previous:
            return ChainReport(False, trusted, "chain head mismatch or truncated tail")
        return ChainReport(True, trusted)

    def create_checkpoint(self, mission_id: str, reason: str = "manual") -> Checkpoint:
        from .checkpoint import checkpoint

        return checkpoint(self, mission_id, reason=reason)

    def restore(self, mission_id: str, checkpoint_sequence: int | None = None) -> RestoredMission:
        from .projection import StateProjector

        query = "SELECT * FROM checkpoints WHERE mission_id=? ORDER BY sequence DESC LIMIT 1"
        args: tuple[Any, ...] = (mission_id,)
        if checkpoint_sequence is not None:
            query = "SELECT * FROM checkpoints WHERE mission_id=? AND sequence=?"
            args = (mission_id, checkpoint_sequence)
        row = self.conn.execute(query, args).fetchone()
        if not row:
            raise KeyError(f"checkpoint not found: {mission_id}")
        saved = Checkpoint(row["mission_id"], row["sequence"], row["payload"], row["digest"])
        if not saved.verify():
            raise RuntimeError("checkpoint integrity failure")
        all_events = self.events(mission_id)
        replay = [event for event in all_events if event.sequence > saved.sequence]
        return RestoredMission(saved, StateProjector.project(all_events), len(replay))

    def raw_execute(self, sql: str, args: tuple[Any, ...] = ()) -> None:
        self.conn.execute(sql, args)
        self.conn.commit()

    def append_work(
        self, mission_id: str, item: str, origin: Origin = Origin.DETERMINISTIC
    ) -> Event:
        if not item or len(item) > MAX_ITEM_CHARS:
            raise ValueError(f"work item must be 1-{MAX_ITEM_CHARS} characters")
        return self.append(mission_id, EventType.WORK_COMPLETED, {"item": item}, origin=origin)

    def append_decision(
        self,
        mission_id: str,
        decision_id: str,
        text: str,
        origin: Origin = Origin.DETERMINISTIC,
    ) -> Event:
        return self.append(
            mission_id,
            EventType.DECISION_RECORDED,
            {"id": decision_id, "text": text},
            origin=origin,
        )

    def current_agent(self, mission_id: str) -> str | None:
        for event in reversed(self.events(mission_id)):
            if event.event_type is EventType.HANDOFF_COMPLETED:
                agent = event.payload.get("to_agent")
                return str(agent) if agent is not None else None
        return None

    def pin_environment(self, mission_id: str, snapshot: EnvironmentSnapshot) -> Event:
        return self.append(
            mission_id, EventType.ENVIRONMENT_PINNED, {"values": dict(snapshot.values)}
        )

    def pinned_environment(self, mission_id: str) -> EnvironmentSnapshot | None:
        for event in reversed(self.events(mission_id)):
            if event.event_type is EventType.ENVIRONMENT_PINNED:
                values = event.payload.get("values") or {}
                return EnvironmentSnapshot({str(k): str(v) for k, v in values.items()})
        return None

    def declare_dependency(
        self, mission_id: str, component: str, requires: tuple[str, ...]
    ) -> Event:
        return self.append(
            mission_id,
            EventType.DEPENDENCY_DECLARED,
            {"component": component, "requires": list(requires)},
        )

    def dependency_graph(self, mission_id: str) -> dict[str, tuple[str, ...]]:
        graph: dict[str, tuple[str, ...]] = {}
        for event in self.events(mission_id):
            if event.event_type is EventType.DEPENDENCY_DECLARED:
                component = str(event.payload["component"])
                graph[component] = tuple(str(item) for item in event.payload.get("requires", ()))
        return graph

    def complete_mission(self, mission_id: str, contract: object | None = None) -> Event:
        """Explicit terminal transition that fails closed on unresolved work."""

        from .contracts import SuccessContract, evaluate_contract
        from .ledger import ActionLedger
        from .projection import StateProjector

        if not self.verify_chain(mission_id).ok:
            raise ValueError("cannot close a mission whose event chain is not verified")
        pending = ActionLedger(self, mission_id).uncertain_details()
        if pending:
            raise ValueError(f"cannot close mission with {len(pending)} unresolved side effect(s)")
        events = self.events(mission_id)
        state = StateProjector.project(events)
        if state.total and len(state.completed) < state.total:
            raise ValueError(
                f"cannot close mission: progress {len(state.completed)}/{state.total} incomplete"
            )
        if isinstance(contract, SuccessContract):
            result = evaluate_contract(contract, events)
            if not result.satisfied:
                raise ValueError(f"success contract unmet: {', '.join(result.missing)}")
        return self.append(
            mission_id,
            EventType.MISSION_COMPLETED,
            {"completed": len(state.completed), "total": state.total},
        )
