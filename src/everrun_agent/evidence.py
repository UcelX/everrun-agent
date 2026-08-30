from __future__ import annotations

import re
from dataclasses import asdict, dataclass

from .models import EventType, Origin
from .store import EverRunStore


@dataclass(frozen=True)
class EvidenceRecord:
    evidence_id: str
    method: str
    subject: str
    ok: bool
    digest: str
    detail: str = ""


def redact(value: str) -> str:
    value = re.sub(r"(?i)(authorization:\s*bearer\s+)\S+", r"\1[REDACTED]", value)
    value = re.sub(r"(?i)((?:api[_-]?key|token|password)\s*[=:]\s*)\S+", r"\1[REDACTED]", value)
    return value[:4096]


def record_evidence(store: EverRunStore, mission_id: str, record: EvidenceRecord) -> None:
    payload = asdict(record)
    payload["detail"] = redact(record.detail)
    store.append(mission_id, EventType.EVIDENCE_RECORDED, payload, origin=Origin.DETERMINISTIC)
