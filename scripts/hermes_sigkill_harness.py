#!/usr/bin/env python3
"""Opt-in, marker-driven real-Hermes SIGKILL recovery harness.

The harness never treats elapsed time as proof that a requested boundary was
reached. The Hermes fixture must create ``<workdir>/<boundary>.ready`` only after
its durable boundary is complete. The harness then sends literal SIGKILL,
observes return code -9, and queries EverRun from a fresh process.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

BOUNDARIES = ("after-start", "after-filesystem", "after-claim", "after-effect", "during-checkpoint")


def build_report(
    *,
    boundary: str,
    returncode: int,
    marker_reached: bool,
    recovery: dict[str, Any],
) -> dict[str, Any]:
    """Build a fail-closed machine report for one literal crash boundary."""

    mode = str(recovery.get("mode", "unknown"))
    chain_ok = bool(recovery.get("chain_ok", False))
    marker_count = int(recovery.get("marker_count", 0))
    verified = (
        marker_reached
        and returncode == -signal.SIGKILL
        and mode in {"reconcile", "request_review", "continue", "verified_complete"}
        and chain_ok
        and marker_count <= 1
    )
    return {
        "boundary": boundary,
        "chain_ok": chain_ok,
        "executed": True,
        "marker_count": marker_count,
        "marker_reached": marker_reached,
        "mode_after_restart": mode,
        "returncode": returncode,
        "signal": "SIGKILL" if returncode == -signal.SIGKILL else "unexpected",
        "verified": verified,
    }


def wait_for_marker(marker: Path, process: subprocess.Popen[str], timeout: int) -> bool:
    """Wait until the fixture proves its boundary, failing if it exits first."""

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if marker.is_file():
            return True
        if process.poll() is not None:
            return False
        time.sleep(0.1)
    return False


def _json_command(command: list[str]) -> dict[str, Any]:
    completed = subprocess.run(command, check=False, capture_output=True, text=True)
    if completed.returncode not in {0, 20}:
        raise RuntimeError(completed.stderr.strip() or completed.stdout.strip())
    return json.loads(completed.stdout.splitlines()[-1])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True)
    parser.add_argument("--boundary", choices=BOUNDARIES, required=True)
    parser.add_argument("--workdir", type=Path, required=True)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--mission-id", required=True)
    parser.add_argument("--marker-file", type=Path)
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--execute-destructive", action="store_true")
    args = parser.parse_args()
    if not args.execute_destructive or os.environ.get("EVERRUN_ALLOW_REAL_HERMES_SIGKILL") != "YES":
        print(
            json.dumps(
                {
                    "executed": False,
                    "reason": "requires flag and EVERRUN_ALLOW_REAL_HERMES_SIGKILL=YES",
                    "boundary": args.boundary,
                }
            )
        )
        return 2

    args.workdir.mkdir(parents=True, exist_ok=True)
    boundary_marker = args.workdir / f"{args.boundary}.ready"
    prompt = (
        f"Run EverRun mission {args.mission_id} until boundary {args.boundary}. "
        f"Only after that boundary is durably reached, create {boundary_marker}, then sleep 300. "
        "Do not continue or settle the mission after creating the marker."
    )
    process = subprocess.Popen(
        ["hermes", "--profile", args.profile, "chat", "-Q", "-q", prompt],
        text=True,
    )
    marker_reached = wait_for_marker(boundary_marker, process, args.timeout)
    if not marker_reached:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=10)
        report = build_report(
            boundary=args.boundary,
            returncode=int(process.returncode or 0),
            marker_reached=False,
            recovery={},
        )
        print(json.dumps(report, sort_keys=True))
        return 20

    os.kill(process.pid, signal.SIGKILL)
    returncode = process.wait()
    executable = Path(sys.executable).with_name("everrun")
    status = _json_command(
        [str(executable), "--db", str(args.db), "status", args.mission_id, "--json"]
    )
    verify = _json_command(
        [str(executable), "--db", str(args.db), "verify", args.mission_id, "--json"]
    )
    marker_file = args.marker_file
    marker_count = 0
    if marker_file is not None and marker_file.exists():
        marker_count = len(marker_file.read_text(encoding="utf-8").splitlines())
    report = build_report(
        boundary=args.boundary,
        returncode=returncode,
        marker_reached=True,
        recovery={
            "mode": status["mode"],
            "chain_ok": verify["ok"],
            "marker_count": marker_count,
        },
    )
    print(json.dumps(report, sort_keys=True))
    return 0 if report["verified"] else 20


if __name__ == "__main__":
    raise SystemExit(main())
