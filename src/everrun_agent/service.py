from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .ledger import ActionLedger
from .models import EventType, Mission, Origin, UncertainAction
from .projection import StateProjector
from .recovery import recover
from .store import EverRunStore

READ_ONLY_TOOLS = frozenset(
    {"everrun_status", "everrun_resume", "everrun_list_actions", "everrun_briefing"}
)
MUTATING_TOOLS = frozenset(
    {
        "everrun_start",
        "everrun_record_work",
        "everrun_checkpoint",
        "everrun_claim_action",
        "everrun_complete_action",
        "everrun_reconcile_action",
        "everrun_confirm",
        "everrun_close",
    }
)
ALL_TOOLS = READ_ONLY_TOOLS | MUTATING_TOOLS
CONFIRM_TOOL = "everrun_confirm"


class AuthorizationError(RuntimeError):
    pass


@dataclass(frozen=True)
class ToolRequest:
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)
    client: str = "unknown"
    confirm_token: str | None = None


@dataclass(frozen=True)
class ToolReply:
    ok: bool
    data: dict[str, Any] = field(default_factory=dict)
    error_code: str | None = None
    error: str | None = None


class ToolServer:
    """Deny-by-default tool surface shared by the MCP server and HTTP sidecar."""

    def __init__(
        self,
        db_path: str | Path,
        mutating_clients: tuple[str, ...] | None = None,
        confirm_token: str | None = None,
    ) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.mutating_clients = mutating_clients
        self.confirm_token = confirm_token

    def _authorize(self, request: ToolRequest) -> None:
        if request.name in MUTATING_TOOLS:
            if self.mutating_clients is not None and request.client not in self.mutating_clients:
                raise AuthorizationError(f"client not allowed to mutate: {request.client}")
            if request.name == CONFIRM_TOOL:
                if self.confirm_token is None:
                    raise AuthorizationError("confirmation requires a configured operator token")
                if request.confirm_token != self.confirm_token:
                    raise AuthorizationError("confirmation token rejected")

    def handle(self, request: ToolRequest) -> ToolReply:
        if request.name not in ALL_TOOLS:
            return ToolReply(False, error_code="unknown_tool", error=f"unknown tool {request.name}")
        self._authorize(request)
        handler = getattr(self, f"_tool_{request.name[len('everrun_') :]}")
        try:
            with EverRunStore(self.db_path) as store:
                return ToolReply(True, handler(store, request))
        except KeyError as exc:
            return ToolReply(False, error_code="invalid_arguments", error=str(exc))
        except UncertainAction as exc:
            return ToolReply(False, error_code="uncertain_action", error=str(exc))
        except ValueError as exc:
            return ToolReply(False, error_code="invalid_arguments", error=str(exc))

    # ---- tools -------------------------------------------------------------

    def _tool_start(self, store: EverRunStore, request: ToolRequest) -> dict[str, Any]:
        args = request.arguments
        store.create_mission(Mission(args["mission_id"], args["goal"], int(args.get("total", 0))))
        return {"mission_id": args["mission_id"]}

    def _tool_record_work(self, store: EverRunStore, request: ToolRequest) -> dict[str, Any]:
        args = request.arguments
        store.append(
            args["mission_id"],
            EventType.WORK_COMPLETED,
            {"item": args["item"]},
            origin=Origin.EXTERNAL_AGENT,
        )
        return {"recorded": args["item"], "origin": Origin.EXTERNAL_AGENT.value}

    def _tool_checkpoint(self, store: EverRunStore, request: ToolRequest) -> dict[str, Any]:
        saved = store.create_checkpoint(request.arguments["mission_id"], reason="tool")
        return {"sequence": saved.sequence, "digest": saved.digest}

    def _tool_confirm(self, store: EverRunStore, request: ToolRequest) -> dict[str, Any]:
        store.append(
            request.arguments["mission_id"],
            EventType.REVIEW_CONFIRMED,
            {"confirmed_by": request.client},
            origin=Origin.HUMAN,
        )
        return {"confirmed": True}

    def _tool_close(self, store: EverRunStore, request: ToolRequest) -> dict[str, Any]:
        event = store.complete_mission(request.arguments["mission_id"])
        return {"closed": True, "sequence": event.sequence}

    def _tool_claim_action(self, store: EverRunStore, request: ToolRequest) -> dict[str, Any]:
        args = request.arguments
        claim = ActionLedger(store, args["mission_id"]).claim(args["kind"], args.get("args", {}))
        return {"key": claim.key, "fresh": claim.fresh, "external_id": claim.external_id}

    def _tool_complete_action(self, store: EverRunStore, request: ToolRequest) -> dict[str, Any]:
        args = request.arguments
        ActionLedger(store, args["mission_id"]).complete(
            args["key"], external_id=args.get("external_id"), result=args.get("result")
        )
        return {"completed": args["key"]}

    def _tool_reconcile_action(self, store: EverRunStore, request: ToolRequest) -> dict[str, Any]:
        args = request.arguments
        ActionLedger(store, args["mission_id"]).reconcile(
            args["key"], occurred=bool(args["occurred"]), external_id=args.get("external_id")
        )
        return {"reconciled": args["key"], "occurred": bool(args["occurred"])}

    def _tool_list_actions(self, store: EverRunStore, request: ToolRequest) -> dict[str, Any]:
        ledger = ActionLedger(store, request.arguments["mission_id"])
        return {"uncertain": ledger.uncertain_details()}

    def _tool_status(self, store: EverRunStore, request: ToolRequest) -> dict[str, Any]:
        mission_id = request.arguments["mission_id"]
        state = StateProjector.project(store.events(mission_id))
        decision = recover(store, mission_id)
        return {
            "mission_id": state.mission_id,
            "goal": state.goal,
            "total": state.total,
            "completed": len(state.completed),
            "failed": len(state.failed),
            "mode": decision.mode.value,
            "safe": decision.safe,
            "next_safe_action": decision.next_safe_action,
            "contract_digest": decision.digest,
        }

    def _tool_resume(self, store: EverRunStore, request: ToolRequest) -> dict[str, Any]:
        decision = recover(store, request.arguments["mission_id"])
        return {
            "mode": decision.mode.value,
            "safe": decision.safe,
            "next_safe_action": decision.next_safe_action,
            "reasons": list(decision.reasons),
            "issued_at": decision.issued_at,
            "digest": decision.digest,
        }

    def _tool_briefing(self, store: EverRunStore, request: ToolRequest) -> dict[str, Any]:
        mission_id = request.arguments["mission_id"]
        state = StateProjector.project(store.events(mission_id))
        decision = recover(store, mission_id)
        ledger = ActionLedger(store, mission_id)
        return {
            "goal": state.goal,
            "verified_progress": f"{len(state.completed)}/{state.total}",
            "decisions": [decision_item.text for decision_item in state.decisions],
            "uncertain_actions": [row["action_key"] for row in ledger.uncertain_details()],
            "next_safe_action": decision.next_safe_action,
            "forbidden": ["repeat uncertain side effects before reconciliation"],
        }

    # ---- JSON-RPC ----------------------------------------------------------

    def tool_descriptors(self) -> list[dict[str, Any]]:
        return [{"name": name, "read_only": name in READ_ONLY_TOOLS} for name in sorted(ALL_TOOLS)]

    def dispatch_json(self, payload: str) -> str:
        try:
            message = json.loads(payload)
        except json.JSONDecodeError:
            return json.dumps(
                {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}}
            )
        message_id = message.get("id")
        method = message.get("method")
        if method == "tools/list":
            return json.dumps(
                {"jsonrpc": "2.0", "id": message_id, "result": {"tools": self.tool_descriptors()}}
            )
        if method != "tools/call":
            return json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": message_id,
                    "error": {"code": -32601, "message": "method not found"},
                }
            )
        params = message.get("params") or {}
        meta = message.get("_meta") or {}
        request = ToolRequest(
            params.get("name", ""),
            params.get("arguments") or {},
            client=str(meta.get("client", "unknown")),
            confirm_token=meta.get("confirm_token"),
        )
        try:
            reply = self.handle(request)
        except AuthorizationError as exc:
            return json.dumps(
                {"jsonrpc": "2.0", "id": message_id, "error": {"code": -32001, "message": str(exc)}}
            )
        return json.dumps(
            {
                "jsonrpc": "2.0",
                "id": message_id,
                "result": {
                    "ok": reply.ok,
                    "data": reply.data,
                    "error_code": reply.error_code,
                    "error": reply.error,
                },
            }
        )


def serve_stdio(
    server: ToolServer, read_line: Callable[[], str], write: Callable[[str], None]
) -> None:
    while True:
        line = read_line()
        if not line:
            return
        write(server.dispatch_json(line) + "\n")
