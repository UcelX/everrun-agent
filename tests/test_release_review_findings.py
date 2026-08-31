from __future__ import annotations

from pathlib import Path

import pytest

from everrun_agent import EverRunStore, Mission
from everrun_agent.hermes import integrate_hermes
from everrun_agent.models import Origin
from everrun_agent.service import ToolRequest, ToolServer


class _Completed:
    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_confirmation_audit_uses_authenticated_transport_identity(tmp_path: Path) -> None:
    db = tmp_path / "everrun.db"
    with EverRunStore(db) as store:
        store.create_mission(Mission("m1", "audit identity", 1))
        ticket = store.issue_confirm_ticket("m1")
    server = ToolServer(
        db,
        mutating_clients=("trusted-transport",),
        transport_client="trusted-transport",
    )
    reply = server.handle(
        ToolRequest(
            "everrun_confirm",
            {"mission_id": "m1", "ticket": ticket},
            client="spoofed-operator",
        )
    )
    assert reply.ok
    with EverRunStore(db) as store:
        event = store.events("m1")[-1]
    assert event.origin is Origin.HUMAN
    assert event.payload["confirmed_by"] == "trusted-transport"


def test_integrator_rolls_back_partial_config_when_handshake_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import everrun_agent.hermes as integration

    monkeypatch.setattr(integration.shutil, "which", lambda _: "/usr/bin/hermes")
    calls: list[list[str]] = []

    def runner(args: list[str], **_: object) -> _Completed:
        calls.append(args)
        if "test" in args:
            return _Completed(stdout="Server 'everrun' not found")
        if "remove" in args:
            return _Completed(stdout="Removed 'everrun'")
        return _Completed(stdout="Saved 'everrun' (13/13 tools enabled)")

    with pytest.raises(RuntimeError, match="handshake"):
        integrate_hermes("qa", hermes_home=tmp_path, runner=runner)
    assert any("remove" in call for call in calls)


def test_sigkill_harness_waits_for_boundary_and_reports_literal_signal() -> None:
    from scripts.hermes_sigkill_harness import build_report

    report = build_report(
        boundary="after-effect",
        returncode=-9,
        marker_reached=True,
        recovery={"mode": "reconcile", "chain_ok": True, "marker_count": 1},
    )
    assert report == {
        "boundary": "after-effect",
        "chain_ok": True,
        "executed": True,
        "marker_count": 1,
        "marker_reached": True,
        "mode_after_restart": "reconcile",
        "returncode": -9,
        "signal": "SIGKILL",
        "verified": True,
    }


def test_sigkill_harness_never_verifies_without_boundary_marker() -> None:
    from scripts.hermes_sigkill_harness import build_report

    report = build_report(
        boundary="after-effect",
        returncode=-9,
        marker_reached=False,
        recovery={"mode": "reconcile", "chain_ok": True, "marker_count": 1},
    )
    assert report["verified"] is False


def test_ci_mcp_major_gate_does_not_swallow_dependency_failure() -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "mcp>=2' || true" not in workflow
    assert "pip check" in workflow
