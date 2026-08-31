from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypeVar

from .evidence import EvidenceRecord, record_evidence
from .gate import GateResult, protected_call
from .ledger import ActionLedger
from .models import Event, EventType, Mission, Origin
from .store import EverRunStore
from .verifier import verify_file

T = TypeVar("T")
SUPPORTED_CLIENTS = ("hermes", "claude-code", "codex")


class GenericAgentAdapter:
    """In-process facade binding claim-before-fire, progress, and evidence."""

    def __init__(self, store: EverRunStore, mission: Mission | str):
        self.store = store
        if isinstance(mission, Mission):
            try:
                store.get_mission(mission.mission_id)
            except KeyError:
                store.create_mission(mission)
            self.mission_id = mission.mission_id
        else:
            store.get_mission(mission)
            self.mission_id = mission
        self.ledger = ActionLedger(store, self.mission_id)

    def perform(self, kind: str, args: dict[str, Any], effect: Callable[[], T]) -> GateResult:
        return protected_call(self.ledger, kind, args, effect)

    def record_progress(self, item: str, origin: Origin = Origin.DETERMINISTIC) -> Event:
        return self.store.append(
            self.mission_id, EventType.WORK_COMPLETED, {"item": item}, origin=origin
        )

    def observe_file(self, path: str | Path, expected_text: str | None = None) -> EvidenceRecord:
        evidence = verify_file(path, expected_text=expected_text)
        record = EvidenceRecord(
            evidence_id=str(path),
            method="file",
            subject=str(path),
            ok=evidence.ok,
            digest=evidence.digest or "",
            detail=evidence.detail,
        )
        record_evidence(self.store, self.mission_id, record)
        return record

    def checkpoint(self, reason: str = "adapter") -> None:
        self.store.create_checkpoint(self.mission_id, reason=reason)


def _load(path: Path) -> dict[str, Any]:
    if path.is_file():
        loaded: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        loaded.setdefault("hooks", {})
        return loaded
    return {"hooks": {}}


def install_hooks(path: str | Path, client: str, db_path: str | Path) -> dict[str, list[str]]:
    """Install lifecycle hooks as ARGV ARRAYS for commands that actually exist.

    H7: hooks used to be f-string shell commands, so a db path containing shell
    metacharacters became an injected pipeline, and two of the three installed
    commands (``gate``, ``observe``) were not real CLI subcommands at all, so
    every hook failed at runtime.
    """

    if client not in SUPPORTED_CLIENTS:
        raise ValueError(f"unsupported client: {client}")
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    config = _load(target)
    db = str(db_path)
    entry: dict[str, list[str]] = {
        "session_start": ["everrun", "--db", db, "briefing", "$EVERRUN_MISSION"],
        "pre_tool_use": ["everrun", "--db", db, "resume", "$EVERRUN_MISSION"],
        "post_tool_use": ["everrun", "--db", db, "status", "$EVERRUN_MISSION", "--json"],
    }
    config["hooks"][client] = entry
    target.write_text(json.dumps(config, indent=2, sort_keys=True), encoding="utf-8")
    return entry


def uninstall_hooks(path: str | Path, client: str) -> None:
    target = Path(path)
    config = _load(target)
    config["hooks"].pop(client, None)
    target.write_text(json.dumps(config, indent=2, sort_keys=True), encoding="utf-8")
