from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, cast

from .crypto import canonical, sha256_text
from .store import RelayStore

FORMAT = "relaycore-capsule-v1"


def export_capsule(store: RelayStore, mission_id: str, path: str | Path) -> Path:
    mission = store.get_mission(mission_id)
    events = store.events(mission_id)
    report = store.verify_chain(mission_id)
    if not report.ok:
        raise ValueError("cannot export corrupt mission")
    body = {
        "format": FORMAT,
        "mission": {"mission_id": mission.mission_id, "goal": mission.goal, "total": mission.total},
        "events": [
            {
                "sequence": e.sequence,
                "event_type": e.event_type.value,
                "payload": e.payload,
                "created_at": e.created_at,
                "previous_hash": e.previous_hash,
                "digest": e.digest,
            }
            for e in events
        ],
    }
    envelope = {"body": body, "digest": sha256_text(canonical(body))}
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=target.name + ".", dir=target.parent)
    os.close(fd)
    try:
        Path(tmp).write_text(canonical(envelope), encoding="utf-8")
        os.chmod(tmp, 0o600)
        os.replace(tmp, target)
    finally:
        if Path(tmp).exists():
            Path(tmp).unlink()
    return target


def import_capsule(store: RelayStore, path: str | Path) -> str:
    env = cast(dict[str, Any], json.loads(Path(path).read_text(encoding="utf-8")))
    body = env["body"]
    if body.get("format") != FORMAT or sha256_text(canonical(body)) != env.get("digest"):
        raise ValueError("invalid capsule")
    m = body["mission"]
    store.conn.execute(
        "INSERT INTO missions VALUES(?,?,?)", (m["mission_id"], m["goal"], m["total"])
    )
    for e in body["events"]:
        store.conn.execute(
            "INSERT INTO events VALUES(?,?,?,?,?,?,?)",
            (
                m["mission_id"],
                e["sequence"],
                e["event_type"],
                canonical(e["payload"]),
                e["created_at"],
                e["previous_hash"],
                e["digest"],
            ),
        )
    store.conn.commit()
    if not store.verify_chain(m["mission_id"]).ok:
        raise ValueError("capsule chain invalid")
    return cast(str, m["mission_id"])
