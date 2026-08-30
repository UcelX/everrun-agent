import hashlib
import json
from typing import Any


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def event_digest(
    mission_id: str,
    sequence: int,
    event_type: str,
    payload: dict[str, Any],
    created_at: str,
    previous_hash: str | None,
    origin: str = "deterministic",
) -> str:
    return sha256_text(
        canonical(
            {
                "mission_id": mission_id,
                "sequence": sequence,
                "event_type": event_type,
                "payload": payload,
                "created_at": created_at,
                "previous_hash": previous_hash,
                "origin": origin,
            }
        )
    )
