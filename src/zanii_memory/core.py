"""MemoryCore — the host-neutral facade. The SDK entry point.

    from zanii_memory import ZaniiMemory

    memory = ZaniiMemory()          # config from ZANII_* env vars
    await memory.initialize()
    recall = await memory.recall("what does the user prefer?", session_key="s1")
    await memory.capture("s1", [{"role": "user", "content": "..."},
                                {"role": "assistant", "content": "..."}])
    await memory.close()
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from .config import Settings
from .embedding import EmbeddingClient
from .llm import LLMClient
from .pipeline import PipelineScheduler
from .offload import Offloader
from .pipeline.consolidate import consolidate
from .pipeline.skills import run_skills
from .recall import perform_recall, query_embedding
from .store import MemoryStore, create_store
from .types import MEMORY_SCOPES, MEMORY_TYPES, MemoryRecord, RecallResult, new_id, now_ms

log = logging.getLogger("zanii_memory.core")

_CAPTURE_ROLES = {"user", "assistant"}


class MemoryCore:
    def __init__(self, config: Settings | None = None):
        self.cfg = config or Settings()
        self.llm = LLMClient(self.cfg)
        self.embedder = EmbeddingClient(self.cfg)
        self.store: MemoryStore | None = None
        self.scheduler: PipelineScheduler | None = None
        self.offloader = Offloader(self.cfg)

    async def initialize(self) -> None:
        self.cfg.data_dir.mkdir(parents=True, exist_ok=True)
        self.cfg.scenes_dir.mkdir(parents=True, exist_ok=True)
        self.store = create_store(self.cfg, want_vectors=self.embedder.enabled)
        self.scheduler = PipelineScheduler(self.store, self.llm, self.embedder, self.cfg)
        await self.scheduler.start()
        log.info(
            "MemoryCore ready (data=%s, llm=%s, embeddings=%s, vectors=%s)",
            self.cfg.data_dir,
            self.llm.enabled,
            self.embedder.enabled,
            self.store.vec_enabled,
        )

    async def close(self) -> None:
        if self.scheduler:
            await self.scheduler.stop()
        await self.llm.close()
        await self.embedder.close()
        if self.store:
            self.store.close()

    # ============================
    # Capture / recall
    # ============================

    async def capture(
        self, session_key: str, messages: list[dict[str, Any]], session_id: str = ""
    ) -> dict[str, int]:
        """Record one completed turn (a list of role/content messages)."""
        assert self.store and self.scheduler, "call initialize() first"
        recorded = 0
        for msg in messages:
            role = str(msg.get("role", ""))
            content = str(msg.get("content", "")).strip()
            if role not in _CAPTURE_ROLES or not content:
                continue
            ts = msg.get("timestamp")
            ts = int(ts) if isinstance(ts, (int, float)) and ts > 0 else None
            self.store.record_l0(session_key, role, content, ts, session_id)
            recorded += 1
        if recorded:
            self.scheduler.on_captured(session_key)
            self._audit("capture", f"{session_key}: {recorded} messages")
        return {"recorded": recorded}

    async def recall(self, query: str, session_key: str) -> RecallResult:
        assert self.store, "call initialize() first"
        self._audit("recall", f"{session_key}: {query[:200]}")
        return await perform_recall(self.store, self.embedder, self.cfg, query, session_key)

    # ============================
    # Search tools
    # ============================

    async def search_memories(
        self,
        query: str,
        limit: int = 10,
        type: str | None = None,
        since: int | None = None,
        until: int | None = None,
    ) -> list[dict[str, Any]]:
        """Hybrid search; since/until are epoch-ms bounds on memory creation time."""
        assert self.store, "call initialize() first"
        self._audit("search_memories", query[:200])
        embedding = await query_embedding(self.embedder, self.cfg, query)
        return self.store.hybrid_search_l1(query, embedding, limit=limit, type=type, since=since, until=until)

    async def search_conversations(
        self, query: str, limit: int = 10, session_key: str | None = None
    ) -> list[dict[str, Any]]:
        assert self.store, "call initialize() first"
        return self.store.search_l0(query, limit=limit, session_key=session_key)

    # ============================
    # Lifecycle / seeding
    # ============================

    async def end_session(self, session_key: str) -> None:
        """Flush pending turns through extraction immediately."""
        assert self.scheduler, "call initialize() first"
        await self.scheduler.flush(session_key)

    async def seed(self, memories: list[dict[str, Any]]) -> int:
        """Directly insert L1 memories (SOPs, facts) without the LLM pipeline."""
        assert self.store, "call initialize() first"
        inserted = 0
        for mem in memories:
            content = str(mem.get("content", "")).strip()
            if not content or self.store.l1_content_exists(content):
                continue
            mem_type = mem.get("type", "persona")
            if mem_type not in MEMORY_TYPES:
                mem_type = "persona"
            embedding = None
            if self.embedder.enabled and self.store.vec_enabled:
                try:
                    embedding = await self.embedder.embed_one(content)
                except Exception as err:
                    log.warning("Seed embedding failed (stored without vector): %s", err)
            scope = mem.get("scope", "user")
            if scope not in MEMORY_SCOPES:
                scope = "user"
            record = MemoryRecord(
                content=content,
                type=mem_type,
                priority=int(mem.get("priority", 80)),
                scope=scope,
                scene_name=str(mem.get("scene_name", "seeded")),
            )
            self.store.insert_l1(record, embedding)
            inserted += 1
        self._audit("seed", f"{inserted} memories")
        return inserted

    # ============================
    # Consolidation, skills, audit
    # ============================

    async def consolidate(self) -> dict[str, int]:
        """Merge near-duplicate memories and apply retention decay."""
        assert self.store, "call initialize() first"
        result = consolidate(self.store, self.cfg)
        self._audit("consolidate", str(result))
        return result

    async def generate_skills(self) -> int:
        """Distill SOP/skill documents from episodic + instruction memories."""
        assert self.store, "call initialize() first"
        if not self.llm.enabled:
            raise RuntimeError("Skill generation requires an LLM (set ZANII_LLM_*)")
        return await run_skills(self.store, self.llm, self.cfg)

    def audit_log(self, limit: int = 100) -> list[dict[str, Any]]:
        assert self.store, "call initialize() first"
        return self.store.get_audit(limit)

    def _audit(self, op: str, detail: str) -> None:
        if self.cfg.audit_enabled and self.store:
            try:
                self.store.audit(op, detail)
            except Exception as err:
                log.warning("Audit write failed: %s", err)

    # ============================
    # Context offload (short-term memory)
    # ============================

    async def offload(self, session_key: str, content: str, label: str = "") -> dict[str, Any]:
        """Store verbose content externally; returns {node_id, stub, chars}."""
        return self.offloader.offload(session_key, content, label)

    async def retrieve_ref(self, node_id: str) -> str | None:
        return self.offloader.retrieve(node_id)

    async def get_canvas(self, session_key: str) -> str:
        return self.offloader.canvas(session_key)

    # ============================
    # Export / import (portable memory, backend migration)
    # ============================

    async def export_memory(self) -> dict[str, Any]:
        """Complete portable memory snapshot (memories, conversations, persona, scenes)."""
        assert self.store, "call initialize() first"
        scenes = {}
        if self.cfg.scenes_dir.exists():
            for path in sorted(self.cfg.scenes_dir.glob("*.md")):
                scenes[path.name] = path.read_text(encoding="utf-8")
        return {
            "version": 1,
            "l1_records": self.store.get_all_l1(),
            "l0_conversations": self.store.get_all_l0(),
            "persona": self.cfg.persona_path.read_text(encoding="utf-8")
            if self.cfg.persona_path.exists()
            else None,
            "scenes": scenes,
        }

    async def import_memory(self, data: dict[str, Any]) -> dict[str, int]:
        """Idempotent import of an export_memory() snapshot. Re-embeds L1 when
        embeddings are enabled. Persona/scene files are only written when the
        local file does not exist (local state wins)."""
        assert self.store, "call initialize() first"
        if data.get("version") != 1:
            raise ValueError(f"Unsupported export version: {data.get('version')!r}")

        l1_inserted = 0
        superseded_links: list[tuple[str, str]] = []
        for row in data.get("l1_records", []):
            content = str(row.get("content", "")).strip()
            if not content or self.store.l1_content_exists(content):
                continue
            embedding = None
            if self.embedder.enabled and self.store.vec_enabled:
                try:
                    embedding = await self.embedder.embed_one(content)
                except Exception as err:
                    log.warning("Import embedding failed (stored without vector): %s", err)
            metadata = row.get("metadata", "{}")
            if isinstance(metadata, str):
                try:
                    metadata = json.loads(metadata)
                except json.JSONDecodeError:
                    metadata = {}
            record = MemoryRecord(
                content=content,
                type=row.get("type", "persona"),
                priority=int(row.get("priority", 60)),
                scene_name=str(row.get("scene_name", "")),
                session_key=str(row.get("session_key", "")),
                session_id=str(row.get("session_id", "")),
                metadata=metadata,
                id=str(row.get("id") or new_id()),
                created_at=int(row.get("created_at") or now_ms()),
                updated_at=int(row.get("updated_at") or now_ms()),
            )
            self.store.insert_l1(record, embedding)
            if row.get("superseded_by"):
                superseded_links.append((record.id, str(row["superseded_by"])))
            l1_inserted += 1
        # restore conflict-resolution state — superseded memories must not resurrect
        for old_id, new_id in superseded_links:
            self.store.mark_superseded([old_id], new_id)

        l0_inserted = 0
        for row in data.get("l0_conversations", []):
            content = str(row.get("content", ""))
            session_key = str(row.get("session_key", ""))
            timestamp = int(row.get("timestamp") or 0)
            if not content or not session_key or not timestamp:
                continue
            if self.store.l0_exists(session_key, str(row.get("role", "user")), content, timestamp):
                continue
            self.store.record_l0(
                session_key, str(row.get("role", "user")), content, timestamp, str(row.get("session_id", ""))
            )
            l0_inserted += 1

        if data.get("persona") and not self.cfg.persona_path.exists():
            self.cfg.persona_path.write_text(str(data["persona"]), encoding="utf-8")
        scenes_written = 0
        for name, text in (data.get("scenes") or {}).items():
            target = self.cfg.scenes_dir / Path(name).name  # strip any path components
            if not target.exists():
                target.write_text(str(text), encoding="utf-8")
                scenes_written += 1

        return {"l1_inserted": l1_inserted, "l0_inserted": l0_inserted, "scenes_written": scenes_written}

    def stats(self) -> dict[str, Any]:
        assert self.store, "call initialize() first"
        return {
            **self.store.stats(),
            "llm": self.llm.enabled,
            "embeddings": self.embedder.enabled,
            "persona": self.cfg.persona_path.exists(),
            "data_dir": str(self.cfg.data_dir),
        }


# Public SDK alias
ZaniiMemory = MemoryCore
