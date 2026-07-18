"""L3 persona generation: distill scene blocks into persona.md.

Uses a four-layer deep-scan prompt (facts, interests, interaction protocol,
cognitive core). The LLM returns markdown and WE write the file — no file-tool
calling required, so any OpenAI-compatible endpoint works.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

from ..config import Settings
from ..llm import LLMClient
from ..store import MemoryStore
from .scenes import read_all_scenes

log = logging.getLogger("zanii_memory.pipeline")

PERSONA_KV_KEY = "persona_l1_count"

PERSONA_SYSTEM_PROMPT = """# Persona Architect — Incremental Evolution Protocol

You maintain `persona.md`, a narrative profile of the user, built ONLY from the scene evidence provided.

**Output language**: detect the dominant language of the scene content and write the persona (headings and body) in that language. Default to English when ambiguous. Keep markdown syntax in English.

## Hard constraints
- Output ONLY the final persona markdown document. No commentary, no reasoning, no code fences.
- Keep the document under 2000 characters — summarize and drop minor details as needed.
- Never invent facts not present in the scene evidence. When information is missing, leave the section short or omit it.
- No bullet-point spamming: find the connecting thread across behaviors and write coherent prose.

## Four-layer deep scan
1. Base & Facts — hard facts, demographics, current state (context anchors).
2. Interest Graph — what the user spends time/money/attention on; distinguish active vs passive interests.
3. Interaction Protocol — how the user wants the AI to speak, deliver, and what to avoid.
4. Cognitive Core — decision logic, productive contradictions, driving motivations.

## Template (adjust chapters when evidence is thin)

# User Narrative Profile

> **Archetype**: [one-sentence core archetype]

> **Basic Information**
 - ...

> **Long-term Preferences**
 - ...

## Chapter 1: Context & Current State
[coherent prose]

## Chapter 2: The Texture of Life
[coherent prose]

## Chapter 3: Interaction Protocol
### 3.1 How to Speak
### 3.2 How to Think

## Chapter 4: Deep Insights
* **Productive Contradictions**: ...
* **Emergent Traits**: 3-7 tags, one per line: `TagName` - short note"""


def _strip_fences(text: str) -> str:
    return re.sub(r"^```[a-z]*\s*|\s*```$", "", text.strip(), flags=re.MULTILINE).strip()


async def run_persona(store: MemoryStore, llm: LLMClient, cfg: Settings) -> bool:
    """Regenerate persona.md from scene blocks. Returns True when written."""
    scenes_text = read_all_scenes(cfg.scenes_dir)
    if not scenes_text:
        return False
    existing = cfg.persona_path.read_text(encoding="utf-8") if cfg.persona_path.exists() else ""
    total = store.count_l1()
    mode = "Incremental update" if existing else "First generation"

    existing_section = (
        f"\n## Current persona.md (update it, keep under 2000 chars)\n\n{existing}\n\n---\n" if existing else ""
    )
    prompt = f"""**Updated at**: {datetime.now(tz=timezone.utc).isoformat(timespec="seconds")}
**Mode**: {mode}
**Total memories**: {total}

## Scene evidence (the ONLY allowed source of facts)

{scenes_text}
{existing_section}
Write the complete new persona.md now."""

    text = await llm.complete(prompt, system=PERSONA_SYSTEM_PROMPT, timeout=180, max_tokens=3000)
    persona = _strip_fences(text)
    if len(persona) < 40:  # refuse to overwrite with garbage
        log.warning("Persona generation returned too little content; keeping existing persona")
        return False
    cfg.persona_path.write_text(persona, encoding="utf-8")
    store.set_kv(PERSONA_KV_KEY, str(total))
    log.info("persona.md regenerated (%d chars, %d memories)", len(persona), total)
    return True


def persona_due(store: MemoryStore, cfg: Settings) -> bool:
    last = int(store.get_kv(PERSONA_KV_KEY) or 0)
    return store.count_l1() - last >= cfg.pipeline_persona_every_n
