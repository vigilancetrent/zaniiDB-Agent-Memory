"""Provable-memory (Zanii ledger) integration tests — fully offline:
network submission is stubbed; chain building, persistence, and verification
use the real zanii.memory implementation."""
import json

import pytest

zanii_core = pytest.importorskip("zanii.core", reason="zanii SDK not installed")
from zanii.memory import verify_content, verify_memory_chain

from zanii_memory.core import MemoryCore
from zanii_memory.provable import ProvableLedger
from zanii_memory.store import SqliteStore


def make_cfg(cfg, tmp_path, enabled=True):
    if not enabled:
        return cfg
    identity = tmp_path / "identity.json"
    kp = zanii_core.generate_keypair()
    identity.write_text(
        json.dumps({"did": kp.did, "private_key_hex": kp.private_key.hex(), "delegation": []}),
        encoding="utf-8",
    )
    return cfg.model_copy(
        update={"ledger_url": "https://ledger.example", "ledger_identity_file": str(identity)}
    )


def test_disabled_by_default_is_noop(cfg, tmp_path):
    store = SqliteStore(tmp_path / "s.db")
    ledger = ProvableLedger(cfg, store)
    assert not ledger.enabled
    ledger.emit("l1.insert", "anything")  # must not raise or write
    assert not (cfg.data_dir / "ledger_entries.jsonl").exists()
    store.close()


def test_chain_builds_verifies_and_survives_submit_failure(cfg, tmp_path, monkeypatch):
    cfg = make_cfg(cfg, tmp_path)
    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    store = SqliteStore(tmp_path / "s.db")
    ledger = ProvableLedger(cfg, store)
    assert ledger.enabled

    submitted = []
    monkeypatch.setattr(ledger, "_submit", lambda entry: submitted.append(entry))
    ledger.emit("l1.insert", "The user prefers tea")
    ledger.emit("l1.supersede", json.dumps({"old_id": "a", "new_id": "b"}))
    ledger.emit("persona.update", "# User Narrative Profile")

    assert len(submitted) == 3
    entries = [json.loads(l) for l in ledger.entries_path.read_text(encoding="utf-8").splitlines()]
    report = verify_memory_chain(entries)
    assert report["ok"] and report["length"] == 3
    assert [e["payload"]["seq"] for e in entries] == [0, 1, 2]
    # the raw content never leaves; the local salt can PROVE it later
    e0 = entries[0]
    assert "The user prefers tea" not in json.dumps(e0["payload"])
    assert verify_content("The user prefers tea", e0["salt"], e0["payload"]["content_commitment"])

    # a dying ledger must never break memory operations
    def boom(entry):
        raise RuntimeError("ledger down")

    monkeypatch.setattr(ledger, "_submit", boom)
    ledger.emit("l1.insert", "still fine")  # swallowed + warned, no raise
    assert len([l for l in ledger.entries_path.read_text(encoding="utf-8").splitlines() if l]) == 3
    store.close()


async def test_seed_emits_receipts_through_core(cfg, tmp_path, monkeypatch):
    cfg = make_cfg(cfg, tmp_path)
    core = MemoryCore(cfg)
    await core.initialize()
    submitted = []
    monkeypatch.setattr(core.ledger, "_submit", lambda e: submitted.append(e))
    await core.seed([{"content": "Team rule: receipts for everything", "type": "instruction"}])
    assert len(submitted) == 1
    assert submitted[0]["payload"]["kind"] == "l1.seed"
    await core.close()
