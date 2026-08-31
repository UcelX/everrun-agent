from __future__ import annotations

from dataclasses import dataclass, field


class BudgetExceeded(RuntimeError):
    pass


@dataclass
class RetryBudget:
    """Attempt caps enforced at claim time.

    Two different limits, because the review (H1/L5) showed the old single
    per-kind row count protected neither case correctly:

    - ``limits`` caps attempts of the SAME action (same kind + same args). This
      is the runaway-retry guard: previously retrying one action never raised the
      counter at all, so a cap of 2 allowed unlimited retries.
    - ``kind_totals`` caps the total number of DISTINCT actions of a kind. Use it
      to bound fan-out, e.g. "never charge more than 100 invoices in one mission".
      Completed work no longer silently erodes another action's retry allowance.
    """

    limits: dict[str, int] = field(default_factory=dict)
    kind_totals: dict[str, int] = field(default_factory=dict)

    def check(self, kind: str, attempts: int, distinct_actions: int = 0) -> None:
        limit = self.limits.get(kind)
        if limit is not None and attempts >= limit:
            raise BudgetExceeded(f"retry budget exhausted for {kind}: {attempts}/{limit}")
        total = self.kind_totals.get(kind)
        if total is not None and distinct_actions >= total:
            raise BudgetExceeded(
                f"action budget exhausted for {kind}: {distinct_actions}/{total} distinct actions"
            )

    def remaining(self, kind: str, attempts: int) -> int | None:
        limit = self.limits.get(kind)
        return None if limit is None else max(limit - attempts, 0)
