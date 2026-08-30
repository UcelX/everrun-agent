from __future__ import annotations

import json
from pathlib import Path

import pytest

from everrun_agent import EverRunStore
from everrun_agent.service import (
    READ_ONLY_TOOLS,
    AuthorizationError,
    ToolRequest,
    ToolServer,
)


def _server(tmp_path: Path, **kwargs: object) -> ToolServer:
    return ToolServer(db_path=tmp_path / "everrun.db", **kwargs)  # type: ignore[arg-type]


def test_read_only_tools_are_allowed_without_mutation_grant(tmp_path: Path) -> None:
    server = _server(tmp_path)
    server.handle(
        ToolRequest(
            "everrun_start", {"mission_id": "m1", "goal": "svc", "total": 1}, client="operator"
        )
    )
    reply = server.handle(ToolRequest("everrun_status", {"mission_id": "m1"}, client="reader"))
    assert reply.ok
    assert reply.data["mode"] == "continue"
    assert "everrun_status" in READ_ONLY_TOOLS


def test_mutating_tools_deny_unknown_clients(tmp_path: Path) -> None:
    server = _server(tmp_path, mutating_clients=("operator",))
    with pytest.raises(AuthorizationError):
        server.handle(
            ToolRequest(
                "everrun_start", {"mission_id": "m1", "goal": "svc", "total": 1}, client="stranger"
            )
        )


def test_confirm_requires_separate_authority(tmp_path: Path) -> None:
    server = _server(tmp_path, mutating_clients=("agent",), confirm_token="human-only")
    server.handle(
        ToolRequest(
            "everrun_start", {"mission_id": "m1", "goal": "svc", "total": 1}, client="agent"
        )
    )
    server.handle(
        ToolRequest("everrun_record_work", {"mission_id": "m1", "item": "a"}, client="agent")
    )
    review = server.handle(ToolRequest("everrun_status", {"mission_id": "m1"}, client="agent"))
    assert review.data["mode"] == "request_review"
    with pytest.raises(AuthorizationError):
        server.handle(ToolRequest("everrun_confirm", {"mission_id": "m1"}, client="agent"))
    confirmed = server.handle(
        ToolRequest(
            "everrun_confirm", {"mission_id": "m1"}, client="agent", confirm_token="human-only"
        )
    )
    assert confirmed.ok
    after = server.handle(ToolRequest("everrun_status", {"mission_id": "m1"}, client="agent"))
    assert after.data["mode"] == "continue"
    assert after.data["next_safe_action"] == "close_mission"
    closed = server.handle(ToolRequest("everrun_close", {"mission_id": "m1"}, client="agent"))
    assert closed.ok
    final = server.handle(ToolRequest("everrun_status", {"mission_id": "m1"}, client="agent"))
    assert final.data["mode"] == "verified_complete"


def test_agent_reported_work_is_marked_external(tmp_path: Path) -> None:
    server = _server(tmp_path)
    server.handle(
        ToolRequest(
            "everrun_start", {"mission_id": "m1", "goal": "svc", "total": 2}, client="agent"
        )
    )
    server.handle(
        ToolRequest("everrun_record_work", {"mission_id": "m1", "item": "a"}, client="agent")
    )
    with EverRunStore(tmp_path / "everrun.db") as store:
        assert store.events("m1")[-1].origin.value == "external_agent"


def test_two_phase_action_tools_refuse_duplicate_effects(tmp_path: Path) -> None:
    server = _server(tmp_path)
    server.handle(
        ToolRequest(
            "everrun_start", {"mission_id": "m1", "goal": "svc", "total": 1}, client="agent"
        )
    )
    claim = server.handle(
        ToolRequest(
            "everrun_claim_action",
            {"mission_id": "m1", "kind": "deploy", "args": {"env": "prod"}},
            client="agent",
        )
    )
    assert claim.data["fresh"] is True
    server.handle(
        ToolRequest(
            "everrun_complete_action",
            {"mission_id": "m1", "key": claim.data["key"], "external_id": "dep-1"},
            client="agent",
        )
    )
    repeat = server.handle(
        ToolRequest(
            "everrun_claim_action",
            {"mission_id": "m1", "kind": "deploy", "args": {"env": "prod"}},
            client="agent",
        )
    )
    assert repeat.data["fresh"] is False
    assert repeat.data["external_id"] == "dep-1"


def test_unknown_tool_and_malformed_payload_fail_closed(tmp_path: Path) -> None:
    server = _server(tmp_path)
    reply = server.handle(ToolRequest("everrun_nope", {}, client="agent"))
    assert not reply.ok and reply.error_code == "unknown_tool"
    bad = server.handle(ToolRequest("everrun_status", {}, client="agent"))
    assert not bad.ok and bad.error_code == "invalid_arguments"


def test_jsonrpc_dispatch_round_trip(tmp_path: Path) -> None:
    server = _server(tmp_path)
    request = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 7,
            "method": "tools/call",
            "params": {
                "name": "everrun_start",
                "arguments": {"mission_id": "m1", "goal": "rpc", "total": 1},
            },
            "_meta": {"client": "agent"},
        }
    )
    response = json.loads(server.dispatch_json(request))
    assert response["id"] == 7
    assert response["result"]["ok"] is True
    listing = json.loads(
        server.dispatch_json(json.dumps({"jsonrpc": "2.0", "id": 8, "method": "tools/list"}))
    )
    names = {tool["name"] for tool in listing["result"]["tools"]}
    assert "everrun_resume" in names and "everrun_reconcile_action" in names
