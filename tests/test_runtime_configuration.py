from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from everrun_agent.runtime_config import resolve_database


def test_database_resolution_precedence_is_explicit_env_then_local(
    tmp_path: Path, monkeypatch: object
) -> None:
    local = tmp_path / ".everrun/everrun.db"
    monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
    monkeypatch.delenv("EVERRUN_DB", raising=False)  # type: ignore[attr-defined]
    assert resolve_database(None) == local

    managed = tmp_path / "managed/everrun.db"
    monkeypatch.setenv("EVERRUN_DB", str(managed))  # type: ignore[attr-defined]
    assert resolve_database(None) == managed
    explicit = tmp_path / "explicit.db"
    assert resolve_database(explicit) == explicit


def test_cli_uses_environment_database_from_any_working_directory(tmp_path: Path) -> None:
    managed = tmp_path / "managed/everrun.db"
    env = os.environ.copy()
    env["EVERRUN_DB"] = str(managed)
    first = subprocess.run(
        [sys.executable, "-m", "everrun_agent.cli", "init", "same-db", "canonical", "--total", "1"],
        cwd=tmp_path,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert first.returncode == 0, first.stderr
    other = tmp_path / "other"
    other.mkdir()
    second = subprocess.run(
        [sys.executable, "-m", "everrun_agent.cli", "list-missions", "--json"],
        cwd=other,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert second.returncode == 0, second.stderr
    assert "same-db" in second.stdout
    assert not (tmp_path / ".everrun").exists()
    assert not (other / ".everrun").exists()


def test_explicit_cli_database_overrides_environment(tmp_path: Path) -> None:
    env = os.environ.copy()
    env["EVERRUN_DB"] = str(tmp_path / "environment.db")
    explicit = tmp_path / "explicit.db"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "everrun_agent.cli",
            "--db",
            str(explicit),
            "init",
            "explicit",
            "wins",
        ],
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert explicit.exists()
    assert not (tmp_path / "environment.db").exists()
