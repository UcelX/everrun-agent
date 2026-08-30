from dataclasses import asdict

from .crypto import canonical, sha256_text
from .models import Checkpoint, EventType
from .projection import StateProjector
from .store import EverRunStore


def checkpoint(store: EverRunStore, mission_id: str) -> Checkpoint:
    events = store.events(mission_id)
    payload = canonical(asdict(StateProjector.project(events)))
    digest = sha256_text(payload)
    seq = events[-1].sequence
    store.conn.execute(
        "INSERT OR REPLACE INTO checkpoints VALUES(?,?,?,?)", (mission_id, seq, payload, digest)
    )
    store.conn.commit()
    store.append(
        mission_id, EventType.CHECKPOINT_CREATED, {"source_sequence": seq, "state_digest": digest}
    )
    return Checkpoint(mission_id, seq, payload, digest)
