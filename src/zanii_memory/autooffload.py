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
        stale_after_messages: int = 0,
    ):
        """stale_after_messages: when > 0, tool outputs more than N messages
        behind the end of the list are offloaded even when small (> 200 chars) —
        stale results rarely earn their context cost. 0 disables (default)."""
        self.core = core
        self.session_key = session_key
        self.threshold_chars = threshold_chars
        self.roles = set(roles)
        self.stale_after_messages = stale_after_messages

    async def guard(self, content: str, label: str = "", force: bool = False) -> str:
        """Return the content unchanged if small (unless forced), else offload
        and return the stub."""
        if not force and len(content) <= self.threshold_chars:
            return content
        result = await self.core.offload(self.session_key, content, label)
        return result["stub"] + f" ({result['chars']} chars offloaded; retrieve by node_id)"

    async def filter_messages(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Replace oversized (and optionally stale) offloadable messages with
        stubs; returns a new list. Already-stubbed messages are left alone
        (idempotent)."""
        out = []
        last = len(messages) - 1
        for idx, msg in enumerate(messages):
            content = msg.get("content")
            offloadable = (
                isinstance(content, str)
                and msg.get("role") in self.roles
                and not content.startswith("[offloaded:")
            )
            oversized = offloadable and len(content) > self.threshold_chars
            stale = (
                offloadable
                and self.stale_after_messages > 0
                and (last - idx) > self.stale_after_messages
                and len(content) > 200
            )
            if oversized or stale:
                label = str(msg.get("name", "") or msg.get("tool_call_id", "") or "tool output")
                if stale and not oversized:
                    label += " (stale)"
                out.append({**msg, "content": await self.guard(content, label, force=stale)})
            else:
                out.append(msg)
        return out
