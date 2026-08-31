from __future__ import annotations

import hashlib
import ipaddress
import socket
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .evidence import redact

MAX_BODY_BYTES = 262144
MAX_OUTPUT_CHARS = 4096

# M8: ranges that are reachable-but-internal and were not covered by the
# ipaddress convenience flags.
EXTRA_DENY_NETWORKS = (
    ipaddress.ip_network("100.64.0.0/10"),  # CGNAT
    ipaddress.ip_network("192.0.0.0/24"),  # IETF protocol assignments
    ipaddress.ip_network("192.0.2.0/24"),  # TEST-NET-1
    ipaddress.ip_network("198.18.0.0/15"),  # benchmarking
    ipaddress.ip_network("198.51.100.0/24"),  # TEST-NET-2
    ipaddress.ip_network("203.0.113.0/24"),  # TEST-NET-3
    ipaddress.ip_network("240.0.0.0/4"),  # reserved class E
    ipaddress.ip_network("64:ff9b::/96"),  # NAT64
    ipaddress.ip_network("::ffff:0:0/96"),  # IPv4-mapped IPv6
    ipaddress.ip_network("fc00::/7"),  # unique local
    ipaddress.ip_network("2002::/16"),  # 6to4
)


class PolicyViolation(RuntimeError):
    pass


@dataclass(frozen=True)
class VerifierPolicy:
    """Deny-by-default verification policy.

    ``allowed_commands`` empty means NO command may run (H2 fixed a fail-open
    default that allowed arbitrary execution). ``follow_redirects`` defaults to
    False because a redirect is a fresh request to a host the caller never
    validated (H3).
    """

    allowed_commands: tuple[str, ...] = ()
    allow_private_hosts: bool = False
    allowed_schemes: tuple[str, ...] = ("http", "https")
    timeout: float = 15.0
    env: dict[str, str] = field(default_factory=dict)
    workdir: str | None = None
    follow_redirects: bool = False
    inherit_environment: bool = False


DEFAULT_POLICY = VerifierPolicy()
MINIMAL_ENV = {"PATH": "/usr/bin:/bin"}


@dataclass(frozen=True)
class Evidence:
    kind: str
    ok: bool
    detail: str
    digest: str | None = None
    exit_code: int | None = None
    status_code: int | None = None


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *_: object, **__: object) -> None:
        raise PolicyViolation("redirect refused: target host was never validated")


def _address_is_internal(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_reserved
        or address.is_multicast
        or address.is_unspecified
    ):
        return True
    return any(address in network for network in EXTRA_DENY_NETWORKS)


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
        if _address_is_internal(address):
            raise PolicyViolation(f"private, reserved, or link-local target refused: {address}")
    return parsed.hostname


def verify_file(
    path: str | Path,
    expected_text: str | None = None,
    policy: VerifierPolicy = DEFAULT_POLICY,
) -> Evidence:
    target = Path(path).resolve()
    if policy.workdir is not None:
        root = Path(policy.workdir).resolve()
        if root not in target.parents and target != root:
            raise PolicyViolation(f"path escapes the policy workdir: {target}")
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
    if not policy.allowed_commands:
        raise PolicyViolation(
            "no command allowlist configured; set VerifierPolicy(allowed_commands=(...)) "
            "before running commands"
        )
    if argv[0] not in policy.allowed_commands:
        raise PolicyViolation(f"command not allowlisted: {argv[0]}")
    # M7: an empty policy env used to become None, so the child inherited every
    # environment variable of the parent, including credentials.
    environment = dict(policy.env) if policy.env else dict(MINIMAL_ENV)
    try:
        completed = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=policy.timeout,
            check=False,
            env=None if policy.inherit_environment else environment,
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
    """Fetch a URL under policy.

    Policy rejections raise PolicyViolation loudly (a blocked SSRF attempt is a
    security event, not a failed check); transport and HTTP errors return
    not-ok Evidence.

    H3: redirects are refused by default, so an internal host is never actually
    contacted. Previously urlopen followed the redirect itself and the check
    happened afterwards, which withheld the body but not the request.
    """

    _assert_public_host(url, policy)

    handlers = [] if policy.follow_redirects else [_NoRedirect()]
    opener = build_opener(*handlers)
    request = Request(url, headers={"User-Agent": "EverRunAgent/0.1"})
    try:
        with opener.open(request, timeout=policy.timeout) as response:
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
        # urllib wraps a handler exception from a redirect in URLError.
        for nested in (exc.__cause__, getattr(exc, "reason", None)):
            if isinstance(nested, PolicyViolation):
                raise nested from exc
        return Evidence("http", False, redact(str(exc)))
