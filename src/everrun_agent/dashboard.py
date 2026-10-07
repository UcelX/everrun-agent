from __future__ import annotations

import ipaddress
import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, cast

from .operations import runtime_status

_PAGE = """<!doctype html><html lang=en><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'><title>EverRun</title><style>body{font:16px system-ui;max-width:960px;margin:40px auto;padding:0 20px;background:#f6f5f1;color:#171717}header{display:flex;justify-content:space-between;align-items:center}h1{font-size:32px}.pill{padding:7px 12px;border:1px solid #bbb;border-radius:99px;background:white}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:14px}.card{background:white;border:1px solid #ddd;border-radius:14px;padding:18px;margin:12px 0}.muted{color:#666;font-size:14px}code{word-break:break-all}</style><header><div><h1>EverRun Agent</h1><p>Local mission control</p></div><span class=pill id=health>Loading</span></header><main><section class=grid id=counts></section><section><h2>Missions</h2><div id=missions></div></section></main><script>fetch('/api/status').then(r=>r.json()).then(x=>{health.textContent=x.healthy?'Healthy':'Needs attention';counts.innerHTML=Object.entries(x.mission_counts).map(([k,v])=>`<div class=card><div class=muted>${k}</div><strong>${v}</strong></div>`).join('');missions.innerHTML=x.missions.length?x.missions.map(m=>`<article class=card><strong>${m.mission_id}</strong><p>${m.goal}</p><div class=muted>${m.status} · ${m.completed}/${m.total}</div></article>`).join(''):'<div class=card>No missions yet.</div>'}).catch(()=>health.textContent='Unavailable')</script></html>"""


class _DashboardHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/":
            self._send(HTTPStatus.OK, "text/html; charset=utf-8", _PAGE.encode())
            return
        if self.path == "/api/status":
            database = cast("DashboardServer", self.server).database
            payload = runtime_status(database)
            self._send(
                HTTPStatus.OK,
                "application/json",
                json.dumps(payload, sort_keys=True).encode(),
            )
            return
        self._send(HTTPStatus.NOT_FOUND, "application/json", b'{"error":"not found"}')

    def do_POST(self) -> None:
        self._send(
            HTTPStatus.METHOD_NOT_ALLOWED,
            "application/json",
            b'{"error":"read-only dashboard"}',
        )

    def _send(self, status: HTTPStatus, content_type: str, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self' 'unsafe-inline'")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:
        return


class DashboardServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        database: str | Path,
        *,
        host: str = "127.0.0.1",
        port: int = 8765,
        allow_remote: bool = False,
    ) -> None:
        try:
            is_loopback = ipaddress.ip_address(host).is_loopback
        except ValueError:
            is_loopback = host == "localhost"
        if not is_loopback and not allow_remote:
            raise ValueError("dashboard binds to loopback only unless --allow-remote is explicit")
        self.database = Path(database)
        super().__init__((host, port), _DashboardHandler)


def serve_dashboard(
    database: str | Path,
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    allow_remote: bool = False,
) -> None:
    server = DashboardServer(database, host=host, port=port, allow_remote=allow_remote)
    print(f"EverRun dashboard: http://{host}:{server.server_address[1]}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
