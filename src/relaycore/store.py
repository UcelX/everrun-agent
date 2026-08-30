from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType
from typing import Any, Self

from .crypto import canonical, event_digest
from .models import ChainReport, Event, EventType, Mission


class RelayStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=FULL")
        self._schema()

    def _schema(self) -> None:
        self.conn.executescript(
            """CREATE TABLE IF NOT EXISTS missions(mission_id TEXT PRIMARY KEY,goal TEXT NOT NULL,total INTEGER NOT NULL); CREATE TABLE IF NOT EXISTS events(mission_id TEXT NOT NULL,sequence INTEGER NOT NULL,event_type TEXT NOT NULL,payload TEXT NOT NULL,created_at TEXT NOT NULL,previous_hash TEXT,digest TEXT NOT NULL,PRIMARY KEY(mission_id,sequence)); CREATE TABLE IF NOT EXISTS checkpoints(mission_id TEXT NOT NULL,sequence INTEGER NOT NULL,payload TEXT NOT NULL,digest TEXT NOT NULL,PRIMARY KEY(mission_id,sequence)); CREATE TABLE IF NOT EXISTS actions(mission_id TEXT NOT NULL,action_key TEXT NOT NULL,kind TEXT NOT NULL,args TEXT NOT NULL,status TEXT NOT NULL,external_id TEXT,result TEXT,PRIMARY KEY(mission_id,action_key));"""
        )
        self.conn.commit()

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

    def create_mission(self, m: Mission) -> None:
        self.conn.execute("INSERT INTO missions VALUES(?,?,?)", (m.mission_id, m.goal, m.total))
        self.conn.commit()
        self.append(m.mission_id, EventType.MISSION_STARTED, {"goal": m.goal, "total": m.total})

    def get_mission(self, mid: str) -> Mission:
        r = self.conn.execute("SELECT * FROM missions WHERE mission_id=?", (mid,)).fetchone()
        if not r:
            raise KeyError(mid)
        return Mission(r["mission_id"], r["goal"], r["total"])

    def append(self, mid: str, typ: EventType, payload: dict[str, Any]) -> Event:
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            row = self.conn.execute(
                "SELECT sequence,digest FROM events WHERE mission_id=? ORDER BY sequence DESC LIMIT 1",
                (mid,),
            ).fetchone()
            seq = row["sequence"] + 1 if row else 1
            prev = row["digest"] if row else None
            now = datetime.now(UTC).isoformat()
            dig = event_digest(mid, seq, typ.value, payload, now, prev)
            self.conn.execute(
                "INSERT INTO events VALUES(?,?,?,?,?,?,?)",
                (mid, seq, typ.value, canonical(payload), now, prev, dig),
            )
            self.conn.commit()
            return Event(mid, seq, typ, payload, now, prev, dig)
        except Exception:
            self.conn.rollback()
            raise

    def events(self, mid: str) -> list[Event]:
        rows = self.conn.execute(
            "SELECT * FROM events WHERE mission_id=? ORDER BY sequence", (mid,)
        ).fetchall()
        return [
            Event(
                r["mission_id"],
                r["sequence"],
                EventType(r["event_type"]),
                json.loads(r["payload"]),
                r["created_at"],
                r["previous_hash"],
                r["digest"],
            )
            for r in rows
        ]

    def verify_chain(self, mid: str) -> ChainReport:
        prev = None
        trusted = 0
        for e in self.events(mid):
            expected = event_digest(
                e.mission_id, e.sequence, e.event_type.value, e.payload, e.created_at, prev
            )
            if e.previous_hash != prev or e.digest != expected:
                return ChainReport(False, trusted, f"invalid event {e.sequence}")
            trusted = e.sequence
            prev = e.digest
        return ChainReport(True, trusted)

    def raw_execute(self, sql: str, args: tuple[Any, ...] = ()) -> None:
        self.conn.execute(sql, args)
        self.conn.commit()
