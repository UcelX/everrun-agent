from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, TypeVar

from .ledger import ActionLedger
from .models import ActionClaim, ActionStatus

T = TypeVar("T")


class UnclaimedSideEffect(RuntimeError):
    """Raised when require_claim is set but no ledger claim exists."""


class UncertainSideEffect(RuntimeError):
    """Raised when a prior attempt may already have taken effect.

    This is the guard that makes the product's central promise true: after a
    crash between firing and recording, the effect is UNKNOWN, so the gate
    refuses to fire it again until a reconciler checks reality.
    """


@dataclass(frozen=True)
class GateResult:
    claim: ActionClaim
    performed: bool
    external_id: str | None = None


def protected_call(
    ledger: ActionLedger,
    kind: str,
    args: dict[str, Any],
    effect: Callable[[], T],
    require_claim: bool = False,
    external_id: str | None = None,
) -> GateResult:
    """Claim-before-fire with mandatory reconciliation of unknown outcomes."""

    existing = ledger.find(kind, args)
    if require_claim and existing is None:
        raise UnclaimedSideEffect(
            f"{kind} has no live claim; call ledger.claim({kind!r}, ...) before firing it"
        )

    if existing is not None:
        if existing.status is ActionStatus.COMPLETED:
            return GateResult(existing, False, existing.external_id)
        if existing.status is ActionStatus.STARTED:
            raise UncertainSideEffect(
                f"{kind} may already have taken effect (action {existing.key}); "
                "reconcile it against reality before firing again"
            )
        # ActionStatus.NOT_OCCURRED: a probe proved it did not happen, so retry.

    claim = ledger.claim(kind, args)
    if not claim.fresh:
        return GateResult(claim, False, claim.external_id)
    result = effect()
    resolved = (
        external_id if external_id is not None else (result if isinstance(result, str) else None)
    )
    ledger.complete(claim.key, external_id=resolved, result={"returned": bool(result)})
    return GateResult(claim, True, resolved)
