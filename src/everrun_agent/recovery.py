from __future__ import annotations

from datetime import UTC, datetime

from .crypto import canonical, sha256_text
from .ledger import ActionLedger
from .models import EventType, Origin, RecoveryDecision, RecoveryMode
from .projection import StateProjector
from .store import EverRunStore


def _sealed(
    mode: RecoveryMode,
    safe: bool,
    next_action: str,
    reasons: tuple[str, ...],
) -> RecoveryDecision:
    issued_at = datetime.now(UTC).isoformat()
    draft = RecoveryDecision(mode, safe, next_action, reasons, issued_at, 1, "")
    return draft.replace(digest=sha256_text(canonical(draft.content())))


def recover(store: EverRunStore, mission_id: str) -> RecoveryDecision:
    report = store.verify_chain(mission_id)
    if not report.ok:
        return _sealed(
            RecoveryMode.ABORT,
            False,
            "repair_event_chain",
            (report.error or "corrupt chain",),
        )
    uncertain = ActionLedger(store, mission_id).uncertain()
    if uncertain:
        return _sealed(
            RecoveryMode.RECONCILE,
            False,
            f"reconcile:{uncertain[0]['action_key']}",
            (f"{len(uncertain)} uncertain action(s)",),
        )
    events = store.events(mission_id)
    external_progress = any(
        event.event_type is EventType.WORK_COMPLETED and event.origin is Origin.EXTERNAL_AGENT
        for event in events
    )
    confirmed = any(event.event_type is EventType.REVIEW_CONFIRMED for event in events)
    if external_progress and not confirmed:
        return _sealed(
            RecoveryMode.REQUEST_REVIEW,
            False,
            "confirm_progress",
            ("external agent progress is not self-certifying",),
        )
    state = StateProjector.project(events)
    if state.total and len(state.completed) >= state.total:
        return _sealed(
            RecoveryMode.VERIFIED_COMPLETE,
            True,
            "none",
            ("goal reached from trusted progress",),
        )
    return _sealed(RecoveryMode.CONTINUE, True, "continue_work", ())
