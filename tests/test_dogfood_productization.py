from __future__ import annotations

from pathlib import Path

import pytest

from everrun_agent import ActionLedger, EverRunStore, Mission
from everrun_agent.models import Origin
from everrun_agent.service import ToolRequest, ToolServer


def test_fresh_agent_discovers_blocked_mission_without_id(tmp_path: Path) -> None:
    with EverRunStore(tmp_path / "everrun.db") as store:
        store.create_mission(Mission("safe", "continue work", 2))
        store.append_work("safe", "one")
        store.create_mission(Mission("blocked", "recover effect", 1))
        ActionLedger(store, "blocked").claim("publish", {"target": "x"})

        rows = store.list_missions(status="blocked")

    assert [row["mission_id"] for row in rows] == ["blocked"]
    assert rows[0]["mode"] == "reconcile"
    assert rows[0]["next_safe_action"].startswith("reconcile:")
    assert rows[0]["completed"] == 0
    assert rows[0]["total"] == 1
    assert rows[0]["updated_at"]


def test_mission_discovery_orders_most_recent_first(tmp_path: Path) -> None:
    with EverRunStore(tmp_path / "everrun.db") as store:
        store.create_mission(Mission("older", "old", 1))
        store.create_mission(Mission("newer", "new", 1))
        store.append_work("older", "touch-again")
        rows = store.list_missions()
    assert [row["mission_id"] for row in rows] == ["older", "newer"]


def test_mcp_list_missions_is_read_only_and_needs_no_mission_id(tmp_path: Path) -> None:
    with EverRunStore(tmp_path / "everrun.db") as store:
        store.create_mission(Mission("blocked", "recover", 1))
        ActionLedger(store, "blocked").claim("publish", {"target": "x"})
    server = ToolServer(tmp_path / "everrun.db")
    reply = server.handle(ToolRequest("everrun_list_missions", {"status": "blocked"}))
    assert reply.ok
    assert reply.data["missions"][0]["mission_id"] == "blocked"


def test_inspect_combines_integrity_checkpoint_review_and_actions(tmp_path: Path) -> None:
    with EverRunStore(tmp_path / "everrun.db") as store:
        store.create_mission(Mission("m1", "inspect", 2))
        store.append_work("m1", "agent-work", origin=Origin.EXTERNAL_AGENT)
        store.create_checkpoint("m1", reason="milestone")
        claim = ActionLedger(store, "m1").claim("publish", {"target": "x"})
        report = store.inspect_mission("m1")
    assert report["chain"]["ok"] is True
    assert report["event_count"] == 4
    assert report["checkpoint"]["reason"] == "milestone"
    assert report["confirmation"]["required"] is True
    assert report["actions"][0]["action_key"] == claim.key
    assert "args" not in report["actions"][0]


def test_operator_approval_request_is_digest_bound_and_replay_safe(tmp_path: Path) -> None:
    with EverRunStore(tmp_path / "everrun.db") as store:
        store.create_mission(Mission("m1", "approve", 1))
        store.append_work("m1", "done", origin=Origin.EXTERNAL_AGENT)
        request = store.request_approval("m1", ttl_seconds=300)
        assert request["mission_id"] == "m1"
        assert request["mode"] == "request_review"
        assert request["progress"] == {"completed": 1, "total": 1}
        assert request["digest"]
        assert request["expires_at"]
        ticket = request["ticket"]
        approved = store.approve_with_ticket("m1", ticket, request["digest"], "operator")
        assert approved["approved"] is True
        with pytest.raises(ValueError, match="used|expired|unknown"):
            store.approve_with_ticket("m1", ticket, request["digest"], "operator")


def test_approval_rejects_state_changed_after_request(tmp_path: Path) -> None:
    with EverRunStore(tmp_path / "everrun.db") as store:
        store.create_mission(Mission("m1", "approve", 2))
        store.append_work("m1", "a", origin=Origin.EXTERNAL_AGENT)
        request = store.request_approval("m1", ttl_seconds=300)
        store.append_work("m1", "b", origin=Origin.EXTERNAL_AGENT)
        with pytest.raises(ValueError, match="state changed"):
            store.approve_with_ticket("m1", request["ticket"], request["digest"], "operator")
