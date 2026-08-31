import json
from pathlib import Path

import pytest

from everrun_agent.cli import main
from everrun_agent.mcp_server import main as mcp_main


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


def test_cli_demo_accepts_root_alias_and_explicit_json(tmp_path: Path, capsys):
    assert main(["demo", "--root", str(tmp_path), "--total", "5", "--crash-at", "2", "--json"]) == 0
    data = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert data == {
        "chain_valid": True,
        "completed": 5,
        "duplicates": 0,
        "side_effect_count": 1,
        "unique_outputs": 5,
    }


def test_mcp_cli_help_does_not_start_server(capsys):
    with pytest.raises(SystemExit) as exc:
        mcp_main(["--help"])
    assert exc.value.code == 0
    output = capsys.readouterr()
    assert "EverRun Agent MCP stdio server" in output.out
    assert "EVERRUN_MUTATING_CLIENTS is unset" not in output.err
