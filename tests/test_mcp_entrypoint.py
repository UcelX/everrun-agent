from __future__ import annotations

import io
import json
from pathlib import Path

from everrun_agent.mcp_server import build_server_from_env
from everrun_agent.service import serve_stdio


def test_stdio_loop_serves_requests_and_stops_at_eof(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("EVERRUN_DB", str(tmp_path / "everrun.db"))
    monkeypatch.setenv("EVERRUN_MUTATING_CLIENTS", "agent")
    server = build_server_from_env()
    lines = iter(
        [
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}) + "\n",
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {
                        "name": "everrun_start",
                        "arguments": {"mission_id": "m1", "goal": "stdio", "total": 1},
                    },
                    "_meta": {"client": "agent"},
                }
            )
            + "\n",
            "",
        ]
    )
    out = io.StringIO()
    serve_stdio(server, lambda: next(lines), out.write)
    responses = [json.loads(line) for line in out.getvalue().strip().splitlines()]
    assert responses[0]["result"]["tools"]
    assert responses[1]["result"]["ok"] is True


def test_unauthorized_client_is_rejected_over_jsonrpc(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("EVERRUN_DB", str(tmp_path / "everrun.db"))
    monkeypatch.setenv("EVERRUN_MUTATING_CLIENTS", "agent")
    server = build_server_from_env()
    payload = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "everrun_start",
                "arguments": {"mission_id": "m2", "goal": "x", "total": 1},
            },
            "_meta": {"client": "intruder"},
        }
    )
    response = json.loads(server.dispatch_json(payload))
    assert response["error"]["code"] == -32001
