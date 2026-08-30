from __future__ import annotations

import json
from pathlib import Path

from everrun_agent.cli import EXIT_OK, EXIT_UNSAFE, main


def test_full_cli_lifecycle(tmp_path: Path, capsys) -> None:
    db = str(tmp_path / "everrun.db")
    assert main(["--db", db, "init", "m1", "Ship release", "--total", "2"]) == EXIT_OK
    assert main(["--db", db, "record-decision", "m1", "d1", "keep it local"]) == EXIT_OK
    assert main(["--db", db, "complete-work", "m1", "a"]) == EXIT_OK
    assert main(["--db", db, "checkpoint", "m1", "--reason", "milestone"]) == EXIT_OK
    assert main(["--db", db, "status", "m1", "--json"]) == EXIT_OK
    status = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert status["completed"] == 1 and status["mode"] == "continue"
    assert main(["--db", db, "resume", "m1", "--json"]) == EXIT_OK
    assert main(["--db", db, "briefing", "m1", "--context-tokens", "500"]) == EXIT_OK
    briefing = capsys.readouterr().out
    assert "GOAL" in briefing and "NEXT SAFE ACTION" in briefing


def test_external_agent_work_forces_review_and_confirm_clears_it(tmp_path: Path, capsys) -> None:
    db = str(tmp_path / "everrun.db")
    main(["--db", db, "init", "m1", "External", "--total", "1"])
    main(["--db", db, "complete-work", "m1", "a", "--external-agent"])
    assert main(["--db", db, "status", "m1", "--json"]) == EXIT_UNSAFE
    assert json.loads(capsys.readouterr().out.strip().splitlines()[-1])["mode"] == "request_review"
    assert main(["--db", db, "confirm", "m1"]) == EXIT_OK
    assert main(["--db", db, "status", "m1", "--json"]) == EXIT_OK
    assert (
        json.loads(capsys.readouterr().out.strip().splitlines()[-1])["mode"] == "verified_complete"
    )


def test_corrupt_chain_blocks_status_with_unsafe_exit(tmp_path: Path, capsys) -> None:
    from everrun_agent import EverRunStore

    db = tmp_path / "everrun.db"
    main(["--db", str(db), "init", "m1", "Corrupt", "--total", "1"])
    main(["--db", str(db), "complete-work", "m1", "a"])
    with EverRunStore(db) as store:
        store.raw_execute("DROP TRIGGER events_no_delete")
        store.raw_execute("DELETE FROM events WHERE sequence=2")
    assert main(["--db", str(db), "status", "m1", "--json"]) == EXIT_UNSAFE
    assert json.loads(capsys.readouterr().out.strip().splitlines()[-1])["ok"] is False


def test_capsule_sign_and_verify_via_cli(tmp_path: Path, capsys) -> None:
    db = str(tmp_path / "everrun.db")
    key = tmp_path / "signer.key"
    capsule = tmp_path / "mission.rly"
    main(["--db", db, "init", "m1", "Signed", "--total", "1"])
    main(["--db", db, "complete-work", "m1", "a"])
    assert main(["--db", db, "keygen", "--out", str(key)]) == EXIT_OK
    assert main(["--db", db, "export", "m1", str(capsule)]) == EXIT_OK
    assert (
        main(["--db", db, "sign", str(capsule), "--key", str(key), "--signer", "ucel"]) == EXIT_OK
    )
    capsys.readouterr()
    assert (
        main(["--db", db, "verify-capsule", str(capsule), "--key", str(key), "--signer", "ucel"])
        == EXIT_OK
    )
    assert json.loads(capsys.readouterr().out.strip())["verified"] is True


def test_handoff_and_hooks_via_cli(tmp_path: Path, capsys) -> None:
    db = str(tmp_path / "everrun.db")
    config = tmp_path / "hooks.json"
    main(["--db", db, "init", "m1", "Handoff", "--total", "2"])
    main(["--db", db, "complete-work", "m1", "a"])
    assert main(["--db", db, "handoff", "m1", "hermes"]) == EXIT_OK
    assert json.loads(capsys.readouterr().out.strip().splitlines()[-1])["to_agent"] == "hermes"
    assert main(["--db", db, "hooks", "install", "claude-code", "--config", str(config)]) == EXIT_OK
    assert "pre_tool_use" in json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert (
        main(["--db", db, "hooks", "uninstall", "claude-code", "--config", str(config)]) == EXIT_OK
    )


def test_actions_command_lists_uncertain_effects(tmp_path: Path, capsys) -> None:
    from everrun_agent import ActionLedger, EverRunStore

    db = tmp_path / "everrun.db"
    main(["--db", str(db), "init", "m1", "Actions", "--total", "1"])
    with EverRunStore(db) as store:
        claim = ActionLedger(store, "m1").claim("deploy", {"env": "prod"})
    assert main(["--db", str(db), "actions", "m1", "--json"]) == EXIT_UNSAFE
    listed = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert listed["uncertain"][0]["action_key"] == claim.key
    assert main(["--db", str(db), "reconcile", "m1", claim.key, "--occurred"]) == EXIT_OK
    assert main(["--db", str(db), "status", "m1", "--json"]) == EXIT_OK
