from __future__ import annotations

import os
import sys
from typing import Any

from .service import ToolReply, ToolRequest, ToolServer


def build_server_from_env() -> ToolServer:
    """Build the authenticated EverRun application service from environment."""

    clients = os.environ.get("EVERRUN_MUTATING_CLIENTS", "")
    allowlist = tuple(entry.strip() for entry in clients.split(",") if entry.strip())
    if not allowlist:
        print(
            "everrun-mcp: EVERRUN_MUTATING_CLIENTS is unset, so this server is READ-ONLY. "
            "Set it to a comma-separated client allowlist to permit mutation.",
            file=sys.stderr,
        )
    transport_client = os.environ.get("EVERRUN_TRANSPORT_CLIENT") or None
    client_tokens = {
        client: token
        for entry in os.environ.get("EVERRUN_CLIENT_TOKENS", "").split(",")
        if ":" in entry
        for client, token in [entry.split(":", 1)]
        if client and token
    }
    # JSON-RPC metadata is attacker-controlled. Mutation requires identity pinned
    # to the stdio transport or proven with a per-client token.
    if allowlist and transport_client is None and not client_tokens:
        print(
            "everrun-mcp: mutation allowlist ignored because no authenticated "
            "transport identity is configured; set EVERRUN_TRANSPORT_CLIENT or "
            "EVERRUN_CLIENT_TOKENS.",
            file=sys.stderr,
        )
        allowlist = ()
    return ToolServer(
        db_path=os.environ.get("EVERRUN_DB", ".everrun/everrun.db"),
        mutating_clients=allowlist,
        confirm_token=os.environ.get("EVERRUN_CONFIRM_TOKEN"),
        transport_client=transport_client,
        client_tokens=client_tokens,
    )


def _unwrap(reply: ToolReply) -> dict[str, Any]:
    if not reply.ok:
        raise ValueError(
            f"{reply.error_code or 'everrun_error'}: {reply.error or 'operation failed'}"
        )
    return reply.data


def build_mcp_server() -> Any:
    """Build a protocol-compliant MCP server backed by EverRun's ToolServer."""

    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:  # pragma: no cover - exercised by clean-install smoke
        raise RuntimeError("MCP support is not installed; install `everrun-agent[mcp]`") from exc

    service = build_server_from_env()
    mcp = FastMCP(
        "EverRun Agent",
        instructions=(
            "Durable mission continuity. Start a mission, record verified progress, "
            "claim external effects before firing, reconcile uncertainty, and resume safely."
        ),
        log_level="WARNING",
    )

    def call(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return _unwrap(service.handle(ToolRequest(name, arguments)))

    @mcp.tool(name="everrun_start")
    def start(mission_id: str, goal: str, total: int = 0) -> dict[str, Any]:
        """Create a durable mission before beginning work."""
        return call("everrun_start", {"mission_id": mission_id, "goal": goal, "total": total})

    @mcp.tool(name="everrun_record_work")
    def record_work(mission_id: str, item: str) -> dict[str, Any]:
        """Record one completed unit of externally reported work."""
        return call("everrun_record_work", {"mission_id": mission_id, "item": item})

    @mcp.tool(name="everrun_checkpoint")
    def checkpoint(mission_id: str) -> dict[str, Any]:
        """Seal a durable checkpoint of the current mission state."""
        return call("everrun_checkpoint", {"mission_id": mission_id})

    @mcp.tool(name="everrun_claim_action")
    def claim_action(
        mission_id: str, kind: str, args: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Claim an external side effect before firing it."""
        return call(
            "everrun_claim_action",
            {"mission_id": mission_id, "kind": kind, "args": args or {}},
        )

    @mcp.tool(name="everrun_complete_action")
    def complete_action(
        mission_id: str,
        key: str,
        external_id: str | None = None,
        result: Any = None,
    ) -> dict[str, Any]:
        """Mark a claimed side effect complete after authoritative success."""
        return call(
            "everrun_complete_action",
            {
                "mission_id": mission_id,
                "key": key,
                "external_id": external_id,
                "result": result,
            },
        )

    @mcp.tool(name="everrun_reconcile_action")
    def reconcile_action(
        mission_id: str,
        key: str,
        occurred: bool,
        external_id: str | None = None,
    ) -> dict[str, Any]:
        """Settle an uncertain effect from an authoritative probe."""
        return call(
            "everrun_reconcile_action",
            {
                "mission_id": mission_id,
                "key": key,
                "occurred": occurred,
                "external_id": external_id,
            },
        )

    @mcp.tool(name="everrun_list_actions")
    def list_actions(mission_id: str) -> dict[str, Any]:
        """List unresolved external effects for a mission."""
        return call("everrun_list_actions", {"mission_id": mission_id})

    @mcp.tool(name="everrun_status")
    def status(mission_id: str) -> dict[str, Any]:
        """Read projected mission state and current recovery mode."""
        return call("everrun_status", {"mission_id": mission_id})

    @mcp.tool(name="everrun_resume")
    def resume(mission_id: str) -> dict[str, Any]:
        """Return the sealed recovery decision and exactly one safe next action."""
        return call("everrun_resume", {"mission_id": mission_id})

    @mcp.tool(name="everrun_briefing")
    def briefing(mission_id: str) -> dict[str, Any]:
        """Compile a compact cross-agent mission briefing."""
        return call("everrun_briefing", {"mission_id": mission_id})

    @mcp.tool(name="everrun_close")
    def close(mission_id: str) -> dict[str, Any]:
        """Explicitly close a mission after all fail-closed conditions pass."""
        return call("everrun_close", {"mission_id": mission_id})

    return mcp


def main() -> int:
    build_mcp_server().run(transport="stdio")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
