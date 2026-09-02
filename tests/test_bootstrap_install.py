from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from everrun_agent.doctor import run_doctor


def test_doctor_reports_core_install_ready(tmp_path: Path) -> None:
    report = run_doctor(state_dir=tmp_path / "state", agent="none")
    assert report["ready"] is True
    assert report["agent"] == "none"
    assert report["checks"]["python"]["ok"] is True
    assert report["checks"]["state_dir"]["ok"] is True
    assert report["checks"]["database"]["ok"] is True


def test_doctor_fails_closed_for_missing_requested_agent(
    tmp_path: Path, monkeypatch: object
) -> None:
    monkeypatch.setenv("PATH", str(tmp_path))  # type: ignore[attr-defined]
    report = run_doctor(state_dir=tmp_path / "state", agent="hermes", profile="default")
    assert report["ready"] is False
    assert report["checks"]["hermes_cli"]["ok"] is False
    assert report["checks"]["hermes_cli"]["hint"]


def test_cli_doctor_emits_machine_readable_json(tmp_path: Path) -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "everrun_agent.cli",
            "doctor",
            "--agent",
            "none",
            "--state-dir",
            str(tmp_path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0
    payload = json.loads(completed.stdout)
    assert payload["ready"] is True


@pytest.mark.skipif(sys.platform == "win32", reason="install.sh targets POSIX servers")
def test_install_script_bootstraps_isolated_prefix(tmp_path: Path) -> None:
    prefix = tmp_path / "everrun"
    env = os.environ.copy()
    env["EVERRUN_SKIP_AGENT_INTEGRATION"] = "1"
    completed = subprocess.run(
        ["bash", "install.sh", "--prefix", str(prefix), "--agent", "none", "--non-interactive"],
        check=False,
        capture_output=True,
        text=True,
        env=env,
        timeout=180,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert (prefix / "venv/bin/everrun").exists()
    report = json.loads((prefix / "install-report.json").read_text(encoding="utf-8"))
    assert report["ready"] is True
    assert report["agent"] == "none"

    second = subprocess.run(
        ["bash", "install.sh", "--prefix", str(prefix), "--agent", "none", "--non-interactive"],
        check=False,
        capture_output=True,
        text=True,
        env=env,
        timeout=180,
    )
    assert second.returncode == 0, second.stdout + second.stderr
    assert json.loads((prefix / "install-report.json").read_text(encoding="utf-8"))["ready"] is True


@pytest.mark.skipif(sys.platform == "win32", reason="install.sh targets POSIX servers")
def test_install_script_supports_safe_uninstall(tmp_path: Path) -> None:
    prefix = tmp_path / "everrun"
    subprocess.run(
        ["bash", "install.sh", "--prefix", str(prefix), "--agent", "none", "--non-interactive"],
        check=True,
        capture_output=True,
        text=True,
        timeout=180,
    )
    persistent = prefix / "state/keep.txt"
    persistent.parent.mkdir(parents=True, exist_ok=True)
    persistent.write_text("mission-state", encoding="utf-8")
    removed = subprocess.run(
        [
            "bash",
            "install.sh",
            "--prefix",
            str(prefix),
            "--agent",
            "none",
            "--uninstall",
            "--non-interactive",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert removed.returncode == 0
    assert not (prefix / "venv").exists()
    assert persistent.read_text(encoding="utf-8") == "mission-state"
