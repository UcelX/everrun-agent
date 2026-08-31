from __future__ import annotations

import os
import sys

from .service import ToolServer, serve_stdio


def build_server_from_env() -> ToolServer:
    """Build the stdio tool server from the environment.

    C3: an absent EVERRUN_MUTATING_CLIENTS used to grant every client full
    mutation. It now yields an EMPTY allowlist, so a forgotten variable makes the
    server read-only instead of wide open.
    """

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
    # C2: JSON-RPC `_meta.client` is attacker-controlled. A stdio server may
    # mutate only when identity is pinned to this transport or proven by a
    # per-client token. An allowlist alone is intentionally insufficient.
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


def _write(text: str) -> None:
    sys.stdout.write(text)
    sys.stdout.flush()


def main() -> int:
    server = build_server_from_env()
    serve_stdio(server, sys.stdin.readline, _write)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
