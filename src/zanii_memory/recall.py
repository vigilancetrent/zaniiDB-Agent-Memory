"""Recall: hybrid search over L1 + persona injection, within char budgets."""
from __future__ import annotations

import asyncio
import logging

from .config import Settings
from .embedding import EmbeddingClient
from .pipeline.skills import find_relevant_skill
from .store import MemoryStore
from .types import RecallResult

log = logging.getLogger("zanii_memory.recall")


async def query_embedding(embedder: EmbeddingClient, cfg: Settings, query: str) -> list[float] | None:
    if cfg.recall_strategy == "keyword" or not embedder.enabled:
        return None
    try:
        return await asyncio.wait_for(embedder.embed_one(query), timeout=cfg.recall_timeout_s)
    except Exception as err:
        log.warning("Query embedding failed, falling back to keyword search: %s", err)
        return None


async def perform_recall(
    store: MemoryStore, embedder: EmbeddingClient, cfg: Settings, query: str, session_key: str
) -> RecallResult:
    embedding = await query_embedding(embedder, cfg, query)
    if cfg.recall_strategy == "embedding" and embedding is not None:
        hits = store.vector_search_l1(embedding, limit=cfg.recall_max_results)
        strategy = "embedding"
    else:
        hits = store.hybrid_search_l1(query, embedding, limit=cfg.recall_max_results)
        strategy = "hybrid" if embedding is not None else "keyword"

    if cfg.recall_chronological:
        hits = sorted(hits, key=lambda h: h["created_at"])

    memories = []
    lines = []
    total = 0
    for hit in hits:
        line = f"- [{hit['type']}] {hit['content']}"
        if cfg.recall_max_total_chars and total + len(line) > cfg.recall_max_total_chars:
            break
        lines.append(line)
        total += len(line)
        memories.append({"content": hit["content"], "type": hit["type"], "score": hit["score"]})

    prepend = ""
    if lines:
        header = "## Relevant memories (auto-recalled, verify before relying on them)"
        if cfg.recall_chronological:
            header += "\n(ordered oldest to newest — the later entries reflect the user's most recent state)"
        prepend = header + "\n" + "\n".join(lines)

    system_parts = []
    if cfg.persona_path.exists():
        persona = cfg.persona_path.read_text(encoding="utf-8").strip()
        if persona:
            system_parts.append(f"## User persona (long-term memory)\n\n{persona}")
    team_rows = store.get_l1_filtered(scope="team", limit=10)
    if team_rows:
        team_lines = "\n".join(f"- [{r['type']}] {r['content']}" for r in team_rows)
        system_parts.append(f"## Team knowledge (shared org memory)\n\n{team_lines}")
    if cfg.recall_skills:
        skill = find_relevant_skill(cfg.skills_dir, query)
        if skill:
            system_parts.append(f"## Learned procedure (from past runs — follow unless it conflicts)\n\n{skill}")
    append_system = "\n\n".join(system_parts)

    return RecallResult(
        prepend_context=prepend,
        append_system_context=append_system,
        memories=memories,
        strategy=strategy,
    )
