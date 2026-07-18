"""Skill/SOP generation — memory that does things.

Distills repeated task patterns from episodic + instruction memories into
reusable procedure documents (`skills/<slug>.md`): "how the user deploys",
"how reports must be formatted". Runs after each persona regeneration (when
pipeline_skills is on) or on demand via `zanii-memory skills`.
"""
from __future__ import annotations

import logging
import re

from ..config import Settings
from ..llm import LLMClient
from ..store import MemoryStore
from .scenes import slugify

log = logging.getLogger("zanii_memory.pipeline")

SKILLS_SYSTEM_PROMPT = """You distill an AI agent's memories into reusable SKILL documents (standard operating procedures).

From the memories provided, identify recurring task patterns, workflows, or standing procedures — things the agent should be able to repeat without being re-told. Ignore one-off events and personal trivia.

**Output language**: match the dominant language of the memories.

Output format — zero or more skill sections, nothing else:

## SKILL: <short imperative skill name>
**When to use**: <trigger condition>
**Procedure**:
1. <step>
2. <step>
**Constraints**: <rules the user has imposed, if any>

Rules:
- Only create a skill when at least two memories support the pattern, or one explicit standing instruction defines it.
- Be concrete: name the actual tools, formats, and preferences from the memories.
- If no reliable skills can be distilled, output exactly: NONE"""

_SKILL_SPLIT_RE = re.compile(r"^## SKILL:\s*(.+)$", re.MULTILINE)


def parse_skills(text: str) -> list[tuple[str, str]]:
    """Split LLM output into (name, markdown) sections."""
    text = text.strip()
    if not text or text.upper() == "NONE":
        return []
    matches = list(_SKILL_SPLIT_RE.finditer(text))
    skills = []
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        name = m.group(1).strip()
        body = text[m.start():end].strip()
        if name and body:
            skills.append((name, body))
    return skills


async def run_skills(store: MemoryStore, llm: LLMClient, cfg: Settings) -> int:
    """Generate/refresh skill docs. Returns the number of skill files written."""
    episodic = store.get_l1_filtered(type="episodic", limit=150)
    instructions = store.get_l1_filtered(type="instruction", limit=50)
    if len(episodic) + len(instructions) < 2:
        return 0

    lines = [f"- [{r['type']}|{r['scene_name'] or 'no-scene'}] {r['content']}" for r in instructions + episodic]
    prompt = "## Memories (evidence for skills)\n\n" + "\n".join(lines) + "\n\nDistill the skills now."
    text = await llm.complete(prompt, system=SKILLS_SYSTEM_PROMPT, timeout=180, max_tokens=3000)

    skills = parse_skills(text)
    if not skills:
        return 0
    cfg.skills_dir.mkdir(parents=True, exist_ok=True)
    for name, body in skills:
        (cfg.skills_dir / f"{slugify(name)}.md").write_text(body + "\n", encoding="utf-8")
    log.info("Wrote %d skill documents", len(skills))
    return len(skills)
