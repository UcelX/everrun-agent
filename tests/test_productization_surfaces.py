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
