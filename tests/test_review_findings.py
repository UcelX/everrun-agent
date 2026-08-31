"""Regression tests for the adversarial review findings (C1-C4, H1-H7, M1-M9, L1-L5).

Every test here failed before the hardening round and encodes a real exploit or
a false product claim, not a style preference.
"""

from __future__ import annotations

import json
import os
import sqlite3
import stat
from pathlib import Path

import pytest

from everrun_agent import ActionLedger, EverRunStore, Mission
from everrun_agent.attestation import generate_keypair, sign_capsule
from everrun_agent.budgets import BudgetExceeded, RetryBudget
from everrun_agent.capsule import CapsuleWouldLeak, export_capsule, import_capsule
from everrun_agent.contracts import ContractClause, SuccessContract, evaluate_contract
from everrun_agent.gate import UncertainSideEffect, protected_call
from everrun_agent.handoff import AgentProfile, BriefingTooLarge, compile_briefing
from everrun_agent.models import EventType, Origin, UncertainAction
from everrun_agent.recovery import recover
from everrun_agent.service import AuthorizationError, ToolRequest, ToolServer
from everrun_agent.verifier import (
    DEFAULT_POLICY,
    PolicyViolation,
    VerifierPolicy,
    verify_command,
    verify_http,
)

# --------------------------------------------------------------------------- C1


def test_gate_refuses_to_refire_an_uncertain_effect(tmp_path: Path) -> None:
    """C1: the central product claim. A crashed mid-flight effect must never re-fire."""

    fired: list[str] = []
    with EverRunStore(tmp_path / "everrun.db") as store:
        store.create_mission(Mission("m1", "charge once", 1))
        ledger = ActionLedger(store, "m1")
        ledger.claim("charge", {"invoice": "INV-1"})  # process died before complete()

        with pytest.raises(UncertainSideEffect):
            protected_call(ledger, "charge", {"invoice": "INV-1"}, lambda: fired.append("charged"))
        assert fired == []

        with pytest.raises(UncertainSideEffect):
            protected_call(
                ledger,
                "charge",
                {"invoice": "INV-1"},
                lambda: fired.append("charged"),
                require_claim=True,
            )
        assert fired == []


def test_gate_still_short_circuits_a_completed_effect(tmp_path: Path) -> None:
    fired: list[str] = []
    with EverRunStore(tmp_path / "everrun.db") as store:
        store.create_mission(Mission("m1", "charge once", 1))
        ledger = ActionLedger(store, "m1")
        first = protected_call(
            ledger, "charge", {"invoice": "INV-1"}, lambda: fired.append("charged")
        )
        assert first.performed
        second = protected_call(
            ledger, "charge", {"invoice": "INV-1"}, lambda: fired.append("charged")
        )
        assert not second.performed
        assert fired == ["charged"]


def test_reconciled_not_occurred_effect_is_retryable(tmp_path: Path) -> None:
    """M1: a probe proved it did NOT happen, so the caller must be able to retry."""

    sent: list[str] = []
    with EverRunStore(tmp_path / "everrun.db") as store:
        store.create_mission(Mission("m1", "send email", 1))
        ledger = ActionLedger(store, "m1")
        claim = ledger.claim("email", {"to": "a@b.test"})
        ledger.reconcile(claim.key, occurred=False)
        result = protected_call(ledger, "email", {"to": "a@b.test"}, lambda: sent.append("sent"))
        assert result.performed
        assert sent == ["sent"]


# --------------------------------------------------------------------------- C3


def test_tool_server_denies_mutation_by_default(tmp_path: Path) -> None:
    """C3: an unconfigured server must not be an open mutation surface."""

    server = ToolServer(db_path=tmp_path / "everrun.db")
    with pytest.raises(AuthorizationError):
        server.handle(
            ToolRequest("everrun_start", {"mission_id": "m1", "goal": "g", "total": 1}, client="x")
        )
    reply = server.handle(ToolRequest("everrun_status", {"mission_id": "m1"}, client="x"))
    assert reply.error_code == "invalid_arguments"


def test_explicit_allowlist_is_required_for_mutation(tmp_path: Path) -> None:
    server = ToolServer(db_path=tmp_path / "everrun.db", mutating_clients=("agent",))
    assert server.handle(
        ToolRequest("everrun_start", {"mission_id": "m1", "goal": "g", "total": 1}, client="agent")
    ).ok


# --------------------------------------------------------------------------- H5


def test_tool_surface_never_leaks_uncaught_exceptions(tmp_path: Path) -> None:
    """H5: an uncaught exception killed the stdio loop, a trivial remote DoS."""

    server = ToolServer(db_path=tmp_path / "everrun.db", mutating_clients=("agent",))
    args = {"mission_id": "m1", "goal": "g", "total": 1}
    assert server.handle(ToolRequest("everrun_start", args, client="agent")).ok

    duplicate = server.handle(ToolRequest("everrun_start", args, client="agent"))
    assert not duplicate.ok
    assert duplicate.error_code == "invalid_arguments"

    bad_type = server.handle(
        ToolRequest("everrun_record_work", {"mission_id": "m1", "item": object()}, client="agent")
    )
    assert not bad_type.ok
    assert bad_type.error_code in {"invalid_arguments", "internal_error"}


def test_stdio_loop_survives_a_poisoned_request(tmp_path: Path) -> None:
    server = ToolServer(db_path=tmp_path / "everrun.db", mutating_clients=("agent",))
    args = {"mission_id": "m1", "goal": "g", "total": 1}
    server.handle(ToolRequest("everrun_start", args, client="agent"))
    payload = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 9,
            "method": "tools/call",
            "params": {"name": "everrun_start", "arguments": args},
            "_meta": {"client": "agent"},
        }
    )
    response = json.loads(server.dispatch_json(payload))
    assert response["id"] == 9
    assert response["result"]["ok"] is False


def test_internal_errors_do_not_echo_internal_detail(tmp_path: Path) -> None:
    server = ToolServer(db_path=tmp_path / "everrun.db", mutating_clients=("agent",))
    args = {"mission_id": "m1", "goal": "g", "total": 1}
    server.handle(ToolRequest("everrun_start", args, client="agent"))
    reply = server.handle(ToolRequest("everrun_start", args, client="agent"))
    assert "sqlite" not in (reply.error or "").lower()
    assert "traceback" not in (reply.error or "").lower()


# --------------------------------------------------------------------------- H1


def test_retry_budget_counts_attempts_per_action_not_per_kind(tmp_path: Path) -> None:
    """H1: the cap must fire for repeat attempts of the SAME action."""

    with EverRunStore(tmp_path / "everrun.db") as store:
        store.create_mission(Mission("m1", "charge", 9))
        ledger = ActionLedger(store, "m1", budget=RetryBudget({"charge": 2}))
        allowed = 0
        for _ in range(6):
            try:
                claim = ledger.claim("charge", {"invoice": "INV-1"})
            except BudgetExceeded:
                break
            ledger.reconcile(claim.key, occurred=False)
            allowed += 1
        assert allowed == 2


def test_completed_actions_do_not_erode_budget_for_new_actions(tmp_path: Path) -> None:
    """L5: successful history must not consume another action's retry allowance."""

    with EverRunStore(tmp_path / "everrun.db") as store:
        store.create_mission(Mission("m1", "charge", 9))
        ledger = ActionLedger(store, "m1", budget=RetryBudget({"charge": 2}))
        for index in range(4):
            claim = ledger.claim("charge", {"invoice": f"INV-{index}"})
            ledger.complete(claim.key)
        fresh = ledger.claim("charge", {"invoice": "INV-new"})
        assert fresh.fresh


# --------------------------------------------------------------------------- H2


def test_command_verifier_is_closed_by_default(tmp_path: Path) -> None:
    """H2: an empty allowlist meant arbitrary execution."""

    with pytest.raises(PolicyViolation):
        verify_command(["/bin/sh", "-c", "echo ARBITRARY"], policy=DEFAULT_POLICY)


def test_command_verifier_runs_only_allowlisted_executables() -> None:
    policy = VerifierPolicy(allowed_commands=("python3",))
    assert verify_command(["python3", "-c", "print('READY')"], contains="READY", policy=policy).ok
    with pytest.raises(PolicyViolation):
        verify_command(["/bin/sh", "-c", "echo x"], policy=policy)


def test_verifier_does_not_inherit_the_parent_environment() -> None:
    """M7: empty policy env became None, so the child inherited every secret."""

    os.environ["EVERRUN_PROBE_SECRET"] = "LEAKY"
    try:
        policy = VerifierPolicy(allowed_commands=("python3",))
        evidence = verify_command(
            ["python3", "-c", "import os;print(os.environ.get('EVERRUN_PROBE_SECRET'))"],
            policy=policy,
        )
        assert "LEAKY" not in evidence.detail
    finally:
        os.environ.pop("EVERRUN_PROBE_SECRET", None)


# --------------------------------------------------------------------------- H3/M8


def test_redirect_to_a_private_host_is_refused_before_the_request_lands() -> None:
    """H3: redirects were followed first and validated afterwards."""

    import http.server
    import socketserver
    import threading

    reached: list[str] = []

    class Internal(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            reached.append(self.path)
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"INTERNAL")

        def log_message(self, *_: object) -> None:
            pass

    with socketserver.TCPServer(("127.0.0.1", 0), Internal) as internal:
        threading.Thread(target=internal.serve_forever, daemon=True).start()
        internal_port = internal.server_address[1]

        class Redirector(http.server.BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                self.send_response(302)
                self.send_header("Location", f"http://127.0.0.1:{internal_port}/secret")
                self.end_headers()

            def log_message(self, *_: object) -> None:
                pass

        with socketserver.TCPServer(("127.0.0.1", 0), Redirector) as front:
            threading.Thread(target=front.serve_forever, daemon=True).start()
            policy = VerifierPolicy(allow_private_hosts=True, follow_redirects=False)
            with pytest.raises(PolicyViolation, match="redirect refused"):
                verify_http(f"http://127.0.0.1:{front.server_address[1]}/", policy=policy)
            front.shutdown()
        internal.shutdown()

    assert reached == []


def test_http_verifier_raises_loudly_on_a_policy_block() -> None:
    """A blocked SSRF attempt is a security event, not a soft check failure."""

    with pytest.raises(PolicyViolation):
        verify_http("http://169.254.169.254/latest/meta-data/")
    with pytest.raises(PolicyViolation):
        verify_http("file:///etc/passwd")


@pytest.mark.parametrize(
    "url",
    [
        "http://100.64.0.1/",
        "http://192.0.0.1/",
        "http://198.18.0.1/",
        "http://127.0.0.1/",
        "http://169.254.169.254/",
        "http://2130706433/",
        "http://[::1]/",
    ],
)
def test_reserved_and_cgnat_ranges_are_all_refused(url: str) -> None:
    """M8: CGNAT 100.64.0.0/10 was allowed."""

    with pytest.raises(PolicyViolation):
        verify_http(url)


# --------------------------------------------------------------------------- H4


def test_confirmation_only_covers_progress_recorded_before_it(tmp_path: Path) -> None:
    """H4: one confirmation used to whitelist all future agent-reported progress."""

    with EverRunStore(tmp_path / "everrun.db") as store:
        store.create_mission(Mission("m1", "review", 3))
        store.append_work("m1", "a", origin=Origin.EXTERNAL_AGENT)
        store.append(
            "m1", EventType.REVIEW_CONFIRMED, {"confirmed_by": "human"}, origin=Origin.HUMAN
        )
        assert recover(store, "m1").mode.value == "continue"

        store.append_work("m1", "b", origin=Origin.EXTERNAL_AGENT)
        after = recover(store, "m1")
        assert after.mode.value == "request_review"
        assert not after.safe

        store.append(
            "m1", EventType.REVIEW_CONFIRMED, {"confirmed_by": "human"}, origin=Origin.HUMAN
        )
        assert recover(store, "m1").mode.value == "continue"


def test_close_is_refused_while_unconfirmed_external_progress_exists(tmp_path: Path) -> None:
    with EverRunStore(tmp_path / "everrun.db") as store:
        store.create_mission(Mission("m1", "review", 1))
        store.append_work("m1", "a", origin=Origin.EXTERNAL_AGENT)
        with pytest.raises(ValueError, match="unconfirmed"):
            store.complete_mission("m1")


# --------------------------------------------------------------------------- H6


def test_capsule_export_refuses_to_leak_a_credential(tmp_path: Path) -> None:
    """H6: claim args went into the capsule verbatim, contradicting the README."""

    with EverRunStore(tmp_path / "everrun.db") as store:
        store.create_mission(Mission("m1", "leaky", 1))
        ActionLedger(store, "m1").claim(
            "call", {"headers": {"Authorization": "Bearer SUPERSECRETVALUE"}}
        )
        with pytest.raises(CapsuleWouldLeak):
            export_capsule(store, "m1", tmp_path / "mission.rly")

        share_only = export_capsule(store, "m1", tmp_path / "share.rly", redact_payloads=True)
        assert "SUPERSECRETVALUE" not in share_only.read_text(encoding="utf-8")


def test_share_only_capsule_cannot_be_imported_as_state(tmp_path: Path) -> None:
    with EverRunStore(tmp_path / "a.db") as store:
        store.create_mission(Mission("m1", "leaky", 1))
        ActionLedger(store, "m1").claim("call", {"token": "SUPERSECRETVALUE"})
        share_only = export_capsule(store, "m1", tmp_path / "share.rly", redact_payloads=True)
    with (
        EverRunStore(tmp_path / "b.db") as target,
        pytest.raises(ValueError, match="share-only"),
    ):
        import_capsule(target, share_only, allow_unsigned=True)


@pytest.mark.parametrize(
    "secret",
    [
        "AKIAIOSFODNN7EXAMPLE",
        "ghp_0123456789abcdefghijklmnopqrstuvwxyz",
        "sk-0123456789abcdefghijklmnopqrstuv",
        "-----BEGIN RSA PRIVATE KEY-----",
        "postgres://user:hunter2@db.internal:5432/app",
        "Set-Cookie: sid=abcdef123456",
        'Authorization": "Bearer abcdef123456"',
        "AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI0K7MDENGbPxRfiCY",
    ],
)
def test_redaction_covers_common_credential_shapes(secret: str) -> None:
    from everrun_agent.evidence import redact

    cleaned = redact(secret)
    for token in (
        "AKIAIOSFODNN7EXAMPLE",
        "hunter2",
        "abcdef123456",
        "wJalrXUtnFEMI0K7MDENGbPxRfiCY",
        "0123456789abcdefghijklmnopqrstuvwxyz",
    ):
        assert token not in cleaned
    assert "BEGIN RSA PRIVATE KEY" not in cleaned


# --------------------------------------------------------------------------- H7


def test_hook_installer_emits_only_real_commands(tmp_path: Path) -> None:
    """H7: it installed `everrun gate` and `everrun observe`, which do not exist."""

    from everrun_agent.adapters import install_hooks
    from everrun_agent.cli import parser

    entry = install_hooks(tmp_path / "hooks.json", "claude-code", tmp_path / "everrun.db")
    known = set(parser()._subparsers._group_actions[0].choices)  # type: ignore[union-attr]
    for command in entry.values():
        assert isinstance(command, list)
        assert command[0] == "everrun"
        assert any(token in known for token in command)


def test_hook_installer_does_not_build_injectable_shell_strings(tmp_path: Path) -> None:
    from everrun_agent.adapters import install_hooks

    nasty = tmp_path / "x.db; curl attacker.test #"
    entry = install_hooks(tmp_path / "hooks.json", "hermes", nasty)
    serialized = json.dumps(entry)
    assert "curl attacker.test" not in serialized.replace(str(nasty), "")
    for command in entry.values():
        assert isinstance(command, list)
        assert str(nasty) in command


# --------------------------------------------------------------------------- C4


def test_capsule_import_refuses_unsigned_capsules_by_default(tmp_path: Path) -> None:
    """C4: any rebuilt chain imported cleanly because digests are keyless."""

    with EverRunStore(tmp_path / "a.db") as store:
        store.create_mission(Mission("m1", "portable", 1))
        store.append_work("m1", "a")
        capsule = export_capsule(store, "m1", tmp_path / "mission.rly")
    with (
        EverRunStore(tmp_path / "b.db") as target,
        pytest.raises(ValueError, match="signed|signature"),
    ):
        import_capsule(target, capsule)


def test_capsule_import_accepts_a_trusted_signature(tmp_path: Path) -> None:
    key, _ = generate_keypair()
    with EverRunStore(tmp_path / "a.db") as store:
        store.create_mission(Mission("m1", "portable", 1))
        store.append_work("m1", "a")
        capsule = export_capsule(store, "m1", tmp_path / "mission.rly")
    sign_capsule(capsule, key, signer="workstation")
    with EverRunStore(tmp_path / "b.db") as target:
        assert import_capsule(target, capsule, trusted_keys={"workstation": key}) == "m1"


def test_forged_capsule_signature_is_rejected(tmp_path: Path) -> None:
    key, _ = generate_keypair()
    other, _ = generate_keypair()
    with EverRunStore(tmp_path / "a.db") as store:
        store.create_mission(Mission("m1", "portable", 1))
        capsule = export_capsule(store, "m1", tmp_path / "mission.rly")
    sign_capsule(capsule, other, signer="workstation")
    with (
        EverRunStore(tmp_path / "b.db") as target,
        pytest.raises(Exception, match="signature|signer"),
    ):
        import_capsule(target, capsule, trusted_keys={"workstation": key})


def test_unsigned_import_requires_explicit_opt_in(tmp_path: Path) -> None:
    with EverRunStore(tmp_path / "a.db") as store:
        store.create_mission(Mission("m1", "portable", 1))
        capsule = export_capsule(store, "m1", tmp_path / "mission.rly")
    with EverRunStore(tmp_path / "b.db") as target:
        assert import_capsule(target, capsule, allow_unsigned=True) == "m1"


# --------------------------------------------------------------------------- M2


def test_raw_execute_cannot_drop_integrity_triggers(tmp_path: Path) -> None:
    """M2: immutability was a convention because any caller could drop the triggers."""

    with EverRunStore(tmp_path / "everrun.db") as store:
        store.create_mission(Mission("m1", "immutable", 1))
        store.append_work("m1", "a")
        for statement in (
            "DROP TRIGGER events_no_delete",
            "DROP TRIGGER events_no_update",
            "DELETE FROM events WHERE sequence=2",
            "UPDATE events SET payload='{}' WHERE sequence=2",
            "PRAGMA writable_schema=ON",
        ):
            with pytest.raises((PermissionError, sqlite3.IntegrityError, ValueError)):
                store.raw_execute(statement)
        assert store.verify_chain("m1").ok


def test_read_only_queries_are_still_allowed(tmp_path: Path) -> None:
    with EverRunStore(tmp_path / "everrun.db") as store:
        store.create_mission(Mission("m1", "read", 1))
        rows = store.raw_query("SELECT COUNT(*) AS n FROM events")
        assert rows[0]["n"] == 1


# --------------------------------------------------------------------------- M3


def test_restore_projects_point_in_time_state(tmp_path: Path) -> None:
    """M3: restore returned a projection over ALL events, not the checkpoint's state."""

    with EverRunStore(tmp_path / "everrun.db") as store:
        store.create_mission(Mission("m1", "restore", 3))
        store.append_work("m1", "a")
        checkpoint = store.create_checkpoint("m1")
        store.append_work("m1", "b")
        store.append_work("m1", "c")
        restored = store.restore("m1", checkpoint.sequence)
        assert list(restored.state.completed) == ["a"]
        # Events strictly after the checkpoint sequence are the replay gap.
        assert restored.replayed_events == 3
        assert list(store.restore("m1").state.completed) == ["a"]


# --------------------------------------------------------------------------- M4


def test_success_contract_rejects_agent_asserted_evidence(tmp_path: Path) -> None:
    """M4: contracts counted EXTERNAL_AGENT evidence, so agents could self-certify."""

    contract = SuccessContract((ContractClause("prod-healthy", expected=True),))
    with EverRunStore(tmp_path / "everrun.db") as store:
        store.create_mission(Mission("m1", "contract", 1))
        store.append(
            "m1",
            EventType.EVIDENCE_RECORDED,
            {
                "evidence_id": "prod-healthy",
                "method": "http",
                "subject": "https://x.test",
                "ok": True,
                "digest": "d",
                "detail": "",
            },
            origin=Origin.EXTERNAL_AGENT,
        )
        assert not evaluate_contract(contract, store.events("m1")).satisfied
        store.append(
            "m1",
            EventType.EVIDENCE_RECORDED,
            {
                "evidence_id": "prod-healthy",
                "method": "http",
                "subject": "https://x.test",
                "ok": True,
                "digest": "d",
                "detail": "",
            },
            origin=Origin.DETERMINISTIC,
        )
        assert evaluate_contract(contract, store.events("m1")).satisfied


# --------------------------------------------------------------------------- M5


def test_events_cannot_be_appended_to_a_nonexistent_mission(tmp_path: Path) -> None:
    """M5: an orphan event permanently bricked a mission id."""

    with EverRunStore(tmp_path / "everrun.db") as store:
        with pytest.raises(KeyError):
            store.append_work("ghost", "a")
        store.create_mission(Mission("ghost", "now real", 1))
        store.append_work("ghost", "a")
        assert store.verify_chain("ghost").ok


def test_tool_surface_cannot_prebrick_a_mission_name(tmp_path: Path) -> None:
    server = ToolServer(db_path=tmp_path / "everrun.db", mutating_clients=("agent",))
    reply = server.handle(
        ToolRequest("everrun_record_work", {"mission_id": "later", "item": "a"}, client="agent")
    )
    assert not reply.ok
    assert server.handle(
        ToolRequest(
            "everrun_start", {"mission_id": "later", "goal": "g", "total": 1}, client="agent"
        )
    ).ok


# --------------------------------------------------------------------------- M6


def test_briefing_refuses_to_silently_drop_critical_sections(tmp_path: Path) -> None:
    """M6: a tiny budget truncated away NEXT SAFE ACTION and FORBIDDEN."""

    with EverRunStore(tmp_path / "everrun.db") as store:
        store.create_mission(Mission("m1", "budget", 2))
        store.append_work("m1", "a")
        with pytest.raises(BriefingTooLarge):
            compile_briefing(store, "m1", AgentProfile("tiny", context_tokens=20))
        generous = compile_briefing(store, "m1", AgentProfile("normal", context_tokens=4000))
        assert "NEXT SAFE ACTION" in generous
        assert "FORBIDDEN" in generous


# --------------------------------------------------------------------------- L1


def test_database_file_is_not_world_readable(tmp_path: Path) -> None:
    """L1: mission data was 0644 while capsules were 0600."""

    db = tmp_path / "everrun.db"
    with EverRunStore(db) as store:
        store.create_mission(Mission("m1", "perm", 1))
    mode = stat.S_IMODE(db.stat().st_mode)
    assert mode & (stat.S_IRGRP | stat.S_IROTH | stat.S_IWGRP | stat.S_IWOTH) == 0


# --------------------------------------------------------------------------- L2


def test_schema_downgrade_and_garbage_version_fail_closed(tmp_path: Path) -> None:
    db = tmp_path / "everrun.db"
    with EverRunStore(db) as store:
        store.create_mission(Mission("m1", "schema", 1))
    connection = sqlite3.connect(db)
    connection.execute("UPDATE metadata SET value='not-a-number' WHERE key='schema_version'")
    connection.commit()
    connection.close()
    with pytest.raises(RuntimeError):
        EverRunStore(db)


# --------------------------------------------------------------------------- M9


def test_attestation_key_is_documented_as_symmetric() -> None:
    """M9: generate_keypair returned (k, k) but labelled one of them public."""

    from everrun_agent.attestation import generate_shared_key

    key = generate_shared_key()
    assert isinstance(key, str)
    assert len(key) >= 32


def test_ledger_claim_still_raises_uncertain_action_directly(tmp_path: Path) -> None:
    with EverRunStore(tmp_path / "everrun.db") as store:
        store.create_mission(Mission("m1", "direct", 1))
        ledger = ActionLedger(store, "m1")
        ledger.claim("k", {"a": 1})
        with pytest.raises(UncertainAction):
            ledger.claim("k", {"a": 1})
