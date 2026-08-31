from __future__ import annotations

import json
import sys
from pathlib import Path

import everrun_agent.hermes as hermes_integration
from everrun_agent.hermes import integrate_hermes, plan_hermes_integration
from everrun_agent.mcp_server import _unwrap
from everrun_agent.service import ToolReply


def test_hermes_dry_run_is_profile_local_and_non_mutating(tmp_path: Path) -> None:
    result = integrate_hermes("qa", hermes_home=tmp_path, dry_run=True)
    assert result["changed"] is False
    assert result["plan"]["db"] == str(tmp_path / "profiles/qa/everrun/everrun.db")
    assert not (tmp_path / "profiles/qa").exists()
    assert result["plan"]["skill"].endswith(
        "profiles/qa/skills/autonomous-ai-agents/everrun-lifecycle/SKILL.md"
    )


class _Completed:
    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_integrator_fails_if_hermes_test_returns_zero_but_server_is_missing(
    tmp_path: Path, monkeypatch: object
) -> None:
    monkeypatch.setattr(hermes_integration.shutil, "which", lambda _: "/usr/bin/hermes")  # type: ignore[attr-defined]
    calls: list[list[str]] = []

    def runner(args: list[str], **_: object) -> _Completed:
        calls.append(args)
        if "test" in args:
            return _Completed(stdout="Server 'everrun' not found in config")
        return _Completed(stdout="Cancelled")

    import pytest

    with pytest.raises(RuntimeError, match="not saved|handshake"):
        integrate_hermes("qa", hermes_home=tmp_path, runner=runner)
    assert calls
    skill = tmp_path / "profiles/qa/skills/autonomous-ai-agents/everrun-lifecycle/SKILL.md"
    assert not skill.exists()


def test_integrator_uses_noninteractive_enable_all_and_requires_discovery(
    tmp_path: Path, monkeypatch: object
) -> None:
    monkeypatch.setattr(hermes_integration.shutil, "which", lambda _: "/usr/bin/hermes")  # type: ignore[attr-defined]
    calls: list[list[str]] = []

    def runner(args: list[str], **kwargs: object) -> _Completed:
        calls.append(args)
        if "test" in args:
            return _Completed(stdout="✓ Connected (10ms)\n✓ Tools discovered: 13")
        assert kwargs.get("input") == "Y\nY\n"
        return _Completed(stdout="✓ Saved 'everrun' (13/13 tools enabled)")

    result = integrate_hermes("qa", hermes_home=tmp_path, runner=runner)
    assert result["verified"] is True
    assert result["tools_discovered"] == 13
    skill = tmp_path / "profiles/qa/skills/autonomous-ai-agents/everrun-lifecycle/SKILL.md"
    assert skill.exists()
    policy = skill.read_text(encoding="utf-8")
    assert "description:" in policy
    assert "mcp_everrun_everrun_list_missions" in policy
    assert skill.stat().st_mode & 0o777 == 0o644
    add = next(call for call in calls if "add" in call)
    assert add[add.index("--command") + 1] == sys.executable
    env_index = add.index("--env")
    assert add[env_index + 1 : env_index + 4] == [
        "EVERRUN_DB=" + str(tmp_path / "profiles/qa/everrun/everrun.db"),
        "EVERRUN_MUTATING_CLIENTS=hermes",
        "EVERRUN_TRANSPORT_CLIENT=hermes",
    ]
    assert add.count("--env") == 1
    assert add[-3:] == ["--args", "-m", "everrun_agent.mcp_server"]


def test_hermes_uninstall_removes_only_everrun_owned_skill(
    tmp_path: Path, monkeypatch: object
) -> None:
    monkeypatch.setattr(hermes_integration.shutil, "which", lambda _: "/usr/bin/hermes")  # type: ignore[attr-defined]
    skill = tmp_path / "profiles/qa/skills/autonomous-ai-agents/everrun-lifecycle/SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text(hermes_integration.lifecycle_skill_text(), encoding="utf-8")

    def runner(args: list[str], **_: object) -> _Completed:
        return _Completed(stdout="✓ Removed 'everrun' from config")

    result = integrate_hermes("qa", hermes_home=tmp_path, uninstall=True, runner=runner)
    assert result["removed"] is True
    assert not skill.exists()


def test_hermes_uninstall_preserves_user_modified_skill(
    tmp_path: Path, monkeypatch: object
) -> None:
    monkeypatch.setattr(hermes_integration.shutil, "which", lambda _: "/usr/bin/hermes")  # type: ignore[attr-defined]
    skill = tmp_path / "profiles/qa/skills/autonomous-ai-agents/everrun-lifecycle/SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("user-owned custom policy", encoding="utf-8")

    def runner(args: list[str], **_: object) -> _Completed:
        return _Completed(stdout="✓ Removed 'everrun' from config")

    result = integrate_hermes("qa", hermes_home=tmp_path, uninstall=True, runner=runner)
    assert result["skill_preserved"] is True
    assert skill.read_text(encoding="utf-8") == "user-owned custom policy"


def test_wheel_configuration_packages_lifecycle_skill() -> None:
    project = Path("pyproject.toml").read_text(encoding="utf-8")
    assert "src/everrun_agent/integrations/hermes/SKILL.md" in project


def test_repo_lifecycle_skill_matches_packaged_canonical_copy() -> None:
    canonical = Path("src/everrun_agent/integrations/hermes/SKILL.md").read_text(encoding="utf-8")
    convenience = Path("integrations/hermes/SKILL.md").read_text(encoding="utf-8")
    assert convenience == canonical


def test_lifecycle_policy_uses_native_tool_names_and_requires_natural_discovery() -> None:
    policy = hermes_integration.lifecycle_skill_text()
    assert "mcp_everrun_everrun_list_missions" in policy
    assert "mcp_everrun_everrun_start" in policy
    assert "mcp_everrun_everrun_claim_action" in policy
    assert "do not wait for the user to name EverRun" in policy


def test_mcp_error_preserves_structured_recovery_data() -> None:
    try:
        _unwrap(
            ToolReply(
                False,
                error_code="uncertain_action",
                error="redacted",
                recovery={"next_safe_action": "reconcile"},
            )
        )
    except ValueError as exc:
        payload = json.loads(str(exc))
    assert payload == {
        "code": "uncertain_action",
        "message": "redacted",
        "recovery": {"next_safe_action": "reconcile"},
    }


def test_mcp_dependency_is_pinned_to_supported_major() -> None:
    project = Path("pyproject.toml").read_text(encoding="utf-8")
    assert "mcp>=1,<2" in project
    assert plan_hermes_integration("default", Path("/tmp/home")).profile == "default"
