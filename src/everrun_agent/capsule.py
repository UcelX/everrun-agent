from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, cast

from .attestation import AttestationError, verify_capsule_signature
from .crypto import canonical, sha256_text
from .evidence import redact_payload
from .store import EverRunStore

FORMAT = "everrun-agent-capsule-v1"


class CapsuleWouldLeak(ValueError):
    """Raised when a capsule cannot be exported without carrying a credential.

    H6: payloads were serialized verbatim, so a token passed in ledger claim args
    ended up inside the portable capsule while the README promised capsules never
    carry credentials. Export now fails closed instead of leaking silently.
    """


def _leaking_sequences(events: list[Any]) -> list[int]:
    leaking = []
    for event in events:
        if redact_payload(event.payload) != event.payload:
            leaking.append(event.sequence)
    return leaking


def export_capsule(
    store: EverRunStore,
    mission_id: str,
    path: str | Path,
    redact_payloads: bool = False,
) -> Path:
    """Write a portable, integrity-checked capsule.

    By default this REFUSES to export a mission whose payloads look like they
    contain credentials, because a transferable capsule must keep the event
    digests intact and therefore cannot rewrite payloads.

    Pass ``redact_payloads=True`` to produce a scrubbed, share-only capsule. That
    artifact is deliberately NOT importable: rewriting payloads breaks the hash
    chain, and silently accepting a broken chain would defeat the whole model.
    """

    mission = store.get_mission(mission_id)
    events = store.events(mission_id)
    if not store.verify_chain(mission_id).ok:
        raise ValueError("cannot export corrupt mission")

    leaking = _leaking_sequences(events)
    if leaking and not redact_payloads:
        raise CapsuleWouldLeak(
            f"events {leaking} contain credential-shaped values; "
            "never pass secrets through ledger args or event payloads. "
            "Use redact_payloads=True for a share-only (non-importable) capsule"
        )

    body = {
        "format": FORMAT,
        "mission": {"mission_id": mission.mission_id, "goal": mission.goal, "total": mission.total},
        "redacted": bool(redact_payloads),
        "transferable": not redact_payloads,
        "events": [
            {
                "sequence": event.sequence,
                "event_type": event.event_type.value,
                "payload": redact_payload(event.payload) if redact_payloads else event.payload,
                "created_at": event.created_at,
                "previous_hash": event.previous_hash,
                "digest": event.digest,
                "origin": event.origin.value,
            }
            for event in events
        ],
    }
    envelope = {"body": body, "digest": sha256_text(canonical(body))}
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=target.name + ".", dir=target.parent)
    os.close(fd)
    try:
        Path(temporary).write_text(canonical(envelope), encoding="utf-8")
        os.chmod(temporary, 0o600)
        os.replace(temporary, target)
    finally:
        if Path(temporary).exists():
            Path(temporary).unlink()
    return target


def import_capsule(
    store: EverRunStore,
    path: str | Path,
    trusted_keys: dict[str, str] | None = None,
    allow_unsigned: bool = False,
) -> str:
    """Import a capsule after verifying its attestation.

    C4: event digests are unkeyed SHA-256, so anyone can rebuild an entire chain
    and it will self-verify. Only a signature from a trusted signer proves
    provenance, so an unsigned capsule is refused unless explicitly allowed.
    """

    if trusted_keys:
        verify_capsule_signature(path, trusted_keys)
    elif not allow_unsigned:
        raise ValueError(
            "refusing to import an unverified capsule: pass trusted_keys={signer: key} "
            "to check its attestation, or allow_unsigned=True to accept unproven provenance"
        )

    try:
        envelope = cast(dict[str, Any], json.loads(Path(path).read_text(encoding="utf-8")))
        body = envelope["body"]
        if body.get("format") != FORMAT or sha256_text(canonical(body)) != envelope.get("digest"):
            raise ValueError("invalid capsule")
        if body.get("redacted"):
            raise ValueError(
                "this is a share-only redacted capsule; its payloads were rewritten so the "
                "hash chain can no longer be verified and it must not be imported as state"
            )
        mission = body["mission"]
        events = body.get("events")
        if not isinstance(events, list) or not events:
            raise ValueError("invalid capsule events")
        with store.transaction():
            store.conn.execute(
                "INSERT INTO missions VALUES(?,?,?)",
                (mission["mission_id"], mission["goal"], mission["total"]),
            )
            for event in events:
                store.conn.execute(
                    "INSERT INTO events(mission_id,sequence,event_type,payload,created_at,previous_hash,digest,origin) VALUES(?,?,?,?,?,?,?,?)",
                    (
                        mission["mission_id"],
                        event["sequence"],
                        event["event_type"],
                        canonical(event["payload"]),
                        event["created_at"],
                        event["previous_hash"],
                        event["digest"],
                        event.get("origin", "deterministic"),
                    ),
                )
            store.conn.execute(
                "INSERT INTO chain_heads VALUES(?,?,?)",
                (mission["mission_id"], len(events), events[-1]["digest"]),
            )
            if not store.verify_chain(mission["mission_id"]).ok:
                raise ValueError("capsule chain invalid")
        return cast(str, mission["mission_id"])
    except AttestationError:
        raise
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError("malformed capsule") from exc
