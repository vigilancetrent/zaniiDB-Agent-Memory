"""L1 extraction: scene segmentation + atomic memory extraction in one LLM call.

Three memory types (persona / episodic / instruction), priority scoring, and
scene continuity, with a match-the-user's-language output contract.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any

from ..config import Settings
from ..embedding import EmbeddingClient
from ..llm import LLMClient
from ..store import MemoryStore
from ..provable import emit_via_store
from ..types import MEMORY_TYPES, MemoryRecord
from .scenes import append_scene_facts, maybe_condense_scene
from .supersede import resolve_conflicts

log = logging.getLogger("zanii_memory.pipeline")

# Cosine distance below which a new memory is considered a duplicate.
DEDUP_DISTANCE = 0.12
MIN_PRIORITY = 50

EXTRACTION_SYSTEM_PROMPT = """You are an expert in scene segmentation and long-term memory extraction for an AI agent.
Analyze the user's conversation, detect scene switches, and extract structured core memories (only the three types: persona, episodic, instruction).

**Output language**: write all free-text fields (`scene_name`, memory `content`) in the same language the user writes in. Keep JSON field names, enum values, and ISO timestamps in English.

### Task 1: Scene segmentation
Given the [previous scene] and the [new messages], decide the current scene(s).
- Inherit: no clear switch -> keep the previous scene name.
- Switch when: the user explicitly changes topic, their intent shifts, or a new independent goal appears.
- A conversation slice may contain one scene or several.
- Naming rule: "I (the AI) am helping <who the user is> with <goal activity>" — one sentence, ~30-60 characters, globally unique.

### Task 2: Memory extraction
Extract core information ONLY from the [new messages], using the background for context.

General principles:
1. Less is more: filter out small talk, one-off requests ("this time", "this order"), and unreliable marginal information.
2. Self-contained: each memory must make sense outside this conversation, with "The user (<name>)" or "The AI" as the subject.
3. Merge related: strongly related or causal messages must be merged into one complete memory — never fragment.

Supported types (follow the rules strictly):
1. persona — stable attributes, preferences, skills, values, habits (home, job, dietary restrictions...).
   Pattern: "The user (<name>) likes/is/excels at ...". Priority: 80-100 health/taboos/core traits; 50-70 general preferences/skills; <50 vague or minor (drop).
2. episodic — objective actions, decisions, plans, or outcomes. Never pure feelings.
   Pattern: "The user (<name>) did <what> at <absolute time if inferable> in <place> (may include cause/process/result)".
   When the activity time can be inferred from message timestamps, put ISO-8601 "activity_start_time"/"activity_end_time" in metadata.
   Priority: 80-100 important events/plans; 60-70 ordinary complete activities; <60 trivia (drop).
3. instruction — long-term behavior rules the user gives the AI (format, tone, workflow).
   Pattern: "The user requires the AI to ...". Trigger words: "from now on", "always", "remember", "must".
   Priority: -1 absolute standing order; 90-100 core rules; 70-80 important requests; <70 temporary (drop).

Do NOT extract: greetings/small talk, one-off tool requests, duplicates, the AI's own output, pure subjective feelings, anything outside the three types.

### Task 3: Output format
Return ONLY a valid JSON array. Each item is one scene:

[
  {
    "scene_name": "current or inherited scene name",
    "memories": [
      {
        "content": "complete, self-contained memory statement",
        "type": "persona|episodic|instruction",
        "priority": 80,
        "metadata": {}
      }
    ]
  }
]

If nothing is worth remembering, still output the scene segmentation with an empty "memories" array.
Output raw JSON only — no markdown fences, no commentary."""


def _fmt_ts(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def build_extraction_prompt(
    new_messages: list[dict[str, Any]],
    background: list[dict[str, Any]],
    previous_scene: str,
) -> str:
    def fmt(rows: list[dict[str, Any]]) -> str:
        return "\n\n".join(f"[{r['id']}] [{r['role']}] [{_fmt_ts(r['timestamp'])}]: {r['content']}" for r in rows)

    bg = fmt(background) if background else "(none)"
    return f"""**All timestamps are UTC.**

[Previous scene]: {previous_scene or "(none)"}

[Background conversation] (context only — NEVER extract memories from it):
{bg}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

[New messages] (infer times from timestamps; extract memories ONLY from here):
{fmt(new_messages)}"""


def parse_extraction(text: str) -> list[dict[str, Any]]:
    """Lenient parse: strip fences, locate the outermost JSON array, validate items."""
    cleaned = re.sub(r"^```[a-z]*\s*|\s*```$", "", text.strip(), flags=re.MULTILINE)
    start, end = cleaned.find("["), cleaned.rfind("]")
    if start == -1 or end <= start:
        return []
    try:
        data = json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    scenes = []
    for item in data:
        if not isinstance(item, dict) or not item.get("scene_name"):
            continue
        memories = []
        for mem in item.get("memories") or []:
            if not isinstance(mem, dict) or not mem.get("content"):
                continue
            if mem.get("type") not in MEMORY_TYPES:
                continue
            try:
                priority = int(mem.get("priority", 60))
            except (TypeError, ValueError):
                priority = 60
            memories.append(
                {
                    "content": str(mem["content"]).strip(),
                    "type": mem["type"],
                    "priority": priority,
                    "metadata": mem.get("metadata") if isinstance(mem.get("metadata"), dict) else {},
                }
            )
        scenes.append({"scene_name": str(item["scene_name"]).strip(), "memories": memories})
    return scenes


async def run_extraction(
    store: MemoryStore,
    llm: LLMClient,
    embedder: EmbeddingClient,
    cfg: Settings,
    session_key: str,
) -> int:
    """Extract L1 memories from un-processed L0 rows of one session.

    Returns the number of memories inserted. Advances the watermark even when
    nothing was extracted, so the same rows are never re-processed.
    """
    state = store.get_pipeline_state(session_key)
    rows = store.get_l0_after(session_key, state["watermark"], limit=200)
    if not rows:
        return 0

    background = store.get_l0_before(session_key, state["watermark"], limit=6)
    previous_scene = store.get_kv(f"scene:{session_key}") or ""
    prompt = build_extraction_prompt(rows, background, previous_scene)

    text = await llm.complete(prompt, system=EXTRACTION_SYSTEM_PROMPT, timeout=240)
    scenes = parse_extraction(text)
    if not scenes:
        log.warning("Extraction for %s produced no parseable scenes", session_key)

    inserted = 0
    kept_with_embeddings: list[tuple[MemoryRecord, list[float] | None]] = []
    for scene in scenes:
        kept: list[MemoryRecord] = []
        for mem in scene["memories"][: cfg.pipeline_max_memories]:
            if not (mem["priority"] >= MIN_PRIORITY or mem["priority"] == -1):
                continue
            if store.l1_content_exists(mem["content"]):
                continue
            embedding = None
            if embedder.enabled and store.vec_enabled:
                try:
                    embedding = await embedder.embed_one(mem["content"])
                    distance = store.nearest_l1_distance(embedding)
                    if distance is not None and distance < DEDUP_DISTANCE:
                        continue  # semantic duplicate
                except Exception as err:
                    log.warning("Embedding failed during extraction (stored without vector): %s", err)
            record = MemoryRecord(
                content=mem["content"],
                type=mem["type"],
                priority=mem["priority"],
                scene_name=scene["scene_name"],
                session_key=session_key,
                metadata=mem["metadata"],
            )
            store.insert_l1(record, embedding)
            emit_via_store(store, "l1.insert", record.content)
            kept.append(record)
            kept_with_embeddings.append((record, embedding))
            inserted += 1
        if kept:
            scene_path = append_scene_facts(cfg.scenes_dir, scene["scene_name"], kept)
            try:
                await maybe_condense_scene(scene_path, llm, cfg.scene_condense_chars)
            except Exception as err:
                log.warning("Scene condensation failed (ledger kept): %s", err)
        store.set_kv(f"scene:{session_key}", scene["scene_name"])

    if kept_with_embeddings:
        try:
            await resolve_conflicts(store, llm, cfg, kept_with_embeddings)
        except Exception as err:
            log.warning("Conflict resolution failed (memories kept unsuperseded): %s", err)

    new_watermark = max(r["id"] for r in rows)
    state = store.get_pipeline_state(session_key)  # re-read: pending may have grown meanwhile
    store.set_pipeline_state(session_key, new_watermark, state["pending"], state["threshold"])
    log.info("Extracted %d memories from %d messages (session=%s)", inserted, len(rows), session_key)
    return inserted
