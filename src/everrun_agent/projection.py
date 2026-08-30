from .models import Decision, Event, EventType, SemanticState


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
