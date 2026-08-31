"""Tests for the C2 confirmation-ticket authority separation."""

from __future__ import annotations

from pathlib import Path

import pytest

from everrun_agent import EverRunStore, Mission
from everrun_agent.mcp_server import build_server_from_env
from everrun_agent.service import AuthorizationError, ToolRequest, ToolServer


def test_ticket_is_single_use_and_hash_only(tmp_path: Path) -> None:
    db = tmp_path / "everrun.db"
    with EverRunStore(db) as store:
        store.create_mission(Mission("m1", "ticket", 1))
        ticket = store.issue_confirm_ticket("m1")
        assert store.open_confirm_tickets("m1") == 1
        # The plaintext ticket is never stored.
        rows = store.raw_query("SELECT ticket_hash FROM confirm_tickets")
        assert ticket not in {row["ticket_hash"] for row in rows}
        assert store.consume_confirm_ticket("m1", ticket)
        assert not store.consume_confirm_ticket("m1", ticket)
        assert store.open_confirm_tickets("m1") == 0


def test_ticket_is_scoped_to_its_mission(tmp_path: Path) -> None:
    with EverRunStore(tmp_path / "everrun.db") as store:
        store.create_mission(Mission("m1", "a", 1))
        store.create_mission(Mission("m2", "b", 1))
        ticket = store.issue_confirm_ticket("m1")
        assert not store.consume_confirm_ticket("m2", ticket)
        assert store.consume_confirm_ticket("m1", ticket)


def test_ticket_cannot_be_minted_for_an_unknown_mission(tmp_path: Path) -> None:
    with EverRunStore(tmp_path / "everrun.db") as store, pytest.raises(KeyError):
        store.issue_confirm_ticket("ghost")


def test_agent_cannot_forge_a_ticket(tmp_path: Path) -> None:
    server = ToolServer(db_path=tmp_path / "everrun.db", mutating_clients=("agent",))
    server.handle(
        ToolRequest("everrun_start", {"mission_id": "m1", "goal": "g", "total": 1}, client="agent")
    )
    for forged in ("", "guess", "a" * 43):
        with pytest.raises(AuthorizationError):
            server.handle(
                ToolRequest(
                    "everrun_confirm", {"mission_id": "m1", "ticket": forged}, client="agent"
                )
            )


def test_mcp_server_defaults_to_read_only_without_an_allowlist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """C3: a forgotten env var must not silently grant full mutation."""

    monkeypatch.delenv("EVERRUN_MUTATING_CLIENTS", raising=False)
    monkeypatch.setenv("EVERRUN_DB", str(tmp_path / "everrun.db"))
    server = build_server_from_env()
    assert server.mutating_clients == ()
    with pytest.raises(AuthorizationError):
        server.handle(
            ToolRequest(
                "everrun_start", {"mission_id": "m1", "goal": "g", "total": 1}, client="anyone"
            )
        )


def test_mcp_server_requires_transport_identity_beyond_allowlist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EVERRUN_MUTATING_CLIENTS", " agent , operator ")
    monkeypatch.delenv("EVERRUN_TRANSPORT_CLIENT", raising=False)
    monkeypatch.delenv("EVERRUN_CLIENT_TOKENS", raising=False)
    monkeypatch.setenv("EVERRUN_DB", str(tmp_path / "everrun.db"))
    server = build_server_from_env()
    assert server.mutating_clients == ()
    with pytest.raises(AuthorizationError):
        server.handle(
            ToolRequest(
                "everrun_start",
                {"mission_id": "m1", "goal": "g", "total": 1},
                client="agent",
            )
        )


def test_mcp_server_honours_transport_pinned_allowlist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EVERRUN_MUTATING_CLIENTS", "agent")
    monkeypatch.setenv("EVERRUN_TRANSPORT_CLIENT", "agent")
    monkeypatch.delenv("EVERRUN_CLIENT_TOKENS", raising=False)
    monkeypatch.setenv("EVERRUN_DB", str(tmp_path / "everrun.db"))
    server = build_server_from_env()
    assert server.mutating_clients == ("agent",)
    assert server.handle(
        ToolRequest(
            "everrun_start",
            {"mission_id": "m1", "goal": "g", "total": 1},
            client="spoofed",
        )
    ).ok


def test_transport_pinned_identity_ignores_self_asserted_client(tmp_path: Path) -> None:
    server = ToolServer(
        db_path=tmp_path / "everrun.db",
        mutating_clients=("trusted-stdio",),
        transport_client="trusted-stdio",
    )
    assert server.handle(
        ToolRequest(
            "everrun_start",
            {"mission_id": "m1", "goal": "g", "total": 1},
            client="attacker-claim",
        )
    ).ok


def test_multiplexed_identity_requires_per_client_token(tmp_path: Path) -> None:
    server = ToolServer(
        db_path=tmp_path / "everrun.db",
        mutating_clients=("operator",),
        client_tokens={"operator": "operator-secret"},
    )
    request = {
        "mission_id": "m1",
        "goal": "g",
        "total": 1,
    }
    with pytest.raises(AuthorizationError, match="identity not proven"):
        server.handle(ToolRequest("everrun_start", request, client="operator"))
    with pytest.raises(AuthorizationError, match="identity not proven"):
        server.handle(
            ToolRequest(
                "everrun_start",
                request,
                client="operator",
                client_token="wrong",
            )
        )
    assert server.handle(
        ToolRequest(
            "everrun_start",
            request,
            client="operator",
            client_token="operator-secret",
        )
    ).ok


def test_json_rpc_forwards_client_token_for_authenticated_identity(tmp_path: Path) -> None:
    server = ToolServer(
        db_path=tmp_path / "everrun.db",
        mutating_clients=("operator",),
        client_tokens={"operator": "operator-secret"},
    )
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "everrun_start",
            "arguments": {"mission_id": "m1", "goal": "g", "total": 1},
        },
        "_meta": {"client": "operator", "client_token": "operator-secret"},
    }
    import json

    response = json.loads(server.dispatch_json(json.dumps(payload)))
    assert response["result"]["ok"] is True
