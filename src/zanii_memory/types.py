"""Core data types shared across the SDK, pipeline, and gateway."""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

MEMORY_TYPES = ("persona", "episodic", "instruction")
MEMORY_SCOPES = ("user", "team")


def now_ms() -> int:
    return int(time.time() * 1000)


def new_id() -> str:
    return uuid.uuid4().hex


@dataclass
class MemoryRecord:
    """One L1 atomic memory."""

    content: str
    type: str = "persona"
    priority: int = 60
    scope: str = "user"  # "user" (personal) or "team" (shared org knowledge)
    scene_name: str = ""
    session_key: str = ""
    session_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=new_id)
    created_at: int = field(default_factory=now_ms)
    updated_at: int = field(default_factory=now_ms)


@dataclass
class RecallResult:
    """Assembled recall context for injection into an agent's prompt."""

    prepend_context: str = ""
    append_system_context: str = ""
    memories: list[dict[str, Any]] = field(default_factory=list)
    strategy: str = "keyword"
