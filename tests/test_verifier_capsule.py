from __future__ import annotations

from pathlib import Path

import pytest

from everrun_agent import ActionLedger, EventType, EverRunStore, Mission
from everrun_agent.attestation import generate_shared_key, sign_capsule
from everrun_agent.capsule import CapsuleWouldLeak, export_capsule, import_capsule
from everrun_agent.verifier import (
    VerifierPolicy,
    verify_command,
    verify_file,
    verify_http,
)


def test_file_and_command_verifiers(tmp_path: Path) -> None:
    p = tmp_path / "artifact.txt"
    p.write_text("done", encoding="utf-8")
    evidence = verify_file(p, expected_text="done")
    assert evidence.ok and evidence.digest
    command = verify_command(
        ["python3", "-c", "print('READY')"],
        contains="READY",
        policy=VerifierPolicy(allowed_commands=("python3",)),
    )
    assert command.ok and command.exit_code == 0


def test_http_verifier_uses_real_local_server(tmp_path: Path) -> None:
    import http.server
    import socketserver
    import threading

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"status":"ok"}')

        def log_message(self, *_):
            pass

    with socketserver.TCPServer(("127.0.0.1", 0), H) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        result = verify_http(
            f"http://127.0.0.1:{server.server_address[1]}",
            contains='"ok"',
            policy=VerifierPolicy(allow_private_hosts=True),
        )
        server.shutdown()
    assert result.ok and result.status_code == 200


def test_signed_capsule_roundtrip(tmp_path: Path) -> None:
    key = generate_shared_key()
    db = tmp_path / "a.db"
    with EverRunStore(db) as store:
        store.create_mission(Mission("m1", "Portable", 2))
        store.append("m1", EventType.FINDING_RECORDED, {"id": "f1", "text": "safe fact"})
        out = export_capsule(store, "m1", tmp_path / "mission.rly")
    sign_capsule(out, key, signer="workstation")
    with EverRunStore(tmp_path / "b.db") as target:
        imported = import_capsule(target, out, trusted_keys={"workstation": key})
        assert imported == "m1" and target.verify_chain("m1").ok


def test_capsule_export_fails_closed_when_a_payload_holds_a_credential(tmp_path: Path) -> None:
    """The README promises capsules never carry credentials; enforce it."""

    with EverRunStore(tmp_path / "a.db") as store:
        store.create_mission(Mission("m1", "Portable", 1))
        ActionLedger(store, "m1").claim("call", {"api_key": "AKIAIOSFODNN7EXAMPLE"})
        with pytest.raises(CapsuleWouldLeak):
            export_capsule(store, "m1", tmp_path / "mission.rly")
        share_only = export_capsule(store, "m1", tmp_path / "share.rly", redact_payloads=True)
    assert "AKIAIOSFODNN7EXAMPLE" not in share_only.read_text(encoding="utf-8")
