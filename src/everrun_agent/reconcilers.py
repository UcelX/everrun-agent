from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from .ledger import ActionLedger


class UnresolvedAction(RuntimeError):
    pass


Probe = Callable[[dict[str, Any]], bool]


@dataclass
class ReconcilerRegistry:
    """Registered probes settle uncertain effects from reality, never by assumption."""

    probes: dict[str, Probe] = field(default_factory=dict)

    def register(self, kind: str, probe: Probe) -> None:
        self.probes[kind] = probe

    def probe_for(self, kind: str) -> Probe | None:
        return self.probes.get(kind)


def reconcile_pending(ledger: ActionLedger, registry: ReconcilerRegistry) -> int:
    settled = 0
    for row in ledger.uncertain_details():
        probe = registry.probe_for(row["kind"])
        if probe is None:
            raise UnresolvedAction(
                f"no probe registered for {row['kind']}; a human must settle {row['action_key']}"
            )
        occurred = bool(probe(row["args"]))
        ledger.reconcile(row["action_key"], occurred=occurred, external_id=None)
        settled += 1
    return settled
