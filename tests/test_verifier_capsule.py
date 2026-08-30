from __future__ import annotations

from pathlib import Path

from everrun_agent import EventType, EverRunStore, Mission
from everrun_agent.capsule import export_capsule, import_capsule
from everrun_agent.verifier import VerifierPolicy, verify_command, verify_file, verify_http


def test_file_and_command_verifiers(tmp_path: Path) -> None:
    p = tmp_path / "artifact.txt"
    p.write_text("done", encoding="utf-8")
    evidence = verify_file(p, expected_text="done")
    assert evidence.ok and evidence.digest
    command = verify_command(["python3", "-c", "print('READY')"], contains="READY")
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


def test_capsule_roundtrip_excludes_credentials(tmp_path: Path) -> None:
    db = tmp_path / "a.db"
    with EverRunStore(db) as store:
        store.create_mission(Mission("m1", "Portable", 2))
        store.append("m1", EventType.FINDING_RECORDED, {"id": "f1", "text": "safe fact"})
        out = export_capsule(store, "m1", tmp_path / "mission.rly")
    raw = out.read_text(encoding="utf-8")
    assert "secret" not in raw.lower() and "api_key" not in raw.lower()
    with EverRunStore(tmp_path / "b.db") as target:
        imported = import_capsule(target, out)
        assert imported == "m1" and target.verify_chain("m1").ok
