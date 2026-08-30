from __future__ import annotations

import json
import sqlite3
from typing import Any

from .crypto import canonical, sha256_text
from .models import ActionClaim, EventType, UncertainAction
from .store import EverRunStore


class ActionLedger:
    def __init__(self, store: EverRunStore, mission_id: str):
        self.store = store
        self.mission_id = mission_id

    def _key(self, kind: str, args: dict[str, Any]) -> str:
        return sha256_text(canonical({"kind": kind, "args": args}))

    def claim(self, kind: str, args: dict[str, Any]) -> ActionClaim:
        key = self._key(kind, args)
        r = self.store.conn.execute(
            "SELECT * FROM actions WHERE mission_id=? AND action_key=?", (self.mission_id, key)
        ).fetchone()
        if r:
            if r["status"] == "completed":
                return ActionClaim(
                    key, False, r["external_id"], json.loads(r["result"]) if r["result"] else None
                )
            raise UncertainAction(f"action {key} may have occurred; reconcile first")
        self.store.conn.execute(
            "INSERT INTO actions VALUES(?,?,?,?,?,?,?)",
            (self.mission_id, key, kind, canonical(args), "started", None, None),
        )
        self.store.conn.commit()
        self.store.append(
            self.mission_id, EventType.ACTION_STARTED, {"key": key, "kind": kind, "args": args}
        )
        return ActionClaim(key, True)

    def complete(
        self, key: str, external_id: str | None = None, result: dict[str, Any] | None = None
    ) -> None:
        cur = self.store.conn.execute(
            "UPDATE actions SET status='completed',external_id=?,result=? WHERE mission_id=? AND action_key=? AND status='started'",
            (external_id, canonical(result or {}), self.mission_id, key),
        )
        if cur.rowcount != 1:
            raise KeyError(key)
        self.store.conn.commit()
        self.store.append(
            self.mission_id,
            EventType.ACTION_COMPLETED,
            {"key": key, "external_id": external_id, "result": result or {}},
        )

    def reconcile(
        self,
        key: str,
        occurred: bool,
        external_id: str | None = None,
        result: dict[str, Any] | None = None,
    ) -> None:
        status = "completed" if occurred else "not_occurred"
        self.store.conn.execute(
            "UPDATE actions SET status=?,external_id=?,result=? WHERE mission_id=? AND action_key=?",
            (status, external_id, canonical(result or {}), self.mission_id, key),
        )
        self.store.conn.commit()
        self.store.append(
            self.mission_id,
            EventType.ACTION_RECONCILED,
            {"key": key, "occurred": occurred, "external_id": external_id},
        )

    def uncertain(self) -> list[sqlite3.Row]:
        return self.store.conn.execute(
            "SELECT action_key FROM actions WHERE mission_id=? AND status='started' ORDER BY rowid",
            (self.mission_id,),
        ).fetchall()
