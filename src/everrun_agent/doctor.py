from __future__ import annotations

import platform
import shutil
import sqlite3
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any

from .store import EverRunStore


def _check(ok: bool, detail: str, hint: str = "") -> dict[str, Any]:
    return {"ok": ok, "detail": detail, "hint": hint}


def run_doctor(
    *,
    state_dir: Path,
    agent: str = "auto",
    profile: str = "default",
) -> dict[str, Any]:
    checks: dict[str, dict[str, Any]] = {}
    checks["python"] = _check(
        sys.version_info >= (3, 11),
        f"Python {platform.python_version()}",
        "Install Python 3.11 or newer.",
    )

    state_error = ""
    try:
        state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        if sys.platform != "win32":
            state_dir.chmod(0o700)
            mode = stat.S_IMODE(state_dir.stat().st_mode)
            if mode != 0o700:
                state_error = f"expected mode 0700, got {mode:04o}"
    except OSError as exc:
        state_error = str(exc)
    checks["state_dir"] = _check(
        not state_error,
        str(state_dir) if not state_error else state_error,
        "Ensure the current user can create and chmod the EverRun state directory.",
    )

    db_error = ""
    db = state_dir / "everrun.db"
    if checks["state_dir"]["ok"]:
        try:
            with EverRunStore(db):
                pass
        except (OSError, sqlite3.Error, ValueError) as exc:
            db_error = str(exc)
    else:
        db_error = "state directory unavailable"
    checks["database"] = _check(
        not db_error,
        str(db) if not db_error else db_error,
        "Fix state storage permissions, then rerun `everrun doctor`.",
    )

    selected = agent
    if selected == "auto":
        selected = "hermes" if shutil.which("hermes") else "none"
    if selected not in {"none", "hermes"}:
        checks["agent"] = _check(False, selected, "Use --agent none or --agent hermes.")
    elif selected == "hermes":
        hermes = shutil.which("hermes")
        checks["hermes_cli"] = _check(
            hermes is not None,
            hermes or "not found",
            "Install Hermes Agent or run with --agent none.",
        )
        if hermes:
            probe = subprocess.run(
                [hermes, "--profile", profile, "mcp", "test", "everrun"],
                check=False,
                capture_output=True,
                text=True,
            )
            output = f"{probe.stdout}\n{probe.stderr}"
            connected = probe.returncode == 0 and "connected" in output.lower() and "13" in output
            checks["hermes_integration"] = _check(
                connected,
                "13 tools discovered" if connected else output.strip()[-500:],
                "Run `everrun integrate hermes --profile <profile>`.",
            )

    ready = all(item["ok"] for item in checks.values())
    return {
        "ready": ready,
        "version": "0.1.0",
        "agent": selected,
        "profile": profile,
        "state_dir": str(state_dir),
        "checks": checks,
    }
