"""Short-term context offload with a symbolic task canvas.

The token killers in long agent tasks are verbose intermediate outputs (tool
logs, search results, stack traces). Instead of keeping them in context:

1. `offload()` writes the full text to `refs/<node_id>.md` and returns a
   compact stub the agent keeps in context.
2. Each offload appends a node to a per-session **Mermaid task canvas**
   (`canvas/<session>.mmd`) — a symbol graph of the task's steps that is
   precise enough for LLMs and readable by humans.
3. `retrieve(node_id)` drills back down to the full raw text on demand.

Everything is plain files — white-box, grep-able, zero DB coupling.

ponytail: the canvas is a linear step chain in v1; branch/merge edges can be
added when callers supply an explicit parent node.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import Settings
from .pipeline.scenes import slugify

NODE_ID_RE = re.compile(r"^N[0-9a-f]{8}$")
_NODE_IN_CANVAS_RE = re.compile(r"\bN[0-9a-f]{8}\b")
STUB_PREVIEW_CHARS = 120
LABEL_MAX_CHARS = 60


def _clean_label(text: str) -> str:
    label = re.sub(r"\s+", " ", text).strip().replace('"', "'")
    return label[:LABEL_MAX_CHARS] or "step"


class Offloader:
    def __init__(self, cfg: Settings):
        self.refs_dir = cfg.data_dir / "refs"
        self.canvas_dir = cfg.data_dir / "canvas"

    def offload(self, session_key: str, content: str, label: str = "") -> dict[str, Any]:
        """Store verbose content externally; return a compact stub + node_id."""
        self.refs_dir.mkdir(parents=True, exist_ok=True)
        node_id = "N" + uuid.uuid4().hex[:8]
        stamp = datetime.now(tz=timezone.utc).isoformat(timespec="seconds")
        header = f"---\nnode_id: {node_id}\nsession_key: {session_key}\nlabel: {label}\ncreated: {stamp}\n---\n\n"
        (self.refs_dir / f"{node_id}.md").write_text(header + content, encoding="utf-8")

        preview = re.sub(r"\s+", " ", content).strip()[:STUB_PREVIEW_CHARS]
        stub = f"[offloaded:{node_id}] {label or preview}"
        self._append_canvas(session_key, node_id, _clean_label(label or preview))
        return {"node_id": node_id, "stub": stub, "chars": len(content)}

    def retrieve(self, node_id: str) -> str | None:
        """Full raw text for a node_id, or None. node_id format is validated —
        no path traversal."""
        if not NODE_ID_RE.match(node_id):
            return None
        path = self.refs_dir / f"{node_id}.md"
        return path.read_text(encoding="utf-8") if path.exists() else None

    def canvas(self, session_key: str) -> str:
        """The session's Mermaid task canvas ('' when none exists)."""
        path = self._canvas_path(session_key)
        return path.read_text(encoding="utf-8") if path.exists() else ""

    def _canvas_path(self, session_key: str) -> Path:
        return self.canvas_dir / f"{slugify(session_key)}.mmd"

    def _append_canvas(self, session_key: str, node_id: str, label: str) -> None:
        self.canvas_dir.mkdir(parents=True, exist_ok=True)
        path = self._canvas_path(session_key)
        text = path.read_text(encoding="utf-8") if path.exists() else "graph TD\n"
        previous_nodes = _NODE_IN_CANVAS_RE.findall(text)
        if previous_nodes:
            line = f'  {previous_nodes[-1]} --> {node_id}["{label}"]\n'
        else:
            line = f'  {node_id}["{label}"]\n'
        path.write_text(text + line, encoding="utf-8")
