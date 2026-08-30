from __future__ import annotations

from pathlib import Path

import pytest

from everrun_agent import EverRunStore, Mission
from everrun_agent.service import ToolRequest, ToolServer


@pytest.mark.parametrize(
    "mission_id",
    ["../../evil", "a/b", "a\\b", "", "   ", "x" * 129, "bad id", "null\x00byte"],
)
def test_unsafe_mission_identifiers_are_refused(tmp_path: Path, mission_id: str) -> None:
    with EverRunStore(tmp_path / "everrun.db") as store:
        with pytest.raises(ValueError):
            store.create_mission(Mission(mission_id, "goal", 1))
        assert store.conn.execute("SELECT COUNT(*) FROM missions").fetchone()[0] == 0


def test_safe_mission_identifiers_are_accepted(tmp_path: Path) -> None:
    with EverRunStore(tmp_path / "everrun.db") as store:
        for mission_id in ("release-1", "mission_2", "ABC.123"):
            store.create_mission(Mission(mission_id, "goal", 1))
        assert store.conn.execute("SELECT COUNT(*) FROM missions").fetchone()[0] == 3


def test_oversized_goal_and_payload_are_refused(tmp_path: Path) -> None:
    with EverRunStore(tmp_path / "everrun.db") as store:
        with pytest.raises(ValueError):
            store.create_mission(Mission("m1", "g" * 8193, 1))
        store.create_mission(Mission("m1", "ok", 1))
        with pytest.raises(ValueError):
            store.append_work("m1", "x" * 4097)


def test_negative_or_absurd_totals_are_refused(tmp_path: Path) -> None:
    with EverRunStore(tmp_path / "everrun.db") as store:
        with pytest.raises(ValueError):
            store.create_mission(Mission("m1", "goal", -1))
        with pytest.raises(ValueError):
            store.create_mission(Mission("m2", "goal", 10_000_001))


def test_tool_surface_rejects_unsafe_identifiers(tmp_path: Path) -> None:
    server = ToolServer(db_path=tmp_path / "everrun.db")
    reply = server.handle(
        ToolRequest(
            "everrun_start", {"mission_id": "../escape", "goal": "g", "total": 1}, client="agent"
        )
    )
    assert not reply.ok
    assert reply.error_code == "invalid_arguments"
