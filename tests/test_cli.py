import json
from pathlib import Path

from relaycore.cli import main


def test_cli_mission_status_verify_export(tmp_path: Path, capsys):
    db = tmp_path / "relay.db"
    capsule = tmp_path / "m.rly"
    assert main(["--db", str(db), "init", "m1", "CLI mission", "--total", "2"]) == 0
    assert main(["--db", str(db), "complete-work", "m1", "a"]) == 0
    assert main(["--db", str(db), "status", "m1", "--json"]) == 0
    status = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert status["completed"] == 1 and status["next_safe_action"] == "continue_work"
    assert main(["--db", str(db), "verify", "m1"]) == 0
    assert main(["--db", str(db), "export", "m1", str(capsule)]) == 0 and capsule.exists()


def test_cli_demo_proves_no_duplicates(tmp_path: Path, capsys):
    assert main(["demo", "--workdir", str(tmp_path), "--total", "20", "--crash-at", "7"]) == 0
    data = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert data["duplicates"] == 0 and data["chain_valid"]
