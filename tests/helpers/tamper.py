"""Out-of-band tampering helpers for integrity tests.

An attacker with filesystem access does NOT go through EverRunStore; they open
the SQLite file directly. These helpers model that threat honestly, which is why
they bypass the library API instead of asking the library to weaken itself.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path


def tamper(db_path: str | Path, *statements: str) -> None:
    """Execute raw SQL directly against the database file, bypassing the library."""

    connection = sqlite3.connect(str(db_path))
    try:
        for statement in statements:
            connection.execute(statement)
        connection.commit()
    finally:
        connection.close()


def drop_append_only_triggers(db_path: str | Path) -> None:
    tamper(
        db_path,
        "DROP TRIGGER IF EXISTS events_no_delete",
        "DROP TRIGGER IF EXISTS events_no_update",
    )


def delete_event(db_path: str | Path, mission_id: str, sequence: int) -> None:
    drop_append_only_triggers(db_path)
    tamper(db_path, f"DELETE FROM events WHERE mission_id='{mission_id}' AND sequence={sequence}")


def rewrite_event_payload(
    db_path: str | Path, mission_id: str, sequence: int, payload: str = "{}"
) -> None:
    drop_append_only_triggers(db_path)
    tamper(
        db_path,
        f"UPDATE events SET payload='{payload}' "
        f"WHERE mission_id='{mission_id}' AND sequence={sequence}",
    )
