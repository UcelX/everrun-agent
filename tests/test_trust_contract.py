from __future__ import annotations

from pathlib import Path

from everrun_agent import EventType, EverRunStore, Mission
from everrun_agent.contracts import ContractClause, SuccessContract, evaluate_contract
from everrun_agent.evidence import EvidenceRecord, record_evidence
from everrun_agent.models import Origin, RecoveryMode
from everrun_agent.recovery import recover


def test_external_agent_progress_cannot_self_certify_completion(tmp_path: Path) -> None:
    with EverRunStore(tmp_path / "everrun.db") as store:
        store.create_mission(Mission("m1", "Verified work", 1))
        store.append("m1", EventType.WORK_COMPLETED, {"item": "a"}, origin=Origin.EXTERNAL_AGENT)
        decision = recover(store, "m1")
        assert decision.mode is RecoveryMode.REQUEST_REVIEW
        assert not decision.safe
        assert decision.next_safe_action == "confirm_progress"


def test_authoritative_evidence_can_satisfy_success_contract(tmp_path: Path) -> None:
    with EverRunStore(tmp_path / "everrun.db") as store:
        store.create_mission(Mission("m1", "Deploy", 1))
        store.append(
            "m1", EventType.WORK_COMPLETED, {"item": "deploy"}, origin=Origin.DETERMINISTIC
        )
        evidence = EvidenceRecord(
            "health", "http", "https://example.test/health", True, "sha256:abc"
        )
        record_evidence(store, "m1", evidence)
        contract = SuccessContract((ContractClause("health", expected=True),))
        result = evaluate_contract(contract, store.events("m1"))
        assert result.satisfied and result.proven == ("health",)


def test_recovery_contract_is_sealed_and_tamper_evident(tmp_path: Path) -> None:
    with EverRunStore(tmp_path / "everrun.db") as store:
        store.create_mission(Mission("m1", "Continue", 2))
        contract = recover(store, "m1")
        assert contract.verify()
        assert not contract.replace(next_safe_action="deploy.production").verify()


def test_unresolved_action_outranks_external_progress_review(tmp_path: Path) -> None:
    from everrun_agent import ActionLedger

    with EverRunStore(tmp_path / "everrun.db") as store:
        store.create_mission(Mission("m1", "Priority", 1))
        store.append("m1", EventType.WORK_COMPLETED, {"item": "a"}, origin=Origin.EXTERNAL_AGENT)
        claim = ActionLedger(store, "m1").claim("publish", {"target": "prod"})
        contract = recover(store, "m1")
        assert contract.mode is RecoveryMode.RECONCILE
        assert contract.next_safe_action == f"reconcile:{claim.key}"


def test_evidence_redacts_secret_like_detail(tmp_path: Path) -> None:
    with EverRunStore(tmp_path / "everrun.db") as store:
        store.create_mission(Mission("m1", "Redact", 1))
        record = EvidenceRecord(
            "api", "http", "endpoint", True, "ok", detail="Authorization: Bearer super-secret-token"
        )
        record_evidence(store, "m1", record)
        raw = store.events("m1")[-1].payload["detail"]
        assert "super-secret-token" not in raw
        assert "[REDACTED]" in raw
