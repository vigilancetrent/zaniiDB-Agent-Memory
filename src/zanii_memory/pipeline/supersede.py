"""Conflict resolution: new memories supersede outdated ones.

Insert-only memory hoards contradictions — "prefers coffee" and "switched to
tea" coexist and recall serves both, forcing the agent to guess which is
current. After each extraction batch, semantically-near existing memories are
gathered per new memory and ONE LLM call decides which are contradicted or
updated. Superseded memories are kept (white-box history, traceable via
superseded_by) but excluded from every search and recall path.
"""
from __future__ import annotations

import json
import logging
import re

from ..config import Settings
from ..llm import LLMClient
from ..provable import emit_via_store
from ..store import MemoryStore
from ..types import MemoryRecord

log = logging.getLogger("zanii_memory.pipeline")

SUPERSEDE_SYSTEM_PROMPT = """You maintain an AI agent's long-term memory about a user.
You are given NEW memories, each followed by EXISTING candidate memories that are semantically close.

For each new memory give ONE verdict:
1. DUPLICATE — the new memory states essentially the SAME fact as an existing one, just reworded
   or with trivially different detail. No actual change of state, preference, or rule.
   -> {"new_id": "<id>", "duplicate_of": "<existing_id>"}
2. SUPERSEDES — the new memory genuinely contradicts or changes the state of the same fact,
   preference, plan, or rule (changed preference, moved home/job, revised decision, replaced
   standing instruction). Rewording is NOT a change — when in doubt between duplicate and
   supersedes, choose duplicate.
   -> {"new_id": "<id>", "supersedes": ["<existing_id>", ...]}
3. DISTINCT — merely related, complementary, a different aspect, or a separate event
   (two events can both be true) -> omit the entry entirely.

Output raw JSON only, no fences or commentary: a list of verdict objects.
If every new memory is distinct, output []."""


def parse_supersede(text: str) -> list[dict]:
    cleaned = re.sub(r"^```[a-z]*\s*|\s*```$", "", text.strip(), flags=re.MULTILINE)
    start, end = cleaned.find("["), cleaned.rfind("]")
    if start == -1 or end <= start:
        return []
    try:
        data = json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError:
        return []
    return [d for d in data if isinstance(d, dict) and d.get("new_id")]


async def resolve_conflicts(
    store: MemoryStore,
    llm: LLMClient,
    cfg: Settings,
    new_items: list[tuple[MemoryRecord, list[float] | None]],
) -> int:
    """Returns the number of memories marked superseded. Zero-cost when no new
    memory has semantically-near existing neighbors."""
    pairs: list[tuple[MemoryRecord, list[dict]]] = []
    new_ids = {record.id for record, _ in new_items}
    for record, embedding in new_items:
        if embedding is None or not store.vec_enabled:
            continue
        candidates = [
            h
            for h in store.vector_search_l1(embedding, limit=6)
            if h["id"] != record.id
            and h["id"] not in new_ids  # never supersede same-batch siblings
            and h["type"] == record.type  # guard: a memory can only supersede its own type
            and h.get("distance", 1.0) <= cfg.supersede_max_distance
        ][:3]
        if candidates:
            pairs.append((record, candidates))
    if not pairs:
        return 0

    lines = []
    for record, candidates in pairs:
        lines.append(f"NEW {record.id}: [{record.type}] {record.content}")
        for c in candidates:
            lines.append(f"  EXISTING {c['id']}: [{c['type']}] {c['content']}")
    text = await llm.complete("\n".join(lines), system=SUPERSEDE_SYSTEM_PROMPT, timeout=60, max_tokens=1000)

    candidate_ids = {c["id"] for _, cands in pairs for c in cands}
    content_by_id = {c["id"]: c["content"] for _, cands in pairs for c in cands}
    new_by_id = {record.id: record.content for record, _ in pairs}
    valid_new = {record.id for record, _ in pairs}
    superseded = 0
    for item in parse_supersede(text):
        if item["new_id"] not in valid_new:
            continue
        duplicate_of = item.get("duplicate_of")
        if duplicate_of and duplicate_of in candidate_ids:
            # Paraphrase re-extraction: drop the NEW copy, keep the original —
            # prevents fact churn (the ping-pong the 2026-07-18 audit caught).
            store.delete_l1([item["new_id"]])
            log.info(
                "DUPLICATE dropped: %r (same as existing %r)",
                new_by_id[item["new_id"]][:120],
                content_by_id[duplicate_of][:120],
            )
            continue
        old_ids = [i for i in item.get("supersedes", []) if i in candidate_ids]
        if old_ids:
            superseded += store.mark_superseded(old_ids, item["new_id"])
            for old_id in old_ids:  # audit trail: exactly what replaced what
                log.info(
                    "SUPERSEDE: %r -> replaced by %r",
                    content_by_id.get(old_id, old_id)[:120],
                    new_by_id[item["new_id"]][:120],
                )
                emit_via_store(
                    store, "l1.supersede",
                    json.dumps({"old_id": old_id, "new_id": item["new_id"]}, sort_keys=True),
                )
    if superseded:
        log.info("Conflict resolution superseded %d outdated memories", superseded)
    return superseded
