from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class IntegrationPlan:
    profile: str
    state_dir: str
    db: str
    command: tuple[str, ...]
    env: dict[str, str]
    skill: str


def lifecycle_skill_text() -> str:
    resource = Path(__file__).parent / "integrations" / "hermes" / "SKILL.md"
    return resource.read_text(encoding="utf-8")


def _skill_digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def plan_hermes_integration(profile: str, hermes_home: Path | None = None) -> IntegrationPlan:
    """Build a profile-isolated, transport-pinned integration plan without side effects."""
    if not profile or any(
        char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
        for char in profile
    ):
        raise ValueError("invalid Hermes profile name")
    home = hermes_home or Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))
    profile_home = home if profile == "default" else home / "profiles" / profile
    state = profile_home / "everrun"
    skill = profile_home / "skills" / "autonomous-ai-agents" / "everrun-lifecycle" / "SKILL.md"
    return IntegrationPlan(
        profile,
        str(state),
        str(state / "everrun.db"),
        (sys.executable, "-m", "everrun_agent.mcp_server"),
        {
            "EVERRUN_DB": str(state / "everrun.db"),
            "EVERRUN_MUTATING_CLIENTS": "hermes",
            "EVERRUN_TRANSPORT_CLIENT": "hermes",
        },
        str(skill),
    )


def integrate_hermes(
    profile: str,
    *,
    hermes_home: Path | None = None,
    dry_run: bool = False,
    uninstall: bool = False,
    runner: Any = subprocess.run,
) -> dict[str, Any]:
    """Install/uninstall only EverRun's named MCP entry; dry-run is always non-mutating."""
    plan = plan_hermes_integration(profile, hermes_home)
    if dry_run:
        return {"changed": False, "dry_run": True, "uninstall": uninstall, "plan": asdict(plan)}
    if shutil.which("hermes") is None:
        raise RuntimeError("Hermes CLI not found; install Hermes before integration")
    state = Path(plan.state_dir)
    skill = Path(plan.skill)
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    state.chmod(0o700)
    args = ["hermes", "--profile", profile, "mcp", "remove" if uninstall else "add", "everrun"]
    if not uninstall:
        args.extend(["--command", plan.command[0]])
        args.append("--env")
        args.extend(f"{key}={value}" for key, value in plan.env.items())
        args.extend(["--args", *plan.command[1:]])
    completed = runner(
        args,
        check=False,
        capture_output=True,
        text=True,
        input=None if uninstall else "Y\nY\n",
    )
    combined = f"{completed.stdout}\n{completed.stderr}"
    if completed.returncode != 0 and not (uninstall and "not found" in combined.lower()):
        raise RuntimeError(f"Hermes MCP configuration failed: {combined.strip()}")
    if not uninstall and "saved 'everrun'" not in combined.lower():
        raise RuntimeError(f"Hermes MCP configuration was not saved: {combined.strip()}")
    skill_preserved = False
    policy = lifecycle_skill_text()
    if uninstall:
        if skill.exists() and _skill_digest(skill.read_text(encoding="utf-8")) == _skill_digest(
            policy
        ):
            skill.unlink()
        elif skill.exists():
            skill_preserved = True
    else:
        skill.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
        skill.write_text(policy, encoding="utf-8")
        skill.chmod(0o644)
    tools_discovered = 0
    if not uninstall:
        probe = runner(
            ["hermes", "--profile", profile, "mcp", "test", "everrun"],
            check=False,
            capture_output=True,
            text=True,
        )
        probe_output = f"{probe.stdout}\n{probe.stderr}"
        match = re.search(r"Tools discovered:\s*(\d+)", probe_output)
        if probe.returncode != 0 or "connected" not in probe_output.lower() or not match:
            rollback = runner(
                ["hermes", "--profile", profile, "mcp", "remove", "everrun"],
                check=False,
                capture_output=True,
                text=True,
                input=None,
            )
            rollback_output = f"{rollback.stdout}\n{rollback.stderr}".strip()
            suffix = ""
            if rollback.returncode != 0:
                suffix = f"; rollback also failed: {rollback_output}"
            raise RuntimeError(f"EverRun handshake failed: {probe_output.strip()}{suffix}")
        tools_discovered = int(match.group(1))
    return {
        "changed": completed.returncode == 0,
        "removed": uninstall,
        "profile": profile,
        "state_dir": str(state),
        "verified": not uninstall,
        "tools_discovered": tools_discovered,
        "skill": str(skill),
        "skill_preserved": skill_preserved,
    }


def render_plan(plan: IntegrationPlan) -> str:
    return json.dumps(asdict(plan), sort_keys=True)
