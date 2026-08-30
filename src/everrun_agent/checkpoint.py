from dataclasses import asdict

from .crypto import canonical, sha256_text
from .models import Checkpoint, EventType
from .projection import StateProjector
from .store import EverRunStore


def checkpoint(store: EverRunStore, mission_id: str, reason: str = "manual") -> Checkpoint:
    events = store.events(mission_id)
    payload = canonical(asdict(StateProjector.project(events)))
    digest = sha256_text(payload)
    sequence = events[-1].sequence
    with store.transaction():
        store.conn.execute(
            "INSERT INTO checkpoints(mission_id,sequence,payload,digest,reason) VALUES(?,?,?,?,?)",
            (mission_id, sequence, payload, digest, reason),
        )
        store._insert_event(
            mission_id,
            EventType.CHECKPOINT_CREATED,
            {"source_sequence": sequence, "state_digest": digest, "reason": reason},
        )
    return Checkpoint(mission_id, sequence, payload, digest)
