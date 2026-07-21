"""Skill/SOP generation — memory that does things.

Distills repeated task patterns from episodic + instruction memories into
reusable procedure documents (`skills/<slug>.md`): "how the user deploys",
"how reports must be formatted". Runs after each persona regeneration (when
pipeline_skills is on) or on demand via `zanii-memory skills`.

Skills close the loop at recall time: find_relevant_skill() matches the
current query against the library so the agent gets the *procedure*, not just
the facts — it stops re-learning what it already figured out.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from ..config import Settings
from ..llm import LLMClient
from ..store import MemoryStore
from .scenes import slugify

log = logging.getLogger("zanii_memory.pipeline")

SKILLS_SYSTEM_PROMPT = """You distill an AI agent's memories into reusable SKILL documents (standard operating procedures).

From the memories provided, identify recurring task patterns, workflows, or standing procedures — things the agent should be able to repeat without being re-told. Ignore one-off events and personal trivia.

Some episodic facts carry an outcome tag (success/failure). Build procedures from what WORKED; when a failure reveals a trap worth avoiding, record it under **Pitfalls** in the relevant skill.

**Output language**: match the dominant language of the memories.

Output format — zero or more skill sections, nothing else:

## SKILL: <short imperative skill name>
**When to use**: <trigger condition>
**Procedure**:
1. <step>
2. <step>
**Constraints**: <rules the user has imposed, if any>
**Pitfalls**: <known failure modes from tagged failures, if any>

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


def _memory_line(row) -> str:
    """`- [type|outcome|scene] content` — outcome only when extraction tagged one."""
    outcome = ""
    try:
        meta = row.get("metadata") or "{}"
        outcome = (json.loads(meta) if isinstance(meta, str) else meta).get("outcome", "")
    except (json.JSONDecodeError, AttributeError):
        pass
    tag = f"|{outcome}" if outcome in ("success", "failure") else ""
    return f"- [{row['type']}{tag}|{row['scene_name'] or 'no-scene'}] {row['content']}"


STOPWORDS = frozenset(
    "the a an and or to of in on for with how what when where why i my your user this that".split()
)


def find_relevant_skill(skills_dir: Path, query: str, max_chars: int = 1500) -> str | None:
    """Match the query against the skill library (procedural recall).

    Keyword-overlap scoring, title/'When to use' hits weighted 3x; returns the
    best doc only on a strong match (score >= 3) so unrelated queries inject
    nothing. ponytail: lexical scoring — embed-and-cache per skill doc if the
    library ever grows past dozens of files.
    """
    if not skills_dir.exists():
        return None
    tokens = {t for t in re.findall(r"[a-z0-9]+", query.lower()) if len(t) > 2 and t not in STOPWORDS}
    if not tokens:
        return None
    best_text, best_score = None, 0
    for path in sorted(skills_dir.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        lower = text.lower()
        lines = lower.splitlines()
        head = (lines[0] if lines else "") + " " + next((l for l in lines if "when to use" in l), "")
        score = sum(1 for t in tokens if t in lower) + 2 * sum(1 for t in tokens if t in head)
        if score > best_score:
            best_text, best_score = text, score
    if best_text is None or best_score < 3:
        return None
    return best_text[:max_chars]


async def run_skills(store: MemoryStore, llm: LLMClient, cfg: Settings) -> int:
    """Generate/refresh skill docs. Returns the number of skill files written."""
    episodic = store.get_l1_filtered(type="episodic", limit=150)
    instructions = store.get_l1_filtered(type="instruction", limit=50)
    if len(episodic) + len(instructions) < 2:
        return 0

    lines = [_memory_line(r) for r in instructions + episodic]
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
