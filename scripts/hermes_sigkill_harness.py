#!/usr/bin/env python3
"""Opt-in real-Hermes SIGKILL harness. Never runs without two explicit safety gates."""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import time
from pathlib import Path

BOUNDARIES = ("after-start", "after-filesystem", "after-claim", "after-effect", "during-checkpoint")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True)
    parser.add_argument("--boundary", choices=BOUNDARIES, required=True)
    parser.add_argument("--workdir", type=Path, required=True)
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
    prompt = f"Run EverRun SIGKILL fixture boundary {args.boundary} in {args.workdir}"
    process = subprocess.Popen(["hermes", "--profile", args.profile, "chat", "-q", prompt])
    time.sleep(2)  # fixture emits durable boundary marker before this bounded kill window
    os.kill(process.pid, signal.SIGKILL)
    process.wait()
    print(json.dumps({"executed": True, "pid": process.pid, "boundary": args.boundary}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
