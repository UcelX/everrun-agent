from __future__ import annotations

import os
from pathlib import Path

LEGACY_DATABASE = Path(".everrun/everrun.db")


def resolve_database(explicit: str | Path | None = None) -> Path:
    """Resolve one database path with explicit > environment > local precedence.

    Managed installations export ``EVERRUN_DB`` from their launchers, which makes
    CLI, MCP, dashboard, backup, and restore independent of the current working
    directory. Source checkouts retain the historical project-local default.
    """

    if explicit is not None:
        return Path(explicit).expanduser()
    configured = os.environ.get("EVERRUN_DB")
    if configured:
        return Path(configured).expanduser()
    return LEGACY_DATABASE.resolve()
