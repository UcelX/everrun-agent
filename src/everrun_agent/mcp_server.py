from __future__ import annotations

import os
import sys

from .service import ToolServer, serve_stdio


def build_server_from_env() -> ToolServer:
    clients = os.environ.get("EVERRUN_MUTATING_CLIENTS")
    return ToolServer(
        db_path=os.environ.get("EVERRUN_DB", ".everrun/everrun.db"),
        mutating_clients=tuple(filter(None, clients.split(","))) if clients else None,
        confirm_token=os.environ.get("EVERRUN_CONFIRM_TOKEN"),
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
