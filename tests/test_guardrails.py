from __future__ import annotations

from pathlib import Path

import pytest

from everrun_agent import ActionLedger, EverRunStore, Mission
from everrun_agent.budgets import BudgetExceeded, RetryBudget
from everrun_agent.gate import UnclaimedSideEffect, protected_call
from everrun_agent.reconcilers import ReconcilerRegistry, UnresolvedAction, reconcile_pending
from everrun_agent.verifier import PolicyViolation, VerifierPolicy, verify_command, verify_http


def test_probe_reconciler_settles_uncertain_action_from_reality(tmp_path: Path) -> None:
    marker = tmp_path / "effect.txt"
    marker.write_text("done", encoding="utf-8")
    with EverRunStore(tmp_path / "everrun.db") as store:
        store.create_mission(Mission("m1", "probe", 1))
        ledger = ActionLedger(store, "m1")
        ledger.claim("publish", {"target": str(marker)})
        registry = ReconcilerRegistry()
        registry.register("publish", lambda args: marker.exists())
        settled = reconcile_pending(ledger, registry)
        assert settled == 1
        assert ledger.uncertain() == []


def test_reconciler_without_probe_stays_unresolved(tmp_path: Path) -> None:
    with EverRunStore(tmp_path / "everrun.db") as store:
        store.create_mission(Mission("m1", "no probe", 1))
        ledger = ActionLedger(store, "m1")
        ledger.claim("publish", {"target": "unknown"})
        with pytest.raises(UnresolvedAction):
            reconcile_pending(ledger, ReconcilerRegistry())
        assert len(ledger.uncertain()) == 1


def test_unclaimed_side_effect_is_refused_before_it_fires(tmp_path: Path) -> None:
    fired: list[str] = []
    with EverRunStore(tmp_path / "everrun.db") as store:
        store.create_mission(Mission("m1", "gate", 1))
        ledger = ActionLedger(store, "m1")
        with pytest.raises(UnclaimedSideEffect):
            protected_call(
                ledger,
                "deploy",
                {"env": "prod"},
                lambda: fired.append("deploy"),
                require_claim=True,
            )
        assert fired == []
        result = protected_call(
            ledger, "deploy", {"env": "prod"}, lambda: fired.append("deploy") or "dep-1"
        )
        assert fired == ["deploy"]
        assert result.external_id is None or isinstance(result.external_id, str)
        assert ledger.uncertain() == []


def test_retry_budget_blocks_runaway_attempts(tmp_path: Path) -> None:
    with EverRunStore(tmp_path / "everrun.db") as store:
        store.create_mission(Mission("m1", "budget", 5))
        # Per-action cap: retrying the SAME action is what a retry budget bounds.
        ledger = ActionLedger(store, "m1", budget=RetryBudget({"flaky": 2}))
        for _ in range(2):
            claim = ledger.claim("flaky", {"n": 1})
            ledger.reconcile(claim.key, occurred=False)
        with pytest.raises(BudgetExceeded):
            ledger.claim("flaky", {"n": 1})


def test_kind_total_budget_bounds_distinct_actions(tmp_path: Path) -> None:
    with EverRunStore(tmp_path / "everrun.db") as store:
        store.create_mission(Mission("m1", "fanout", 5))
        ledger = ActionLedger(store, "m1", budget=RetryBudget(kind_totals={"flaky": 2}))
        for index in (1, 2):
            claim = ledger.claim("flaky", {"n": index})
            ledger.reconcile(claim.key, occurred=False)
        with pytest.raises(BudgetExceeded):
            ledger.claim("flaky", {"n": 3})


def test_http_verifier_refuses_private_targets_by_default() -> None:
    with pytest.raises(PolicyViolation):
        verify_http("http://169.254.169.254/latest/meta-data/")
    with pytest.raises(PolicyViolation):
        verify_http("file:///etc/passwd")


def test_command_verifier_enforces_allowlist_and_redacts_output() -> None:
    policy = VerifierPolicy(allowed_commands=("python3",))
    with pytest.raises(PolicyViolation):
        verify_command(["curl", "https://example.test"], policy=policy)
    evidence = verify_command(
        ["python3", "-c", "print('token=super-secret-value')"],
        contains="token",
        policy=policy,
    )
    assert evidence.ok
    assert "super-secret-value" not in evidence.detail
    assert "[REDACTED]" in evidence.detail
