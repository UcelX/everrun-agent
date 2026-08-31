from __future__ import annotations

import json
from pathlib import Path

import pytest

from everrun_agent import ActionLedger, EverRunStore, Mission
from everrun_agent.adapters import GenericAgentAdapter, install_hooks, uninstall_hooks
from everrun_agent.handoff import (
    AgentProfile,
    HandoffRefused,
    compile_briefing,
    handoff,
)
from everrun_agent.models import Origin


def test_generic_adapter_claims_before_firing_and_records_evidence(tmp_path: Path) -> None:
    fired: list[str] = []
    artifact = tmp_path / "out.txt"
    with EverRunStore(tmp_path / "everrun.db") as store:
        adapter = GenericAgentAdapter(store, Mission("m1", "adapter", 2))
        result = adapter.perform(
            "write_file",
            {"path": str(artifact)},
            lambda: (artifact.write_text("done", encoding="utf-8"), fired.append("write"))[1],
        )
        assert result.performed
        adapter.observe_file(artifact, expected_text="done")
        repeat = adapter.perform(
            "write_file",
            {"path": str(artifact)},
            lambda: fired.append("write-again"),
        )
        assert not repeat.performed
        assert fired == ["write"]
        kinds = [event.event_type.value for event in store.events("m1")]
        assert "evidence_recorded" in kinds
        assert adapter.record_progress("item-1").origin is Origin.DETERMINISTIC


def test_handoff_refuses_while_side_effect_is_uncertain(tmp_path: Path) -> None:
    with EverRunStore(tmp_path / "everrun.db") as store:
        store.create_mission(Mission("m1", "handoff", 2))
        ActionLedger(store, "m1").claim("deploy", {"env": "prod"})
        with pytest.raises(HandoffRefused):
            handoff(store, "m1", AgentProfile("hermes", context_tokens=8000))


def test_handoff_transfers_authority_and_records_events(tmp_path: Path) -> None:
    with EverRunStore(tmp_path / "everrun.db") as store:
        store.create_mission(Mission("m1", "handoff", 2))
        store.append_work("m1", "a")
        capsule = handoff(
            store, "m1", AgentProfile("hermes", context_tokens=8000), from_agent="claude-code"
        )
        assert capsule.to_agent == "hermes"
        assert capsule.next_safe_action == "continue_work"
        assert capsule.verify()
        events = [event.event_type.value for event in store.events("m1")]
        assert events.count("handoff_completed") == 1
        assert store.current_agent("m1") == "hermes"


def test_briefing_respects_token_budget_but_keeps_critical_sections(tmp_path: Path) -> None:
    with EverRunStore(tmp_path / "everrun.db") as store:
        store.create_mission(Mission("m1", "budget briefing", 3))
        for index in range(3):
            store.append_decision("m1", f"d{index}", f"decision text {index} " * 40)
        briefing = compile_briefing(store, "m1", AgentProfile("small-model", context_tokens=200))
        assert "GOAL" in briefing and "NEXT SAFE ACTION" in briefing
        assert len(briefing) <= 200 * 4
        assert "FORBIDDEN" in briefing


def test_hook_installer_is_reversible_and_idempotent(tmp_path: Path) -> None:
    target = tmp_path / "hooks.json"
    first = install_hooks(target, client="claude-code", db_path=tmp_path / "everrun.db")
    second = install_hooks(target, client="claude-code", db_path=tmp_path / "everrun.db")
    assert first == second
    payload = json.loads(target.read_text(encoding="utf-8"))
    command = payload["hooks"]["claude-code"]["pre_tool_use"]
    assert isinstance(command, list)
    assert command[0] == "everrun"
    uninstall_hooks(target, client="claude-code")
    assert json.loads(target.read_text(encoding="utf-8"))["hooks"] == {}
