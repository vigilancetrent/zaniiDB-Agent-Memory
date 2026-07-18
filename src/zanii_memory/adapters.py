"""Framework-agnostic agent hooks — wire memory into any agent loop in 3 lines.

    hooks = AgentMemoryHooks(memory, session_key="user-42")
    injection = await hooks.before_turn(user_text)   # -> prepend/system contexts
    ...run your agent with the injected context...
    await hooks.after_turn(user_text, assistant_text)

Recipes:

**OpenAI-style message list** (works for OpenAI Agents SDK, LiteLLM, raw APIs):
    messages = hooks.inject(messages, injection)

**LangGraph**: call `before_turn` in the node that builds the prompt, and
`after_turn` in a terminal node / `on_chat_model_end` callback.

**CrewAI / Pydantic-AI**: call `before_turn` when building the system prompt
for a task, `after_turn` from the task-completion callback.

`end()` flushes pending turns through extraction (call on session close).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .core import MemoryCore


@dataclass
class PromptInjection:
    prepend: str  # relevant memories -> prepend to the user message
    system: str  # persona / team knowledge -> append to the system prompt


class AgentMemoryHooks:
    def __init__(self, core: MemoryCore, session_key: str):
        self.core = core
        self.session_key = session_key

    async def before_turn(self, user_text: str) -> PromptInjection:
        result = await self.core.recall(user_text, self.session_key)
        return PromptInjection(prepend=result.prepend_context, system=result.append_system_context)

    async def after_turn(self, user_text: str, assistant_text: str) -> None:
        await self.core.capture(
            self.session_key,
            [{"role": "user", "content": user_text}, {"role": "assistant", "content": assistant_text}],
        )

    async def end(self) -> None:
        await self.core.end_session(self.session_key)

    @staticmethod
    def inject(messages: list[dict[str, Any]], injection: PromptInjection) -> list[dict[str, Any]]:
        """Apply an injection to an OpenAI-style message list (returns a new list)."""
        out = [dict(m) for m in messages]
        if injection.system:
            for msg in out:
                if msg.get("role") == "system":
                    msg["content"] = f"{msg.get('content', '')}\n\n{injection.system}".strip()
                    break
            else:
                out.insert(0, {"role": "system", "content": injection.system})
        if injection.prepend:
            for msg in reversed(out):
                if msg.get("role") == "user":
                    msg["content"] = f"{injection.prepend}\n\n{msg.get('content', '')}"
                    break
        return out
