"""Automatic context offload — no explicit offload() calls required.

Wrap it around your agent loop's message list; any oversized message body is
transparently replaced with a compact stub (full text retrievable by node_id):

    auto = AutoOffloader(memory, "task-1")
    messages = await auto.filter_messages(messages)   # before each LLM call
    text = await auto.guard(tool_output, label="grep results")  # or per-output
"""
from __future__ import annotations

from typing import Any

from .core import MemoryCore

DEFAULT_THRESHOLD_CHARS = 4000
# Roles whose verbose payloads are safe to stub out. User/system messages are
# never touched — they carry intent, not bulk.
DEFAULT_OFFLOAD_ROLES = ("tool", "function")


class AutoOffloader:
    def __init__(
        self,
        core: MemoryCore,
        session_key: str,
        threshold_chars: int = DEFAULT_THRESHOLD_CHARS,
        roles: tuple[str, ...] = DEFAULT_OFFLOAD_ROLES,
    ):
        self.core = core
        self.session_key = session_key
        self.threshold_chars = threshold_chars
        self.roles = set(roles)

    async def guard(self, content: str, label: str = "") -> str:
        """Return the content unchanged if small, else offload and return the stub."""
        if len(content) <= self.threshold_chars:
            return content
        result = await self.core.offload(self.session_key, content, label)
        return result["stub"] + f" ({result['chars']} chars offloaded; retrieve by node_id)"

    async def filter_messages(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Replace oversized offloadable messages with stubs; returns a new list.
        Already-stubbed messages are left alone (idempotent)."""
        out = []
        for msg in messages:
            content = msg.get("content")
            if (
                isinstance(content, str)
                and msg.get("role") in self.roles
                and len(content) > self.threshold_chars
                and not content.startswith("[offloaded:")
            ):
                label = str(msg.get("name", "") or msg.get("tool_call_id", "") or "tool output")
                out.append({**msg, "content": await self.guard(content, label)})
            else:
                out.append(msg)
        return out
