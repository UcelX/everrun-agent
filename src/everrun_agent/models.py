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
    EVIDENCE_RECORDED = "evidence_recorded"
    REVIEW_CONFIRMED = "review_confirmed"
    HANDOFF_STARTED = "handoff_started"
    HANDOFF_COMPLETED = "handoff_completed"
    ENVIRONMENT_PINNED = "environment_pinned"
    DEPENDENCY_DECLARED = "dependency_declared"


class Origin(StrEnum):
    DETERMINISTIC = "deterministic"
    HUMAN = "human"
    EXTERNAL_AGENT = "external_agent"


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
    origin: Origin = Origin.DETERMINISTIC


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


@dataclass(frozen=True)
class RestoredMission:
    checkpoint: Checkpoint
    state: SemanticState
    replayed_events: int


class RecoveryMode(StrEnum):
    CONTINUE = "continue"
    RECONCILE = "reconcile"
    REPAIR = "repair"
    WAIT = "wait"
    REQUEST_REVIEW = "request_review"
    VERIFIED_COMPLETE = "verified_complete"
    ABORT = "abort"


@dataclass(frozen=True)
class RecoveryDecision:
    mode: RecoveryMode
    safe: bool
    next_safe_action: str
    reasons: tuple[str, ...] = ()
    issued_at: str = ""
    version: int = 1
    digest: str = ""

    def content(self) -> dict[str, Any]:
        return {
            "mode": self.mode.value,
            "safe": self.safe,
            "next_safe_action": self.next_safe_action,
            "reasons": self.reasons,
            "issued_at": self.issued_at,
            "version": self.version,
        }

    def verify(self) -> bool:
        from .crypto import canonical, sha256_text

        return self.digest == sha256_text(canonical(self.content()))

    def replace(self, **changes: Any) -> RecoveryDecision:
        return replace(self, **changes)


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


class ConcurrentWriteError(RuntimeError):
    pass
