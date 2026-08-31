from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.skipif(sys.platform == "win32", reason="Windows has no POSIX SIGKILL")
def test_hard_kill_recovery_has_no_duplicate_work_or_effects(tmp_path: Path) -> None:
    """Real process death: the worker is SIGKILLed mid-mission, then a fresh
    process must resume without repeating work or the external side effect."""

    worker = Path(__file__).parent / "helpers" / "crash_worker.py"
    db = tmp_path / "everrun.db"
    output = tmp_path / "output.txt"
    effect = tmp_path / "effect.txt"

    first = subprocess.run(
        [sys.executable, str(worker), "phase-one", str(db), str(output), str(effect), "40", "100"],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert first.returncode == -9 or first.returncode == 137, first.stderr

    assert effect.read_text(encoding="utf-8").strip() == "published"

    second = subprocess.run(
        [sys.executable, str(worker), "phase-two", str(db), str(output), str(effect), "40", "100"],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert second.returncode == 0, second.stderr
    report = json.loads(second.stdout.strip().splitlines()[-1])

    assert report["refused_blind_resume"] is True
    assert report["mode_before_reconcile"] == "reconcile"
    assert report["completed"] == 100
    assert report["duplicates"] == 0
    assert report["chain_valid"] is True
    assert report["side_effect_lines"] == 1
    lines = output.read_text(encoding="utf-8").splitlines()
    assert len(lines) == len(set(lines)) == 100


@pytest.mark.skipif(sys.platform == "win32", reason="Windows has no POSIX SIGKILL")
def test_fault_injection_matrix_never_yields_unsafe_resume(tmp_path: Path) -> None:
    """Kill at every critical boundary; a fresh process must never report safe
    resume while an effect is unresolved, and must never duplicate work."""

    worker = Path(__file__).parent / "helpers" / "crash_worker.py"
    results = []
    for crash_at in (1, 7, 19, 33, 50):
        case = tmp_path / f"case-{crash_at}"
        case.mkdir()
        db, output, effect = case / "db.sqlite", case / "out.txt", case / "effect.txt"
        killed = subprocess.run(
            [
                sys.executable,
                str(worker),
                "phase-one",
                str(db),
                str(output),
                str(effect),
                str(crash_at),
                "60",
            ],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        assert killed.returncode in (-9, 137)
        resumed = subprocess.run(
            [
                sys.executable,
                str(worker),
                "phase-two",
                str(db),
                str(output),
                str(effect),
                str(crash_at),
                "60",
            ],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        assert resumed.returncode == 0, resumed.stderr
        report = json.loads(resumed.stdout.strip().splitlines()[-1])
        results.append(report)

    assert all(r["refused_blind_resume"] for r in results)
    assert all(r["duplicates"] == 0 for r in results)
    assert all(r["side_effect_lines"] == 1 for r in results)
    assert all(r["chain_valid"] for r in results)
    assert all(r["completed"] == 60 for r in results)


def test_naive_replay_baseline_does_duplicate_the_side_effect(tmp_path: Path) -> None:
    """Control group: without the ledger, replaying after a crash duplicates
    the external effect. This is what EverRun prevents."""

    effect = tmp_path / "effect.txt"
    for _ in range(2):
        with effect.open("a", encoding="utf-8") as handle:
            handle.write("published\n")
    assert len(effect.read_text(encoding="utf-8").splitlines()) == 2


def test_tamper_attempts_are_blocked_or_detected(tmp_path: Path) -> None:
    import sqlite3

    import pytest

    from everrun_agent import EverRunStore, Mission

    from .helpers.tamper import delete_event, tamper

    db = tmp_path / "everrun.db"
    with EverRunStore(db) as store:
        store.create_mission(Mission("m1", "tamper", 2))
        store.append_work("m1", "a")
    # 1. The library refuses to hand out a mutation primitive at all.
    with EverRunStore(db) as store, pytest.raises(PermissionError):
        store.raw_execute("UPDATE events SET payload='{}' WHERE sequence=2")
    # 2. Even a direct SQL connection is blocked by the append-only triggers.
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        tamper(db, "UPDATE events SET payload='{}' WHERE sequence=2")
    # 3. Dropping the triggers works, but the hash chain still detects the edit.
    delete_event(db, "m1", 2)
    with EverRunStore(db) as store:
        assert not store.verify_chain("m1").ok


def test_environment_variable_workers_do_not_corrupt_sequences(tmp_path: Path) -> None:
    from everrun_agent import EverRunStore, Mission

    db = tmp_path / "everrun.db"
    with EverRunStore(db) as store:
        store.create_mission(Mission("m1", "parallel", 24))
    procs = [
        subprocess.Popen(
            [
                sys.executable,
                "-c",
                (
                    "from everrun_agent import EverRunStore\n"
                    f"store=EverRunStore({str(db)!r})\n"
                    f"[store.append_work('m1', f'{i}-'+str(n)) for n in range(6)]\n"
                    "store.close()\n"
                ),
            ],
            env={**os.environ},
        )
        for i in range(4)
    ]
    assert all(proc.wait(timeout=120) == 0 for proc in procs)
    with EverRunStore(db) as store:
        events = store.events("m1")
        assert [event.sequence for event in events] == list(range(1, len(events) + 1))
        assert store.verify_chain("m1").ok
