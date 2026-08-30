from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, TypeVar

from .ledger import ActionLedger
from .models import ActionClaim

T = TypeVar("T")


class UnclaimedSideEffect(RuntimeError):
    pass


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
    """Claim-before-fire. An effect never runs without a live ledger claim."""

    existing = ledger.find(kind, args)
    if require_claim and existing is None:
        raise UnclaimedSideEffect(
            f"{kind} has no live claim; call ledger.claim({kind!r}, ...) before firing it"
        )
    claim = existing or ledger.claim(kind, args)
    if not claim.fresh:
        return GateResult(claim, False, claim.external_id)
    result = effect()
    resolved = (
        external_id if external_id is not None else (result if isinstance(result, str) else None)
    )
    ledger.complete(claim.key, external_id=resolved, result={"returned": bool(result)})
    return GateResult(claim, True, resolved)
