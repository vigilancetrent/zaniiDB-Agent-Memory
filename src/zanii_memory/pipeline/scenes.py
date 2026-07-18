"""L2 scene blocks: human-readable markdown files, one per scene.

White-box by design — open the files and read what the agent remembers.
Facts append as a ledger; once a scene grows past scene_condense_chars, an LLM
synthesizes it into a resolved current-state narrative (newest facts win,
update history preserved) — so scenes stay small, current, and readable.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from pathlib import Path

from ..llm import LLMClient
from ..types import MemoryRecord

log = logging.getLogger("zanii_memory.pipeline")

CONDENSE_SYSTEM_PROMPT = """You maintain one scene file of an AI agent's memory about a user.
Rewrite the scene into a synthesized, current-state document:

- Keep the first line ("# Scene: ...") exactly as it is.
- "## Current state": the resolved facts as of now. When facts conflict, the newest wins; note meaningful changes inline as "(updated from: <old>)".
- "## History": brief dated notes of events and past states worth keeping.
- Preserve the [type|pXX|id] tags of every fact you keep (traceability). Drop trivia and exact duplicates.
- Match the language of the scene content. Maximum ~1500 characters. Output only the markdown document."""


async def maybe_condense_scene(path: Path, llm: LLMClient, max_chars: int) -> bool:
    """Synthesize an oversized scene ledger into a current-state narrative."""
    if max_chars <= 0 or not llm.enabled or not path.exists():
        return False
    text = path.read_text(encoding="utf-8")
    if len(text) <= max_chars:
        return False
    out = await llm.complete(text, system=CONDENSE_SYSTEM_PROMPT, timeout=90, max_tokens=1200)
    out = re.sub(r"^```[a-z]*\s*|\s*```$", "", out.strip(), flags=re.MULTILINE).strip()
    if len(out) < 60 or not out.startswith("# Scene:"):
        log.warning("Scene condensation for %s returned invalid output; keeping ledger", path.name)
        return False
    path.write_text(out + "\n", encoding="utf-8")
    log.info("Condensed scene %s: %d -> %d chars", path.name, len(text), len(out))
    return True


def slugify(name: str) -> str:
    slug = re.sub(r"[^\w\-]+", "-", name.strip().lower()).strip("-")
    return slug[:80] or "scene"


def append_scene_facts(scenes_dir: Path, scene_name: str, memories: list[MemoryRecord]) -> Path:
    scenes_dir.mkdir(parents=True, exist_ok=True)
    path = scenes_dir / f"{slugify(scene_name)}.md"
    if not path.exists():
        path.write_text(f"# Scene: {scene_name}\n", encoding="utf-8")
    stamp = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [f"\n## Update {stamp}\n"]
    for mem in memories:
        lines.append(f"- [{mem.type}|p{mem.priority}|{mem.id}] {mem.content}\n")
    with path.open("a", encoding="utf-8") as f:
        f.writelines(lines)
    return path


def read_all_scenes(scenes_dir: Path, max_chars: int = 12000) -> str:
    """Concatenate scene files, most recently modified first, within a char budget."""
    if not scenes_dir.exists():
        return ""
    files = sorted(scenes_dir.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
    parts: list[str] = []
    total = 0
    for path in files:
        text = path.read_text(encoding="utf-8")
        if total + len(text) > max_chars:
            text = text[: max(0, max_chars - total)]
        parts.append(text)
        total += len(text)
        if total >= max_chars:
            break
    return "\n\n---\n\n".join(parts)
