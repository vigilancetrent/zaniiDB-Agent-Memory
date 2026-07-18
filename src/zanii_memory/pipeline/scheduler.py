"""Pipeline scheduler: decides WHEN to run L1 extraction and L3 persona.

Triggers:
- every N captured turns (pending >= threshold)
- warmup: a fresh session triggers at turn 1, then thresholds double 1->2->4->...->N
- idle flush: sessions with pending turns and no activity for idle_timeout_s
- explicit flush on session end

State (watermark/pending/threshold) is persisted in the DB, so restarts never
re-extract the same rows.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field

from ..config import Settings
from ..embedding import EmbeddingClient
from ..llm import LLMClient
from ..store import MemoryStore
from .consolidate import consolidate
from .extractor import run_extraction
from .persona import persona_due, run_persona
from .skills import run_skills

log = logging.getLogger("zanii_memory.pipeline")

IDLE_CHECK_INTERVAL_S = 30.0


def next_threshold(current: int, every_n: int, warmup: bool) -> int:
    if not warmup:
        return every_n
    return min(max(current, 1) * 2, every_n)


@dataclass
class _SessionState:
    pending: int = 0
    threshold: int = 1
    last_activity: float = field(default_factory=time.monotonic)
    task: asyncio.Task | None = None


class PipelineScheduler:
    def __init__(self, store: MemoryStore, llm: LLMClient, embedder: EmbeddingClient, cfg: Settings):
        self.store = store
        self.llm = llm
        self.embedder = embedder
        self.cfg = cfg
        self.sessions: dict[str, _SessionState] = {}
        self._idle_task: asyncio.Task | None = None
        self._warned_no_llm = False

    def _state(self, session_key: str) -> _SessionState:
        if session_key not in self.sessions:
            persisted = self.store.get_pipeline_state(session_key)
            initial = 1 if self.cfg.pipeline_warmup else self.cfg.pipeline_every_n_turns
            self.sessions[session_key] = _SessionState(
                pending=persisted["pending"], threshold=max(persisted["threshold"], initial)
            )
        return self.sessions[session_key]

    def _persist(self, session_key: str, state: _SessionState) -> None:
        watermark = self.store.get_pipeline_state(session_key)["watermark"]
        self.store.set_pipeline_state(session_key, watermark, state.pending, state.threshold)

    def on_captured(self, session_key: str) -> None:
        """Called once per completed turn. May schedule a background extraction."""
        if not self.llm.enabled:
            if not self._warned_no_llm:
                log.info("LLM not configured — capture only, no memory extraction (set ZANII_LLM_* to enable)")
                self._warned_no_llm = True
            return
        state = self._state(session_key)
        state.pending += 1
        state.last_activity = time.monotonic()
        if state.pending >= state.threshold:
            self._launch(session_key, state)
        else:
            self._persist(session_key, state)

    def _launch(self, session_key: str, state: _SessionState) -> None:
        if state.task and not state.task.done():
            return  # one extraction per session at a time; pending keeps accruing
        state.pending = 0
        state.threshold = next_threshold(state.threshold, self.cfg.pipeline_every_n_turns, self.cfg.pipeline_warmup)
        self._persist(session_key, state)
        state.task = asyncio.create_task(self._run(session_key))

    async def _run(self, session_key: str) -> None:
        try:
            inserted = await run_extraction(self.store, self.llm, self.embedder, self.cfg, session_key)
            if inserted and persona_due(self.store, self.cfg):
                wrote = await run_persona(self.store, self.llm, self.cfg)
                consolidate(self.store, self.cfg)  # dedup + decay each persona cycle
                if wrote and self.cfg.pipeline_skills:
                    await run_skills(self.store, self.llm, self.cfg)
        except Exception:
            log.exception("Pipeline run failed (session=%s)", session_key)

    async def flush(self, session_key: str) -> None:
        """Extract now (session end). Waits for any in-flight run first."""
        if not self.llm.enabled:
            return
        state = self._state(session_key)
        if state.task and not state.task.done():
            await state.task
        state.pending = 0
        self._persist(session_key, state)
        await self._run(session_key)

    async def start(self) -> None:
        self._idle_task = asyncio.create_task(self._idle_loop())

    async def stop(self) -> None:
        if self._idle_task:
            self._idle_task.cancel()
            self._idle_task = None
        pending = [s.task for s in self.sessions.values() if s.task and not s.task.done()]
        if pending:
            await asyncio.wait(pending, timeout=30)

    async def _idle_loop(self) -> None:
        while True:
            await asyncio.sleep(IDLE_CHECK_INTERVAL_S)
            now = time.monotonic()
            for session_key, state in list(self.sessions.items()):
                if state.pending > 0 and now - state.last_activity > self.cfg.pipeline_idle_timeout_s:
                    self._launch(session_key, state)
