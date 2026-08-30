from __future__ import annotations

import json
from pathlib import Path

from everrun_agent.cli import EXIT_OK, EXIT_UNSAFE, main


def test_pin_declare_and_detect_drift_via_cli(tmp_path: Path, capsys) -> None:
    db = str(tmp_path / "everrun.db")
    main(["--db", db, "init", "m1", "Pinned mission", "--total", "2"])
    assert main(["--db", db, "pin-env", "m1", "dataset=v3", "model=opus"]) == EXIT_OK
    assert main(["--db", db, "declare-dep", "m1", "index", "dataset"]) == EXIT_OK
    capsys.readouterr()

    assert main(["--db", db, "check-env", "m1", "dataset=v3", "model=opus", "--json"]) == EXIT_OK
    clean = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert clean["safe"] is True and clean["changed"] == []

    assert (
        main(["--db", db, "check-env", "m1", "dataset=v4", "model=opus", "--json"]) == EXIT_UNSAFE
    )
    drifted = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert drifted["safe"] is False
    assert drifted["changed"] == ["dataset"]
    assert drifted["stale"] == ["index"]


def test_check_env_without_pin_is_reported_not_crashed(tmp_path: Path, capsys) -> None:
    db = str(tmp_path / "everrun.db")
    main(["--db", db, "init", "m1", "No pin", "--total", "1"])
    capsys.readouterr()
    assert main(["--db", db, "check-env", "m1", "dataset=v1", "--json"]) == EXIT_OK
    assert json.loads(capsys.readouterr().out.strip().splitlines()[-1])["pinned"] is False


def test_close_refuses_incomplete_mission_via_cli(tmp_path: Path, capsys) -> None:
    import pytest

    db = str(tmp_path / "everrun.db")
    main(["--db", db, "init", "m1", "Close guard", "--total", "3"])
    main(["--db", db, "complete-work", "m1", "a"])
    capsys.readouterr()
    with pytest.raises(ValueError, match="progress"):
        main(["--db", db, "close", "m1"])


def test_close_succeeds_when_target_reached(tmp_path: Path, capsys) -> None:
    db = str(tmp_path / "everrun.db")
    main(["--db", db, "init", "m1", "Close ok", "--total", "1"])
    main(["--db", db, "complete-work", "m1", "a"])
    capsys.readouterr()
    assert main(["--db", db, "close", "m1"]) == EXIT_OK
    assert json.loads(capsys.readouterr().out.strip())["closed"] is True
    assert main(["--db", db, "status", "m1", "--json"]) == EXIT_OK
    assert (
        json.loads(capsys.readouterr().out.strip().splitlines()[-1])["mode"] == "verified_complete"
    )
