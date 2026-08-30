from __future__ import annotations

import hashlib
import ipaddress
import socket
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .evidence import redact

MAX_BODY_BYTES = 262144
MAX_OUTPUT_CHARS = 4096


class PolicyViolation(RuntimeError):
    pass


@dataclass(frozen=True)
class VerifierPolicy:
    allowed_commands: tuple[str, ...] = ()
    allow_private_hosts: bool = False
    allowed_schemes: tuple[str, ...] = ("http", "https")
    timeout: float = 15.0
    env: dict[str, str] = field(default_factory=dict)
    workdir: str | None = None


DEFAULT_POLICY = VerifierPolicy()


@dataclass(frozen=True)
class Evidence:
    kind: str
    ok: bool
    detail: str
    digest: str | None = None
    exit_code: int | None = None
    status_code: int | None = None


def _assert_public_host(url: str, policy: VerifierPolicy) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in policy.allowed_schemes:
        raise PolicyViolation(f"scheme not allowed: {parsed.scheme or 'missing'}")
    if not parsed.hostname:
        raise PolicyViolation("url has no host")
    if policy.allow_private_hosts:
        return parsed.hostname
    try:
        infos = socket.getaddrinfo(
            parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80)
        )
    except socket.gaierror as exc:
        raise PolicyViolation(f"host cannot be resolved: {parsed.hostname}") from exc
    for info in infos:
        address = ipaddress.ip_address(info[4][0])
        if (
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_reserved
            or address.is_multicast
        ):
            raise PolicyViolation(f"private or link-local target refused: {address}")
    return parsed.hostname


def verify_file(path: str | Path, expected_text: str | None = None) -> Evidence:
    target = Path(path)
    if not target.is_file():
        return Evidence("file", False, "missing")
    data = target.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    ok = expected_text is None or expected_text in data.decode("utf-8", errors="replace")
    return Evidence("file", ok, str(target), digest=digest)


def verify_command(
    argv: list[str],
    contains: str | None = None,
    policy: VerifierPolicy = DEFAULT_POLICY,
) -> Evidence:
    if not argv:
        raise PolicyViolation("empty command")
    if policy.allowed_commands and argv[0] not in policy.allowed_commands:
        raise PolicyViolation(f"command not allowlisted: {argv[0]}")
    try:
        completed = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=policy.timeout,
            check=False,
            env=dict(policy.env) or None,
            cwd=policy.workdir,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return Evidence("command", False, redact(str(exc)))
    merged = completed.stdout + completed.stderr
    ok = completed.returncode == 0 and (contains is None or contains in merged)
    return Evidence(
        "command",
        ok,
        redact(merged[-MAX_OUTPUT_CHARS:]),
        exit_code=completed.returncode,
    )


def verify_http(
    url: str,
    contains: str | None = None,
    policy: VerifierPolicy = DEFAULT_POLICY,
) -> Evidence:
    _assert_public_host(url, policy)
    request = Request(url, headers={"User-Agent": "EverRunAgent/0.1"})
    try:
        with urlopen(request, timeout=policy.timeout) as response:
            final_url = response.geturl()
            if final_url != url:
                _assert_public_host(final_url, policy)
            body = response.read(MAX_BODY_BYTES).decode("utf-8", errors="replace")
            status = int(response.status)
        ok = 200 <= status < 300 and (contains is None or contains in body)
        return Evidence("http", ok, redact(body[-MAX_OUTPUT_CHARS:]), status_code=status)
    except HTTPError as exc:
        return Evidence("http", False, redact(str(exc)), status_code=exc.code)
    except OSError as exc:
        return Evidence("http", False, redact(str(exc)))
