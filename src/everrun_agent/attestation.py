from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
from pathlib import Path
from typing import Any

from .crypto import canonical

ALGORITHM = "hmac-sha256"


class AttestationError(RuntimeError):
    pass


def generate_shared_key() -> str:
    """Generate a SYMMETRIC attestation key.

    M9: this is a shared secret, not a keypair. Anyone who can verify a capsule
    with this key can also forge one. v0.1 ships symmetric HMAC so the core stays
    dependency-free; asymmetric Ed25519 signing is planned for v0.2 behind an
    optional extra, and the envelope (signer identity + algorithm + digest)
    already matches that future format.
    """

    return secrets.token_hex(32)


def generate_keypair() -> tuple[str, str]:
    """Deprecated alias kept for compatibility.

    Returns the SAME symmetric key twice. Do not treat the second value as a
    public key: see generate_shared_key.
    """

    key = generate_shared_key()
    return key, key


def _signature(body: dict[str, Any], private_key: str) -> str:
    return hmac.new(
        private_key.encode("utf-8"), canonical(body).encode("utf-8"), hashlib.sha256
    ).hexdigest()


def sign_capsule(path: str | Path, private_key: str, signer: str) -> Path:
    target = Path(path)
    payload: dict[str, Any] = json.loads(target.read_text(encoding="utf-8"))
    if "body" not in payload:
        raise AttestationError("capsule has no body to sign")
    payload["signature"] = {
        "signer": signer,
        "algorithm": ALGORITHM,
        "value": _signature(payload["body"], private_key),
    }
    target.write_text(canonical(payload), encoding="utf-8")
    os.chmod(target, 0o600)
    return target


def verify_capsule_signature(path: str | Path, trusted_keys: dict[str, str]) -> bool:
    payload: dict[str, Any] = json.loads(Path(path).read_text(encoding="utf-8"))
    signature = payload.get("signature")
    if not isinstance(signature, dict):
        raise AttestationError("capsule is unsigned")
    if signature.get("algorithm") != ALGORITHM:
        raise AttestationError(f"unsupported algorithm: {signature.get('algorithm')}")
    signer = str(signature.get("signer", ""))
    key = trusted_keys.get(signer)
    if key is None:
        raise AttestationError(f"unknown or revoked signer: {signer or 'missing'}")
    expected = _signature(payload["body"], key)
    if not hmac.compare_digest(expected, str(signature.get("value", ""))):
        raise AttestationError("capsule signature does not match its body")
    return True
