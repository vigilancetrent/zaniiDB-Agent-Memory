"""MCP server — exposes ZaniiDB Agent Memory to any MCP-capable agent
(Claude Code, IDE agents, etc.) over stdio.

Tools:
- memory_search        hybrid search over L1 memories
- conversation_search  BM25 search over raw captured conversations
- save_memory          store a fact/instruction directly (no LLM pipeline)
- get_persona          the user's persona.md profile

Register in Claude Code:
    claude mcp add zanii-memory -- zanii-memory mcp
"""
from __future__ import annotations

import logging

from mcp.server.fastmcp import FastMCP

from .config import Settings
from .core import MemoryCore

log = logging.getLogger("zanii_memory.mcp")

INSTRUCTIONS = (
    "Long-term memory for this user. Call memory_search before answering questions that may "
    "depend on the user's preferences, history, or standing instructions; call get_persona at "
    "the start of a session; call save_memory when the user states a durable fact or rule."
)


def format_memory_hits(hits: list[dict]) -> str:
    if not hits:
        return "No memories found."
    return "\n".join(f"- [{h['type']}|p{h['priority']}] {h['content']}" for h in hits)


def format_conversation_hits(hits: list[dict]) -> str:
    if not hits:
        return "No conversations found."
    return "\n".join(f"- [{h['session_key']}] [{h['role']}] {h['content'][:300]}" for h in hits)


def create_mcp_server(config: Settings | None = None) -> FastMCP:
    cfg = config or Settings()
    state: dict[str, MemoryCore | None] = {"core": None}

    async def get_core() -> MemoryCore:
        # ponytail: lazy init + no explicit shutdown — SQLite WAL is crash-safe
        # and the process owns the core for its whole lifetime.
        if state["core"] is None:
            core = MemoryCore(cfg)
            await core.initialize()
            state["core"] = core
        return state["core"]

    mcp = FastMCP("zanii-memory", instructions=INSTRUCTIONS)

    @mcp.tool()
    async def memory_search(
        query: str,
        limit: int = 10,
        type: str | None = None,
        since: str | None = None,
        until: str | None = None,
    ) -> str:
        """Search the user's long-term memories (stable preferences, past events, standing
        instructions). Optional type filter: persona | episodic | instruction.
        since/until: ISO-8601 dates to restrict when the memory was created
        (e.g. since="2026-07-01" for "what did the user decide recently?")."""
        core = await get_core()

        def to_ms(value: str | None) -> int | None:
            if not value:
                return None
            from datetime import datetime, timezone

            dt = datetime.fromisoformat(value)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return int(dt.timestamp() * 1000)

        return format_memory_hits(
            await core.search_memories(query, limit=limit, type=type, since=to_ms(since), until=to_ms(until))
        )

    @mcp.tool()
    async def conversation_search(query: str, limit: int = 10, session_key: str | None = None) -> str:
        """Keyword-search raw captured conversation history, optionally scoped to one session."""
        core = await get_core()
        return format_conversation_hits(
            await core.search_conversations(query, limit=limit, session_key=session_key)
        )

    @mcp.tool()
    async def save_memory(content: str, type: str = "persona", priority: int = 80, scope: str = "user") -> str:
        """Store one durable memory about the user. type: persona (trait/preference),
        episodic (event/decision), or instruction (standing rule for the AI).
        scope: "user" (personal) or "team" (shared org knowledge injected for all sessions)."""
        core = await get_core()
        inserted = await core.seed([{"content": content, "type": type, "priority": priority, "scope": scope}])
        return "Memory saved." if inserted else "Skipped: duplicate or empty content."

    @mcp.tool()
    async def get_persona() -> str:
        """The user's narrative persona profile distilled from long-term memory."""
        await get_core()
        if cfg.persona_path.exists():
            text = cfg.persona_path.read_text(encoding="utf-8").strip()
            if text:
                return text
        return "No persona generated yet."

    return mcp


def run() -> None:
    create_mcp_server().run()  # stdio transport
