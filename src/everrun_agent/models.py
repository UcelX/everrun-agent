from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Any


class EventType(StrEnum):
    MISSION_STARTED = "mission_started"
    WORK_COMPLETED = "work_completed"
    WORK_FAILED = "work_failed"
    DECISION_RECORDED = "decision_recorded"
    FINDING_RECORDED = "finding_recorded"
    CHECKPOINT_CREATED = "checkpoint_created"
    ACTION_STARTED = "action_started"
    ACTION_COMPLETED = "action_completed"
    ACTION_RECONCILED = "action_reconciled"
    MISSION_COMPLETED = "mission_completed"


@dataclass(frozen=True)
class Mission:
    mission_id: str
    goal: str
    total: int = 0


@dataclass(frozen=True)
class Event:
    mission_id: str
    sequence: int
    event_type: EventType
    payload: dict[str, Any]
    created_at: str
    previous_hash: str | None
    digest: str


@dataclass(frozen=True)
class Decision:
    decision_id: str
    text: str


@dataclass(frozen=True)
class SemanticState:
    mission_id: str
    goal: str
    total: int
    completed: tuple[str, ...] = ()
    failed: tuple[str, ...] = ()
    decisions: tuple[Decision, ...] = ()
    findings: tuple[str, ...] = ()


@dataclass(frozen=True)
class ChainReport:
    ok: bool
    trusted_through: int
    error: str | None = None


@dataclass(frozen=True)
class Checkpoint:
    mission_id: str
    sequence: int
    payload: str
    digest: str

    def verify(self) -> bool:
        from .crypto import sha256_text

        return sha256_text(self.payload) == self.digest

    def replace_payload(self, payload: str) -> Checkpoint:
        return replace(self, payload=payload)


class RecoveryMode(StrEnum):
    CONTINUE = "continue"
    RECONCILE = "reconcile"
    REPAIR = "repair"
    VERIFIED_COMPLETE = "verified_complete"
    ABORT = "abort"


@dataclass(frozen=True)
class RecoveryDecision:
    mode: RecoveryMode
    safe: bool
    next_safe_action: str
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class ActionClaim:
    key: str
    fresh: bool
    external_id: str | None = None
    result: dict[str, Any] | None = None


class HashChainError(RuntimeError):
    pass


class UncertainAction(RuntimeError):
    pass
