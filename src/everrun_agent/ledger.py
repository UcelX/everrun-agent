from __future__ import annotations

import json
import sqlite3
from typing import Any

from .budgets import RetryBudget
from .crypto import canonical, sha256_text
from .models import ActionClaim, ActionStatus, EventType, UncertainAction
from .store import EverRunStore


class ActionLedger:
    """Idempotency ledger for external side effects.

    Three states matter after a crash:

    - ``completed``  the effect provably happened, never fire again
    - ``started``    the outcome is UNKNOWN, never fire again until reconciled
    - ``not_occurred`` a probe proved it did not happen, so retrying is correct
    """

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

    def _attempts_for_key(self, key: str) -> int:
        row = self.store.conn.execute(
            "SELECT attempts FROM actions WHERE mission_id=? AND action_key=?",
            (self.mission_id, key),
        ).fetchone()
        return int(row["attempts"]) if row and row["attempts"] is not None else 0

    def attempts(self, kind: str, args: dict[str, Any]) -> int:
        return self._attempts_for_key(self._key(kind, args))

    def _distinct_actions(self, kind: str) -> int:
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
        return ActionClaim(
            key,
            fresh=False,
            external_id=row["external_id"],
            result=json.loads(row["result"]) if row["result"] else None,
            status=ActionStatus(row["status"]),
        )

    def claim(self, kind: str, args: dict[str, Any]) -> ActionClaim:
        key = self._key(kind, args)
        try:
            with self.store.transaction():
                row = self.store.conn.execute(
                    "SELECT * FROM actions WHERE mission_id=? AND action_key=?",
                    (self.mission_id, key),
                ).fetchone()
                attempts = 0
                if row:
                    status = ActionStatus(row["status"])
                    attempts = int(row["attempts"] or 0)
                    if status is ActionStatus.COMPLETED:
                        return ActionClaim(
                            key,
                            fresh=False,
                            external_id=row["external_id"],
                            result=json.loads(row["result"]) if row["result"] else None,
                            status=status,
                        )
                    if status is ActionStatus.STARTED:
                        raise UncertainAction(f"action {key} may have occurred; reconcile first")
                self.budget.check(
                    kind,
                    attempts,
                    distinct_actions=self._distinct_actions(kind) - (1 if row else 0),
                )
                self.store.conn.execute(
                    "INSERT INTO actions(mission_id,action_key,kind,args,status,external_id,result,attempts) "
                    "VALUES(?,?,?,?,?,?,?,?) "
                    "ON CONFLICT(mission_id,action_key) DO UPDATE SET "
                    "status='started',external_id=NULL,result=NULL,attempts=attempts+1",
                    (
                        self.mission_id,
                        key,
                        kind,
                        canonical(args),
                        ActionStatus.STARTED.value,
                        None,
                        None,
                        1,
                    ),
                )
                self.store._insert_event(
                    self.mission_id,
                    EventType.ACTION_STARTED,
                    {"key": key, "kind": kind, "args": args, "attempt": attempts + 1},
                )
            return ActionClaim(key, fresh=True, status=ActionStatus.STARTED)
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
                "UPDATE actions SET status='completed',external_id=?,result=? "
                "WHERE mission_id=? AND action_key=? AND status='started'",
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
        status = ActionStatus.COMPLETED if occurred else ActionStatus.NOT_OCCURRED
        with self.store.transaction():
            cursor = self.store.conn.execute(
                "UPDATE actions SET status=?,external_id=?,result=? "
                "WHERE mission_id=? AND action_key=? AND status='started'",
                (status.value, external_id, canonical(result or {}), self.mission_id, key),
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
            "SELECT action_key,kind,args,attempts FROM actions "
            "WHERE mission_id=? AND status='started' ORDER BY rowid",
            (self.mission_id,),
        ).fetchall()
        return [
            {
                "action_key": row["action_key"],
                "kind": row["kind"],
                "args": json.loads(row["args"]),
                "attempts": int(row["attempts"] or 0),
            }
            for row in rows
        ]
