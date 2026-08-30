from .ledger import ActionLedger
from .models import RecoveryDecision, RecoveryMode
from .projection import StateProjector
from .store import EverRunStore


def recover(store: EverRunStore, mission_id: str) -> RecoveryDecision:
    report = store.verify_chain(mission_id)
    if not report.ok:
        return RecoveryDecision(
            RecoveryMode.ABORT, False, "repair_event_chain", (report.error or "corrupt chain",)
        )
    uncertain = ActionLedger(store, mission_id).uncertain()
    if uncertain:
        return RecoveryDecision(
            RecoveryMode.RECONCILE,
            False,
            f"reconcile:{uncertain[0]['action_key']}",
            (f"{len(uncertain)} uncertain action(s)",),
        )
    state = StateProjector.project(store.events(mission_id))
    if state.total and len(state.completed) >= state.total:
        return RecoveryDecision(RecoveryMode.VERIFIED_COMPLETE, True, "none", ("goal reached",))
    return RecoveryDecision(RecoveryMode.CONTINUE, True, "continue_work", ())
