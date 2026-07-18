"""Memory consolidation & decay — keeps the memory base from becoming a landfill.

Two passes, both idempotent:
1. Near-duplicate merge: semantically near-identical L1 memories (cosine
   distance <= dedup_max_distance) are collapsed; the higher-priority / older
   record wins. Requires vectors; skipped in keyword-only mode.
2. Retention decay: episodic memories older than retention_episodic_days are
   deleted unless their priority >= retention_keep_priority. Disabled by
   default (retention_episodic_days=0). persona/instruction memories never
   decay.
"""
from __future__ import annotations

import logging

from ..config import Settings
from ..store import MemoryStore
from ..types import now_ms

log = logging.getLogger("zanii_memory.pipeline")

MS_PER_DAY = 86_400_000


def consolidate(store: MemoryStore, cfg: Settings) -> dict[str, int]:
    """Run both passes; returns {"duplicates_removed", "decayed"}."""
    duplicates_removed = 0
    pairs = store.find_near_duplicate_pairs(cfg.dedup_max_distance)
    if pairs:
        keep_ids = {keep for keep, _ in pairs}
        drop_ids = {drop for _, drop in pairs if drop not in keep_ids}
        duplicates_removed = store.delete_l1(sorted(drop_ids))
        log.info("Consolidation removed %d near-duplicate memories", duplicates_removed)

    decayed = 0
    if cfg.retention_episodic_days > 0:
        cutoff = now_ms() - cfg.retention_episodic_days * MS_PER_DAY
        old = store.get_l1_filtered(type="episodic", created_before=cutoff, limit=10_000)
        expired = [row["id"] for row in old if row["priority"] < cfg.retention_keep_priority]
        decayed = store.delete_l1(expired)
        if decayed:
            log.info("Retention decay removed %d episodic memories older than %d days",
                     decayed, cfg.retention_episodic_days)

    return {"duplicates_removed": duplicates_removed, "decayed": decayed}
