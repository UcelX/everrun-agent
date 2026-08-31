from __future__ import annotations

import json
from pathlib import Path

import pytest

from everrun_agent import EverRunStore, Mission
from everrun_agent.attestation import (
    AttestationError,
    generate_keypair,
    sign_capsule,
    verify_capsule_signature,
)
from everrun_agent.capsule import export_capsule, import_capsule


def test_signed_capsule_verifies_with_known_key(tmp_path: Path) -> None:
    private_key, public_key = generate_keypair()
    with EverRunStore(tmp_path / "everrun.db") as store:
        store.create_mission(Mission("m1", "signed", 1))
        store.append_work("m1", "a")
        capsule = export_capsule(store, "m1", tmp_path / "mission.rly")
    signed = sign_capsule(capsule, private_key, signer="ucel-workstation")
    assert verify_capsule_signature(signed, {"ucel-workstation": public_key})
    payload = json.loads(signed.read_text(encoding="utf-8"))
    assert payload["signature"]["signer"] == "ucel-workstation"
    assert payload["signature"]["algorithm"] == "hmac-sha256"


def test_tampered_signed_capsule_is_rejected(tmp_path: Path) -> None:
    private_key, public_key = generate_keypair()
    with EverRunStore(tmp_path / "everrun.db") as store:
        store.create_mission(Mission("m1", "signed", 1))
        capsule = export_capsule(store, "m1", tmp_path / "mission.rly")
    signed = sign_capsule(capsule, private_key, signer="ucel")
    payload = json.loads(signed.read_text(encoding="utf-8"))
    payload["body"]["mission"]["goal"] = "hijacked"
    signed.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(AttestationError):
        verify_capsule_signature(signed, {"ucel": public_key})


def test_unknown_signer_is_not_trusted(tmp_path: Path) -> None:
    private_key, _ = generate_keypair()
    _, other_public = generate_keypair()
    with EverRunStore(tmp_path / "everrun.db") as store:
        store.create_mission(Mission("m1", "signed", 1))
        capsule = export_capsule(store, "m1", tmp_path / "mission.rly")
    signed = sign_capsule(capsule, private_key, signer="stranger")
    with pytest.raises(AttestationError):
        verify_capsule_signature(signed, {"trusted": other_public})


def test_signed_capsule_can_be_imported_after_verification(tmp_path: Path) -> None:
    private_key, public_key = generate_keypair()
    with EverRunStore(tmp_path / "a.db") as store:
        store.create_mission(Mission("m1", "portable", 1))
        store.append_work("m1", "a")
        capsule = export_capsule(store, "m1", tmp_path / "mission.rly")
    signed = sign_capsule(capsule, private_key, signer="ucel")
    assert verify_capsule_signature(signed, {"ucel": public_key})
    with EverRunStore(tmp_path / "b.db") as target:
        assert import_capsule(target, signed, trusted_keys={"ucel": public_key}) == "m1"
        assert target.verify_chain("m1").ok


def test_storage_backend_contract_is_explicit() -> None:
    from everrun_agent.storage import StorageBackend

    assert hasattr(StorageBackend, "append")
    assert hasattr(StorageBackend, "events")
    assert hasattr(StorageBackend, "verify_chain")
    assert issubclass(EverRunStore, StorageBackend)
