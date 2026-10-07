from __future__ import annotations

import hashlib
import os
import sqlite3
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .store import EverRunStore


def _readonly_uri(path: Path) -> str:
    """Return a cross-platform SQLite read-only URI, including Windows drives."""

    return f"{path.resolve().as_uri()}?mode=ro"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _integrity(path: Path) -> None:
    try:
        with sqlite3.connect(_readonly_uri(path), uri=True) as conn:
            row = conn.execute("PRAGMA integrity_check").fetchone()
    except sqlite3.Error as exc:
        raise ValueError(f"database integrity check failed: {exc}") from exc
    if not row or row[0] != "ok":
        raise ValueError(f"database integrity check failed: {row[0] if row else 'no result'}")


def backup_database(source: str | Path, backup_dir: str | Path) -> dict[str, Any]:
    source_path = Path(source).expanduser().resolve()
    if not source_path.is_file():
        raise FileNotFoundError(source_path)
    destination_dir = Path(backup_dir).expanduser().resolve()
    destination_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name != "nt":
        destination_dir.chmod(0o700)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
    destination = destination_dir / f"everrun-{stamp}.db"
    fd, temporary_name = tempfile.mkstemp(prefix=".everrun-backup-", dir=destination_dir)
    os.close(fd)
    temporary = Path(temporary_name)
    try:
        with (
            sqlite3.connect(_readonly_uri(source_path), uri=True) as src,
            sqlite3.connect(temporary) as dst,
        ):
            src.backup(dst)
        _integrity(temporary)
        if os.name != "nt":
            temporary.chmod(0o600)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return {
        "path": str(destination),
        "sha256": _sha256(destination),
        "integrity": "ok",
        "created_at": datetime.now(UTC).isoformat(),
    }


def restore_database(
    backup: str | Path, target: str | Path, *, overwrite: bool = False
) -> dict[str, Any]:
    backup_path = Path(backup).expanduser().resolve()
    target_path = Path(target).expanduser().resolve()
    if not backup_path.is_file():
        raise FileNotFoundError(backup_path)
    if target_path.exists() and not overwrite:
        raise FileExistsError(f"refusing to overwrite existing database: {target_path}")
    _integrity(backup_path)
    target_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary_name = tempfile.mkstemp(prefix=".everrun-restore-", dir=target_path.parent)
    os.close(fd)
    temporary = Path(temporary_name)
    try:
        with (
            sqlite3.connect(_readonly_uri(backup_path), uri=True) as src,
            sqlite3.connect(temporary) as dst,
        ):
            src.backup(dst)
        _integrity(temporary)
        if os.name != "nt":
            temporary.chmod(0o600)
        os.replace(temporary, target_path)
    finally:
        temporary.unlink(missing_ok=True)
    return {"path": str(target_path), "sha256": _sha256(target_path), "integrity": "ok"}


def runtime_status(database: str | Path) -> dict[str, Any]:
    path = Path(database).expanduser().resolve()
    if not path.exists():
        return {
            "healthy": False,
            "database": {"path": str(path), "integrity": "missing"},
            "mission_counts": {},
            "missions": [],
        }
    try:
        _integrity(path)
        with EverRunStore(path) as store:
            missions = store.list_missions()
        counts = {"active": 0, "blocked": 0, "review-required": 0, "completed": 0}
        for mission in missions:
            status = str(mission.get("status", "active"))
            counts[status] = counts.get(status, 0) + 1
        return {
            "healthy": True,
            "database": {
                "path": str(path),
                "integrity": "ok",
                "bytes": path.stat().st_size,
            },
            "mission_counts": counts,
            "missions": missions,
        }
    except (sqlite3.Error, ValueError) as exc:
        return {
            "healthy": False,
            "database": {"path": str(path), "integrity": "failed", "error": str(exc)},
            "mission_counts": {},
            "missions": [],
        }
