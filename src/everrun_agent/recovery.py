from __future__ import annotations

from datetime import UTC, datetime

from .contracts import SuccessContract, evaluate_contract
from .crypto import canonical, sha256_text
from .environment import EnvironmentSnapshot, validate_environment
from .ledger import ActionLedger
from .models import EventType, RecoveryDecision, RecoveryMode
from .projection import StateProjector, unconfirmed_external_progress
from .store import EverRunStore

SEVERITY: dict[RecoveryMode, int] = {
    RecoveryMode.VERIFIED_COMPLETE: 0,
    RecoveryMode.CONTINUE: 1,
    RecoveryMode.WAIT: 2,
    RecoveryMode.REPAIR: 3,
    RecoveryMode.REQUEST_REVIEW: 4,
    RecoveryMode.RECONCILE: 5,
    RecoveryMode.ABORT: 6,
}

SAFE_MODES = frozenset({RecoveryMode.CONTINUE, RecoveryMode.VERIFIED_COMPLETE})


def _seal(
    mode: RecoveryMode,
    next_action: str,
    reasons: tuple[str, ...],
) -> RecoveryDecision:
    issued_at = datetime.now(UTC).isoformat()
    draft = RecoveryDecision(mode, mode in SAFE_MODES, next_action, reasons, issued_at, 1, "")
    return draft.replace(digest=sha256_text(canonical(draft.content())))


def recover(
    store: EverRunStore,
    mission_id: str,
    current_environment: EnvironmentSnapshot | None = None,
    contract: SuccessContract | None = None,
) -> RecoveryDecision:
    """Reduce every signal to one sealed contract naming a single next action.

    The most cautious applicable signal always wins, so evaluation order can
    never turn an unsafe situation into a safe verdict.
    """

    chain = store.verify_chain(mission_id)
    if not chain.ok:
        return _seal(RecoveryMode.ABORT, "repair_event_chain", (chain.error or "corrupt chain",))

    events = store.events(mission_id)
    state = StateProjector.project(events)
    ledger = ActionLedger(store, mission_id)
    candidates: list[tuple[RecoveryMode, str, str]] = []

    uncertain = ledger.uncertain_details()
    if uncertain:
        candidates.append(
            (
                RecoveryMode.RECONCILE,
                f"reconcile:{uncertain[0]['action_key']}",
                f"{len(uncertain)} external effect(s) have unknown outcomes",
            )
        )

    if unconfirmed_external_progress(events):
        candidates.append(
            (
                RecoveryMode.REQUEST_REVIEW,
                "confirm_progress",
                "external agent progress is not self-certifying",
            )
        )

    pinned = store.pinned_environment(mission_id)
    if pinned is not None and current_environment is not None:
        outcome = validate_environment(
            pinned, current_environment, store.dependency_graph(mission_id)
        )
        if not outcome.safe:
            first = outcome.changed[0] if outcome.changed else outcome.stale[0]
            detail = ", ".join(outcome.changed) or ", ".join(outcome.stale)
            candidates.append(
                (
                    RecoveryMode.REPAIR,
                    f"revalidate:{first}",
                    f"environment drifted: {detail}",
                )
            )

    terminal = any(event.event_type is EventType.MISSION_COMPLETED for event in events)
    if terminal:
        if contract is not None:
            result = evaluate_contract(contract, events)
            if not result.satisfied:
                candidates.append(
                    (
                        RecoveryMode.REPAIR,
                        f"prove:{result.missing[0]}",
                        f"success contract unmet: {', '.join(result.missing)}",
                    )
                )
            else:
                candidates.append(
                    (
                        RecoveryMode.VERIFIED_COMPLETE,
                        "none",
                        "terminal transition and contract proven",
                    )
                )
        else:
            candidates.append(
                (RecoveryMode.VERIFIED_COMPLETE, "none", "explicit terminal transition recorded")
            )
    elif state.total and len(state.completed) >= state.total:
        candidates.append(
            (
                RecoveryMode.CONTINUE,
                "close_mission",
                "progress target reached; close the mission explicitly",
            )
        )
    else:
        candidates.append(
            (RecoveryMode.CONTINUE, "continue_work", "verified progress may continue")
        )

    winner = max(candidates, key=lambda item: SEVERITY[item[0]])
    reasons = tuple(
        reason for _, _, reason in sorted(candidates, key=lambda item: -SEVERITY[item[0]])
    )
    return _seal(winner[0], winner[1], reasons)
