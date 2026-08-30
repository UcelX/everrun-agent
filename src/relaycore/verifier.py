from __future__ import annotations

import hashlib
import subprocess
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class Evidence:
    kind: str
    ok: bool
    detail: str
    digest: str | None = None
    exit_code: int | None = None
    status_code: int | None = None


def verify_file(path: str | Path, expected_text: str | None = None) -> Evidence:
    p = Path(path)
    if not p.is_file():
        return Evidence("file", False, "missing")
    data = p.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    ok = expected_text is None or expected_text in data.decode("utf-8", errors="replace")
    return Evidence("file", ok, str(p), digest=digest)


def verify_command(argv: list[str], contains: str | None = None, timeout: float = 30) -> Evidence:
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as e:
        return Evidence("command", False, str(e))
    merged = p.stdout + p.stderr
    return Evidence(
        "command",
        p.returncode == 0 and (contains is None or contains in merged),
        merged[-2000:],
        exit_code=p.returncode,
    )


def verify_http(url: str, contains: str | None = None, timeout: float = 10) -> Evidence:
    try:
        with urlopen(Request(url, headers={"User-Agent": "RelayCore/0.1"}), timeout=timeout) as r:
            body = r.read(1048576).decode("utf-8", errors="replace")
            code = r.status
        return Evidence(
            "http",
            200 <= code < 300 and (contains is None or contains in body),
            body[-2000:],
            status_code=code,
        )
    except HTTPError as e:
        return Evidence("http", False, str(e), status_code=e.code)
    except OSError as e:
        return Evidence("http", False, str(e))
