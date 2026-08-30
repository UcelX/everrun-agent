from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, cast

from .crypto import canonical, sha256_text
from .store import EverRunStore

FORMAT = "everrun-agent-capsule-v1"


def export_capsule(store: EverRunStore, mission_id: str, path: str | Path) -> Path:
    mission = store.get_mission(mission_id)
    events = store.events(mission_id)
    if not store.verify_chain(mission_id).ok:
        raise ValueError("cannot export corrupt mission")
    body = {
        "format": FORMAT,
        "mission": {"mission_id": mission.mission_id, "goal": mission.goal, "total": mission.total},
        "events": [
            {
                "sequence": event.sequence,
                "event_type": event.event_type.value,
                "payload": event.payload,
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


def import_capsule(store: EverRunStore, path: str | Path) -> str:
    try:
        envelope = cast(dict[str, Any], json.loads(Path(path).read_text(encoding="utf-8")))
        body = envelope["body"]
        if body.get("format") != FORMAT or sha256_text(canonical(body)) != envelope.get("digest"):
            raise ValueError("invalid capsule")
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
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError("malformed capsule") from exc
