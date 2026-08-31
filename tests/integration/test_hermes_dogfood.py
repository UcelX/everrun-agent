from __future__ import annotations

import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "dogfood_harness", Path(__file__).parents[2] / "scripts/dogfood_harness.py"
)
assert _spec is not None and _spec.loader is not None
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)
run = _module.run


def test_protocol_fallback_dogfood_transitions_once_and_valid_chain(tmp_path: Path) -> None:
    report = run(tmp_path)
    assert report["transitions"] == [
        "reconcile",
        "request_review",
        "close_mission",
        "verified_complete",
    ]
    assert report["marker_count"] == 1
    assert report["chain_ok"] is True
