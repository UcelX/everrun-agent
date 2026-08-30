from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime

from .crypto import canonical, sha256_text
from .ledger import ActionLedger
from .models import EventType, Origin, RecoveryMode
from .projection import StateProjector
from .recovery import recover
from .store import EverRunStore

CHARS_PER_TOKEN = 4


class HandoffRefused(RuntimeError):
    pass


@dataclass(frozen=True)
class AgentProfile:
    name: str
    context_tokens: int = 16000
    capabilities: tuple[str, ...] = ()


@dataclass(frozen=True)
class HandoffCapsule:
    mission_id: str
    from_agent: str
    to_agent: str
    next_safe_action: str
    briefing: str
    issued_at: str
    digest: str = ""

    def content(self) -> dict[str, object]:
        return {
            "mission_id": self.mission_id,
            "from_agent": self.from_agent,
            "to_agent": self.to_agent,
            "next_safe_action": self.next_safe_action,
            "briefing": self.briefing,
            "issued_at": self.issued_at,
        }

    def verify(self) -> bool:
        return self.digest == sha256_text(canonical(self.content()))


def compile_briefing(store: EverRunStore, mission_id: str, profile: AgentProfile) -> str:
    state = StateProjector.project(store.events(mission_id))
    decision = recover(store, mission_id)
    ledger = ActionLedger(store, mission_id)
    uncertain = [row["action_key"] for row in ledger.uncertain_details()]
    critical = [
        f"GOAL\n  {state.goal}",
        f"VERIFIED PROGRESS\n  {len(state.completed)}/{state.total} completed, {len(state.failed)} failed",
        f"UNCERTAIN EFFECTS\n  {', '.join(uncertain) if uncertain else 'none'}",
        f"NEXT SAFE ACTION\n  {decision.next_safe_action}",
        "FORBIDDEN\n  repeating an uncertain side effect before reconciliation",
    ]
    optional = []
    if state.decisions:
        optional.append("DECISIONS\n" + "\n".join(f"  - {item.text}" for item in state.decisions))
    if state.findings:
        optional.append("FINDINGS\n" + "\n".join(f"  - {text}" for text in state.findings))
    budget = max(profile.context_tokens * CHARS_PER_TOKEN, 1)
    briefing = "\n\n".join(critical)
    for section in optional:
        candidate = briefing + "\n\n" + section
        if len(candidate) <= budget:
            briefing = candidate
    return briefing[:budget]


def handoff(
    store: EverRunStore,
    mission_id: str,
    to_agent: AgentProfile,
    from_agent: str | None = None,
) -> HandoffCapsule:
    decision = recover(store, mission_id)
    if decision.mode in {RecoveryMode.RECONCILE, RecoveryMode.ABORT}:
        raise HandoffRefused(
            f"handoff refused while mode={decision.mode.value}; resolve {decision.next_safe_action} first"
        )
    source = from_agent or store.current_agent(mission_id) or "unknown"
    briefing = compile_briefing(store, mission_id, to_agent)
    issued_at = datetime.now(UTC).isoformat()
    draft = HandoffCapsule(
        mission_id, source, to_agent.name, decision.next_safe_action, briefing, issued_at
    )
    capsule = replace(draft, digest=sha256_text(canonical(draft.content())))
    store.append(
        mission_id,
        EventType.HANDOFF_STARTED,
        {"from_agent": source, "to_agent": to_agent.name},
        origin=Origin.DETERMINISTIC,
    )
    store.append(
        mission_id,
        EventType.HANDOFF_COMPLETED,
        {
            "from_agent": source,
            "to_agent": to_agent.name,
            "next_safe_action": decision.next_safe_action,
            "capsule_digest": capsule.digest,
        },
        origin=Origin.DETERMINISTIC,
    )
    return capsule
