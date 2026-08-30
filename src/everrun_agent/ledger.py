from __future__ import annotations

import json
import sqlite3
from typing import Any

from .budgets import RetryBudget
from .crypto import canonical, sha256_text
from .models import ActionClaim, EventType, UncertainAction
from .store import EverRunStore


class ActionLedger:
    def __init__(
        self,
        store: EverRunStore,
        mission_id: str,
        budget: RetryBudget | None = None,
    ):
        self.store = store
        self.mission_id = mission_id
        self.budget = budget or RetryBudget()

    def _key(self, kind: str, args: dict[str, Any]) -> str:
        return sha256_text(canonical({"kind": kind, "args": args}))

    def _attempts(self, kind: str) -> int:
        row = self.store.conn.execute(
            "SELECT COUNT(*) FROM actions WHERE mission_id=? AND kind=?",
            (self.mission_id, kind),
        ).fetchone()
        return int(row[0])

    def find(self, kind: str, args: dict[str, Any]) -> ActionClaim | None:
        key = self._key(kind, args)
        row = self.store.conn.execute(
            "SELECT * FROM actions WHERE mission_id=? AND action_key=?",
            (self.mission_id, key),
        ).fetchone()
        if not row:
            return None
        fresh = row["status"] == "started"
        return ActionClaim(
            key,
            fresh,
            row["external_id"],
            json.loads(row["result"]) if row["result"] else None,
        )

    def claim(self, kind: str, args: dict[str, Any]) -> ActionClaim:
        key = self._key(kind, args)
        try:
            with self.store.transaction():
                row = self.store.conn.execute(
                    "SELECT * FROM actions WHERE mission_id=? AND action_key=?",
                    (self.mission_id, key),
                ).fetchone()
                if row:
                    if row["status"] == "completed":
                        return ActionClaim(
                            key,
                            False,
                            row["external_id"],
                            json.loads(row["result"]) if row["result"] else None,
                        )
                    if row["status"] == "started":
                        raise UncertainAction(f"action {key} may have occurred; reconcile first")
                self.budget.check(kind, self._attempts(kind))
                self.store.conn.execute(
                    "INSERT OR REPLACE INTO actions VALUES(?,?,?,?,?,?,?)",
                    (self.mission_id, key, kind, canonical(args), "started", None, None),
                )
                self.store._insert_event(
                    self.mission_id,
                    EventType.ACTION_STARTED,
                    {"key": key, "kind": kind, "args": args},
                )
            return ActionClaim(key, True)
        except sqlite3.IntegrityError as exc:
            raise UncertainAction(f"concurrent action claim for {key}") from exc

    def complete(
        self,
        key: str,
        external_id: str | None = None,
        result: dict[str, Any] | None = None,
    ) -> None:
        with self.store.transaction():
            cursor = self.store.conn.execute(
                "UPDATE actions SET status='completed',external_id=?,result=? WHERE mission_id=? AND action_key=? AND status='started'",
                (external_id, canonical(result or {}), self.mission_id, key),
            )
            if cursor.rowcount != 1:
                raise KeyError(key)
            self.store._insert_event(
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
        with self.store.transaction():
            cursor = self.store.conn.execute(
                "UPDATE actions SET status=?,external_id=?,result=? WHERE mission_id=? AND action_key=? AND status='started'",
                (status, external_id, canonical(result or {}), self.mission_id, key),
            )
            if cursor.rowcount != 1:
                raise KeyError(key)
            self.store._insert_event(
                self.mission_id,
                EventType.ACTION_RECONCILED,
                {"key": key, "occurred": occurred, "external_id": external_id},
            )

    def uncertain(self) -> list[sqlite3.Row]:
        return self.store.conn.execute(
            "SELECT action_key FROM actions WHERE mission_id=? AND status='started' ORDER BY rowid",
            (self.mission_id,),
        ).fetchall()

    def uncertain_details(self) -> list[dict[str, Any]]:
        rows = self.store.conn.execute(
            "SELECT action_key,kind,args FROM actions WHERE mission_id=? AND status='started' ORDER BY rowid",
            (self.mission_id,),
        ).fetchall()
        return [
            {
                "action_key": row["action_key"],
                "kind": row["kind"],
                "args": json.loads(row["args"]),
            }
            for row in rows
        ]
