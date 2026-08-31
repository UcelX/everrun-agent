from .models import Decision, Event, EventType, Origin, SemanticState


def unconfirmed_external_progress(events: list[Event]) -> bool:
    """True when agent-reported progress exists that no LATER confirmation covers.

    H4: a single confirmation used to whitelist every future agent claim, because
    the check was ``any(REVIEW_CONFIRMED)`` over all history. Confirmation must
    only vouch for progress recorded before it.
    """

    last_external = 0
    last_confirmed = 0
    for event in events:
        if event.event_type is EventType.WORK_COMPLETED and event.origin is Origin.EXTERNAL_AGENT:
            last_external = max(last_external, event.sequence)
        elif event.event_type is EventType.REVIEW_CONFIRMED:
            last_confirmed = max(last_confirmed, event.sequence)
    return last_external > last_confirmed


class StateProjector:
    @staticmethod
    def project(events: list[Event]) -> SemanticState:
        if not events or events[0].event_type is not EventType.MISSION_STARTED:
            raise ValueError("mission start event required")
        p = events[0].payload
        completed = []
        failed = []
        decisions = []
        findings = []
        for e in events[1:]:
            if e.event_type is EventType.WORK_COMPLETED and e.payload["item"] not in completed:
                completed.append(e.payload["item"])
            elif e.event_type is EventType.WORK_FAILED and e.payload["item"] not in failed:
                failed.append(e.payload["item"])
            elif e.event_type is EventType.DECISION_RECORDED:
                decisions.append(Decision(e.payload["id"], e.payload["text"]))
            elif e.event_type is EventType.FINDING_RECORDED:
                findings.append(e.payload["text"])
        return SemanticState(
            events[0].mission_id,
            p["goal"],
            p.get("total", 0),
            tuple(completed),
            tuple(failed),
            tuple(decisions),
            tuple(findings),
        )
