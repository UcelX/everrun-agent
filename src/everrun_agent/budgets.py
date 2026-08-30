from __future__ import annotations

from dataclasses import dataclass, field


class BudgetExceeded(RuntimeError):
    pass


@dataclass
class RetryBudget:
    """Per-action-kind attempt caps enforced at claim time."""

    limits: dict[str, int] = field(default_factory=dict)

    def check(self, kind: str, attempts: int) -> None:
        limit = self.limits.get(kind)
        if limit is not None and attempts >= limit:
            raise BudgetExceeded(f"retry budget exhausted for {kind}: {attempts}/{limit}")

    def remaining(self, kind: str, attempts: int) -> int | None:
        limit = self.limits.get(kind)
        return None if limit is None else max(limit - attempts, 0)
