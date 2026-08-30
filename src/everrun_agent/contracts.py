from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .models import Event, EventType


@dataclass(frozen=True)
class ContractClause:
    evidence_id: str
    expected: Any


@dataclass(frozen=True)
class SuccessContract:
    clauses: tuple[ContractClause, ...]


@dataclass(frozen=True)
class ContractResult:
    satisfied: bool
    proven: tuple[str, ...]
    missing: tuple[str, ...]


def evaluate_contract(contract: SuccessContract, events: list[Event]) -> ContractResult:
    evidence = {
        e.payload.get("evidence_id"): e.payload.get("ok")
        for e in events
        if e.event_type is EventType.EVIDENCE_RECORDED
    }
    proven = tuple(
        c.evidence_id for c in contract.clauses if evidence.get(c.evidence_id) == c.expected
    )
    missing = tuple(c.evidence_id for c in contract.clauses if c.evidence_id not in proven)
    return ContractResult(not missing, proven, missing)
