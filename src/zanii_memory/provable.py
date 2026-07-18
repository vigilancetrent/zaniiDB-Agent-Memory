"""Provable memory — optional Zanii transparency-ledger integration.

When enabled, every memory mutation (extract, seed, supersede, persona update)
emits a hash-chained `zanii.memory` receipt to a Zanii ledger: an append-only,
Merkle-verified record of WHAT this agent remembered and WHEN, verifiable
offline by anyone. Only a salted content commitment leaves the machine — the
raw memory never does. Full entries (with their proof salts) are kept locally
in `ledger_entries.jsonl`, so `zanii-memory ledger-verify` can check the whole
chain for tampering at any time.

Enable:
    pip install "zaniidb-agent-memory[provable]"
    zanii-memory ledger-init                      # creates identity + delegation
    export ZANII_LEDGER_URL=https://ledger.zanii.agency
    export ZANII_LEDGER_API_KEY=zk_live_...       # writes need a key; reads are public

Off by default; a ledger failure never breaks memory operations.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import Settings
from .store import MemoryStore

log = logging.getLogger("zanii_memory.provable")

PREV_KV_KEY = "zanii_ledger_prev"


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


class ProvableLedger:
    def __init__(self, cfg: Settings, store: MemoryStore):
        self.cfg = cfg
        self.store = store
        self.enabled = False
        self._agent = None
        self._warned = False
        if not (cfg.ledger_url and cfg.ledger_identity_file):
            return
        try:
            from zanii import ZaniiAgent
        except ImportError:
            log.warning(
                "ZANII_LEDGER_URL is set but the 'zanii' package is missing — "
                "pip install \"zaniidb-agent-memory[provable]\""
            )
            return
        try:
            identity = json.loads(Path(cfg.ledger_identity_file).read_text(encoding="utf-8"))
            self._agent = ZaniiAgent(
                server_url=cfg.ledger_url.rstrip("/"),
                agent_did=identity["did"],
                agent_private_key=bytes.fromhex(identity["private_key_hex"]),
                delegation=identity.get("delegation", []),
                api_key=cfg.ledger_api_key or None,
            )
            self.enabled = True
            log.info("Provable memory ledger active (%s, agent %s…)", cfg.ledger_url, identity["did"][:24])
        except Exception as err:
            log.warning("Provable ledger disabled (identity load failed): %r", err)

    @property
    def entries_path(self) -> Path:
        return self.cfg.data_dir / "ledger_entries.jsonl"

    def emit(self, kind: str, content: str) -> None:
        """Append one hash-chained memory entry and receipt it. Never raises."""
        if not self.enabled:
            return
        try:
            from zanii.memory import append_memory

            prev_raw = self.store.get_kv(PREV_KV_KEY)
            prev = json.loads(prev_raw) if prev_raw else None
            entry = append_memory(prev, content=content, kind=kind, ts=_now_iso())
            self._submit(entry)
            self.store.set_kv(PREV_KV_KEY, json.dumps(entry))
            with self.entries_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception as err:
            if not self._warned:
                log.warning("Provable receipt failed (memory operations unaffected): %r", err)
                self._warned = True

    def _submit(self, entry: dict[str, Any]) -> None:
        # The payload carries only the salted content commitment + chain links;
        # the raw content and the proof salt stay local (entries_path).
        self._agent.record(target=entry["target"], payload=entry["payload"])

    def close(self) -> None:
        if self.enabled and self._agent is not None:
            try:
                self._agent.flush()
            except Exception as err:
                log.warning("Ledger flush failed: %r", err)


def emit_via_store(store: MemoryStore, kind: str, content: str) -> None:
    """Pipeline hook: emits when core attached a ledger to the store (duck-typed
    so pipeline functions need no signature changes)."""
    ledger = getattr(store, "ledger", None)
    if ledger is not None:
        ledger.emit(kind, content)
