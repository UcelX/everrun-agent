from __future__ import annotations

from pathlib import Path

import pytest

from everrun_agent import ActionLedger, EverRunStore, Mission
from everrun_agent.contracts import ContractClause, SuccessContract
from everrun_agent.environment import EnvironmentSnapshot
from everrun_agent.evidence import EvidenceRecord, record_evidence
from everrun_agent.models import Origin, RecoveryMode
from everrun_agent.recovery import SEVERITY, recover


def test_severity_ordering_is_explicit_and_total() -> None:
    assert SEVERITY[RecoveryMode.VERIFIED_COMPLETE] < SEVERITY[RecoveryMode.CONTINUE]
    assert SEVERITY[RecoveryMode.CONTINUE] < SEVERITY[RecoveryMode.WAIT]
    assert SEVERITY[RecoveryMode.WAIT] < SEVERITY[RecoveryMode.REPAIR]
    assert SEVERITY[RecoveryMode.REPAIR] < SEVERITY[RecoveryMode.REQUEST_REVIEW]
    assert SEVERITY[RecoveryMode.REQUEST_REVIEW] < SEVERITY[RecoveryMode.RECONCILE]
    assert SEVERITY[RecoveryMode.RECONCILE] < SEVERITY[RecoveryMode.ABORT]
    assert len(SEVERITY) == len(RecoveryMode)


def test_environment_drift_forces_repair_before_continuing(tmp_path: Path) -> None:
    with EverRunStore(tmp_path / "everrun.db") as store:
        store.create_mission(Mission("m1", "pinned work", 5))
        store.pin_environment("m1", EnvironmentSnapshot({"dataset": "v3"}))
        store.append_work("m1", "a")
        clean = recover(store, "m1", current_environment=EnvironmentSnapshot({"dataset": "v3"}))
        assert clean.mode is RecoveryMode.CONTINUE
        drifted = recover(store, "m1", current_environment=EnvironmentSnapshot({"dataset": "v4"}))
        assert drifted.mode is RecoveryMode.REPAIR
        assert drifted.next_safe_action == "revalidate:dataset"
        assert not drifted.safe


def test_unknown_environment_value_is_not_treated_as_valid(tmp_path: Path) -> None:
    with EverRunStore(tmp_path / "everrun.db") as store:
        store.create_mission(Mission("m1", "pinned", 2))
        store.pin_environment("m1", EnvironmentSnapshot({"dataset": "v3"}))
        unknown = recover(store, "m1", current_environment=EnvironmentSnapshot({}))
        assert unknown.mode is RecoveryMode.REPAIR
        assert not unknown.safe


def test_progress_alone_no_longer_declares_verified_complete(tmp_path: Path) -> None:
    with EverRunStore(tmp_path / "everrun.db") as store:
        store.create_mission(Mission("m1", "finish", 1))
        store.append_work("m1", "a")
        decision = recover(store, "m1")
        assert decision.mode is RecoveryMode.CONTINUE
        assert decision.next_safe_action == "close_mission"


def test_explicit_terminal_transition_yields_verified_complete(tmp_path: Path) -> None:
    with EverRunStore(tmp_path / "everrun.db") as store:
        store.create_mission(Mission("m1", "finish", 1))
        store.append_work("m1", "a")
        store.complete_mission("m1")
        decision = recover(store, "m1")
        assert decision.mode is RecoveryMode.VERIFIED_COMPLETE
        assert decision.safe
        assert decision.next_safe_action == "none"


def test_mission_cannot_be_closed_with_unresolved_effect(tmp_path: Path) -> None:
    with EverRunStore(tmp_path / "everrun.db") as store:
        store.create_mission(Mission("m1", "finish", 1))
        store.append_work("m1", "a")
        ActionLedger(store, "m1").claim("publish", {"to": "prod"})
        with pytest.raises(ValueError, match="unresolved"):
            store.complete_mission("m1")


def test_mission_cannot_be_closed_before_progress_target(tmp_path: Path) -> None:
    with EverRunStore(tmp_path / "everrun.db") as store:
        store.create_mission(Mission("m1", "finish", 3))
        store.append_work("m1", "a")
        with pytest.raises(ValueError, match="progress"):
            store.complete_mission("m1")


def test_mission_close_can_require_a_success_contract(tmp_path: Path) -> None:
    contract = SuccessContract((ContractClause("health", expected=True),))
    with EverRunStore(tmp_path / "everrun.db") as store:
        store.create_mission(Mission("m1", "contracted", 1))
        store.append_work("m1", "a")
        with pytest.raises(ValueError, match="contract"):
            store.complete_mission("m1", contract=contract)
        record_evidence(
            store, "m1", EvidenceRecord("health", "http", "https://x.test", True, "sha256:1")
        )
        store.complete_mission("m1", contract=contract)
        assert recover(store, "m1").mode is RecoveryMode.VERIFIED_COMPLETE


def test_uncertain_effect_still_outranks_environment_drift(tmp_path: Path) -> None:
    with EverRunStore(tmp_path / "everrun.db") as store:
        store.create_mission(Mission("m1", "priority", 2))
        store.pin_environment("m1", EnvironmentSnapshot({"dataset": "v3"}))
        claim = ActionLedger(store, "m1").claim("publish", {"to": "prod"})
        decision = recover(store, "m1", current_environment=EnvironmentSnapshot({"dataset": "v9"}))
        assert decision.mode is RecoveryMode.RECONCILE
        assert decision.next_safe_action == f"reconcile:{claim.key}"


def test_external_review_outranks_environment_repair(tmp_path: Path) -> None:
    with EverRunStore(tmp_path / "everrun.db") as store:
        store.create_mission(Mission("m1", "priority", 2))
        store.pin_environment("m1", EnvironmentSnapshot({"dataset": "v3"}))
        store.append_work("m1", "a", origin=Origin.EXTERNAL_AGENT)
        decision = recover(store, "m1", current_environment=EnvironmentSnapshot({"dataset": "v4"}))
        assert decision.mode is RecoveryMode.REQUEST_REVIEW
        assert decision.next_safe_action == "confirm_progress"


def test_recovery_reports_all_contributing_reasons(tmp_path: Path) -> None:
    with EverRunStore(tmp_path / "everrun.db") as store:
        store.create_mission(Mission("m1", "reasons", 2))
        store.pin_environment("m1", EnvironmentSnapshot({"dataset": "v3"}))
        store.append_work("m1", "a", origin=Origin.EXTERNAL_AGENT)
        decision = recover(store, "m1", current_environment=EnvironmentSnapshot({"dataset": "v4"}))
        joined = " ".join(decision.reasons)
        assert "dataset" in joined
        assert "external" in joined
