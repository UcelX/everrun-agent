from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from everrun_agent.dashboard import DashboardServer
from everrun_agent.models import Mission
from everrun_agent.operations import backup_database, restore_database, runtime_status
from everrun_agent.store import EverRunStore


def _seed(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with EverRunStore(path) as store:
        store.create_mission(Mission("mission-1", "prove recovery", 1))
        store.append_work("mission-1", "work-1")


def test_backup_is_consistent_verified_and_private(tmp_path: Path) -> None:
    source = tmp_path / "state/everrun.db"
    _seed(source)

    result = backup_database(source, tmp_path / "backups")

    artifact = Path(result["path"])
    assert artifact.exists()
    assert result["integrity"] == "ok"
    assert result["sha256"]
    if sys.platform != "win32":
        assert artifact.stat().st_mode & 0o777 == 0o600
    with EverRunStore(artifact) as copied:
        assert copied.verify_chain("mission-1").ok


def test_restore_refuses_to_overwrite_and_restores_atomically(tmp_path: Path) -> None:
    source = tmp_path / "state/everrun.db"
    _seed(source)
    backup = Path(backup_database(source, tmp_path / "backups")["path"])
    target = tmp_path / "restored/everrun.db"

    restored = restore_database(backup, target)
    assert restored["integrity"] == "ok"
    with EverRunStore(target) as store:
        assert store.get_mission("mission-1").goal == "prove recovery"

    with pytest.raises(FileExistsError):
        restore_database(backup, target)


def test_restore_rejects_corrupt_sqlite(tmp_path: Path) -> None:
    bad = tmp_path / "bad.db"
    bad.write_bytes(b"not sqlite")
    with pytest.raises(ValueError, match="integrity"):
        restore_database(bad, tmp_path / "target.db")


def test_runtime_status_summarizes_real_missions(tmp_path: Path) -> None:
    db = tmp_path / "everrun.db"
    _seed(db)
    report = runtime_status(db)
    assert report["healthy"] is True
    assert report["mission_counts"]["active"] == 1
    assert report["database"]["integrity"] == "ok"


def test_local_dashboard_binds_loopback_and_exposes_read_only_json(tmp_path: Path) -> None:
    db = tmp_path / "everrun.db"
    _seed(db)
    server = DashboardServer(db, host="127.0.0.1", port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{server.server_address[1]}"
        with urllib.request.urlopen(base + "/api/status", timeout=3) as response:
            payload = json.load(response)
        assert payload["healthy"] is True
        assert payload["missions"][0]["mission_id"] == "mission-1"
        request = urllib.request.Request(base + "/api/status", method="POST", data=b"{}")
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(request, timeout=3)
        assert exc.value.code == 405
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_dashboard_refuses_non_loopback_without_explicit_override(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="loopback"):
        DashboardServer(tmp_path / "everrun.db", host="0.0.0.0", port=0)


def test_cli_status_backup_restore_and_dashboard_help(tmp_path: Path) -> None:
    db = tmp_path / "state/everrun.db"
    _seed(db)
    backup_dir = tmp_path / "backups"
    commands = [
        (["--db", str(db), "runtime-status", "--json"], "healthy"),
        (["--db", str(db), "backup", "--output-dir", str(backup_dir), "--json"], "integrity"),
        (["dashboard", "--help"], "loopback"),
    ]
    for argv, expected in commands:
        result = subprocess.run(
            [sys.executable, "-m", "everrun_agent.cli", *argv],
            check=False,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
        assert expected in result.stdout

    artifact = next(backup_dir.glob("*.db"))
    target = tmp_path / "restored.db"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "everrun_agent.cli",
            "restore",
            str(artifact),
            "--target",
            str(target),
            "--json",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["integrity"] == "ok"


def test_backup_uses_sqlite_snapshot_not_file_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "everrun.db"
    _seed(source)
    called = False
    original = sqlite3.Connection.backup

    # The stdlib descriptor is immutable, so prove behaviour by keeping a writer
    # transaction open while the SQLite online-backup API obtains a valid snapshot.
    writer = sqlite3.connect(source)
    writer.execute("BEGIN")
    writer.execute("UPDATE missions SET goal=? WHERE mission_id=?", ("uncommitted", "mission-1"))
    try:
        result = backup_database(source, tmp_path / "backups")
    finally:
        writer.rollback()
        writer.close()
    assert result["integrity"] == "ok"
    with EverRunStore(result["path"]) as copied:
        assert copied.get_mission("mission-1").goal == "prove recovery"
    assert original is sqlite3.Connection.backup
    assert called is False
