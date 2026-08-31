from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any

from .models import EventType, Origin
from .store import EverRunStore

MAX_DETAIL_CHARS = 4096

_PEM_BLOCK = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
    re.DOTALL,
)

# Ordered: structural patterns first, then bare high-entropy prefixes.
_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"(?i)(authorization\"?\s*[:=]\s*\"?)(?:bearer|basic|token)?\s*[^\s\"',]+"),
        r"\1[REDACTED]",
    ),
    (re.compile(r"(?i)(set-cookie\s*[:=]\s*)[^\s;]+"), r"\1[REDACTED]"),
    (re.compile(r"(?i)(cookie\s*[:=]\s*)[^\s;]+"), r"\1[REDACTED]"),
    (
        re.compile(
            r"(?i)([A-Za-z0-9_.\-]*(?:api[_-]?key|secret|token|password|passwd|pwd|credential|private[_-]?key)"
            r"[A-Za-z0-9_.\-]*\s*[:=]\s*\"?)[^\s\"',}]+"
        ),
        r"\1[REDACTED]",
    ),
    (re.compile(r"([a-zA-Z][a-zA-Z0-9+.\-]*://[^\s/:@]+):[^\s/@]+@"), r"\1:[REDACTED]@"),
    (re.compile(r"\bAKIA[0-9A-Z]{12,}\b"), "[REDACTED]"),
    (re.compile(r"\bASIA[0-9A-Z]{12,}\b"), "[REDACTED]"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{16,}\b"), "[REDACTED]"),
    (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"), "[REDACTED]"),
    (re.compile(r"\bsk-[A-Za-z0-9_\-]{16,}\b"), "[REDACTED]"),
    (re.compile(r"\bxox[abposr]-[A-Za-z0-9\-]{10,}\b"), "[REDACTED]"),
    (
        re.compile(r"\bey[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\b"),
        "[REDACTED]",
    ),
    (re.compile(r"\bAIza[0-9A-Za-z_\-]{20,}\b"), "[REDACTED]"),
)

_SENSITIVE_KEY = re.compile(
    r"(?i)(authorization|api[_-]?key|secret|token|password|passwd|pwd|credential|"
    r"private[_-]?key|cookie|session|bearer|mnemonic|seed[_-]?phrase|passphrase)"
)


@dataclass(frozen=True)
class EvidenceRecord:
    evidence_id: str
    method: str
    subject: str
    ok: bool
    digest: str
    detail: str = ""


def redact(value: str) -> str:
    """Best-effort credential scrubbing for durable text.

    This is defence in depth, not a guarantee: never deliberately route a
    credential through evidence or a capsule and rely on this to hide it.
    """

    value = _PEM_BLOCK.sub("[REDACTED PRIVATE KEY]", value)
    if "-----BEGIN" in value and "PRIVATE KEY" in value:
        value = re.sub(r"-----BEGIN [A-Z ]*PRIVATE KEY-----", "[REDACTED PRIVATE KEY]", value)
    for pattern, replacement in _PATTERNS:
        value = pattern.sub(replacement, value)
    return value[:MAX_DETAIL_CHARS]


def redact_payload(payload: Any) -> Any:
    """Recursively scrub a JSON-shaped payload, by key name and by value shape."""

    if isinstance(payload, dict):
        cleaned: dict[str, Any] = {}
        for key, value in payload.items():
            if _SENSITIVE_KEY.search(str(key)):
                cleaned[str(key)] = "[REDACTED]"
            else:
                cleaned[str(key)] = redact_payload(value)
        return cleaned
    if isinstance(payload, list):
        return [redact_payload(item) for item in payload]
    if isinstance(payload, tuple):
        return [redact_payload(item) for item in payload]
    if isinstance(payload, str):
        return redact(payload)
    return payload


def record_evidence(
    store: EverRunStore,
    mission_id: str,
    record: EvidenceRecord,
    origin: Origin = Origin.DETERMINISTIC,
) -> None:
    payload = asdict(record)
    payload["detail"] = redact(record.detail)
    store.append(mission_id, EventType.EVIDENCE_RECORDED, payload, origin=origin)
