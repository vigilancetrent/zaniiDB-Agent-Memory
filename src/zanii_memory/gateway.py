"""FastAPI gateway — the HTTP surface of ZaniiDB Agent Memory:

    GET  /health                 (always open)
    POST /recall                 {query, session_key}
    POST /capture                {session_key, messages[], session_id?}
    POST /search/memories        {query, limit?, type?}
    POST /search/conversations   {query, limit?, session_key?}
    POST /session/end            {session_key}
    POST /seed                   {memories[]}

Bearer auth is enforced on everything except /health when
ZANII_GATEWAY_API_KEY is set. CORS headers are emitted only for origins in
ZANII_CORS_ORIGINS (empty default = none).
"""
from __future__ import annotations

import hmac
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from . import __version__
from .config import Settings
from .core import MemoryCore
from .dashboard import DASHBOARD_HTML


def _parse_iso_ms(value: str | None, field: str) -> int | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"{field} must be ISO-8601 (e.g. 2026-07-01 or 2026-07-01T12:00:00)")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


class RecallRequest(BaseModel):
    query: str = Field(min_length=1)
    session_key: str = Field(min_length=1)


class CaptureRequest(BaseModel):
    session_key: str = Field(min_length=1)
    messages: list[dict[str, Any]]
    session_id: str = ""


class MemorySearchRequest(BaseModel):
    query: str = Field(min_length=1)
    limit: int = Field(default=10, ge=1, le=100)
    type: str | None = None
    since: str | None = None  # ISO-8601: only memories created at/after this time
    until: str | None = None  # ISO-8601: only memories created at/before this time


class ConversationSearchRequest(BaseModel):
    query: str = Field(min_length=1)
    limit: int = Field(default=10, ge=1, le=100)
    session_key: str | None = None


class SessionEndRequest(BaseModel):
    session_key: str = Field(min_length=1)


class SeedRequest(BaseModel):
    memories: list[dict[str, Any]]


class OffloadRequest(BaseModel):
    session_key: str = Field(min_length=1)
    content: str = Field(min_length=1)
    label: str = ""


def create_app(config: Settings | None = None) -> FastAPI:
    cfg = config or Settings()
    core = MemoryCore(cfg)
    start_time = time.time()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        await core.initialize()
        yield
        await core.close()

    app = FastAPI(title="ZaniiDB Agent Memory", version=__version__, lifespan=lifespan)

    if cfg.cors_origin_list:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=cfg.cors_origin_list,
            allow_methods=["GET", "POST", "OPTIONS"],
            allow_headers=["Content-Type", "Authorization"],
        )

    async def require_auth(request: Request) -> None:
        if not cfg.gateway_api_key:
            return
        header = request.headers.get("authorization", "")
        token = header[len("Bearer "):].strip() if header.startswith("Bearer ") else ""
        # ?token= fallback lets the browser dashboard authenticate without headers.
        token = token or request.query_params.get("token", "")
        if not token or not hmac.compare_digest(token, cfg.gateway_api_key):
            raise HTTPException(status_code=401, detail="Unauthorized: missing or invalid token")

    @app.get("/health")
    async def health() -> dict[str, Any]:
        ready = core.store is not None
        return {
            "status": "ok" if ready else "degraded",
            "version": __version__,
            "uptime": int(time.time() - start_time),
            **(core.stats() if ready else {}),
        }

    @app.post("/recall", dependencies=[Depends(require_auth)])
    async def recall(body: RecallRequest) -> dict[str, Any]:
        result = await core.recall(body.query, body.session_key)
        return {
            "prepend_context": result.prepend_context,
            "context": result.append_system_context,
            "strategy": result.strategy,
            "memory_count": len(result.memories),
            "memories": result.memories,
        }

    @app.post("/capture", dependencies=[Depends(require_auth)])
    async def capture(body: CaptureRequest) -> dict[str, Any]:
        return await core.capture(body.session_key, body.messages, body.session_id)

    @app.post("/search/memories", dependencies=[Depends(require_auth)])
    async def search_memories(body: MemorySearchRequest) -> dict[str, Any]:
        hits = await core.search_memories(
            body.query,
            limit=body.limit,
            type=body.type,
            since=_parse_iso_ms(body.since, "since"),
            until=_parse_iso_ms(body.until, "until"),
        )
        return {
            "results": [
                {
                    "id": h["id"],
                    "content": h["content"],
                    "type": h["type"],
                    "priority": h["priority"],
                    "scope": h.get("scope", "user"),
                    "scene_name": h["scene_name"],
                    "score": h["score"],
                }
                for h in hits
            ]
        }

    @app.post("/search/conversations", dependencies=[Depends(require_auth)])
    async def search_conversations(body: ConversationSearchRequest) -> dict[str, Any]:
        hits = await core.search_conversations(body.query, limit=body.limit, session_key=body.session_key)
        return {
            "results": [
                {
                    "session_key": h["session_key"],
                    "role": h["role"],
                    "content": h["content"],
                    "timestamp": h["timestamp"],
                    "score": h["score"],
                }
                for h in hits
            ]
        }

    @app.post("/session/end", dependencies=[Depends(require_auth)])
    async def session_end(body: SessionEndRequest) -> dict[str, Any]:
        await core.end_session(body.session_key)
        return {"status": "flushed"}

    @app.post("/seed", dependencies=[Depends(require_auth)])
    async def seed(body: SeedRequest) -> dict[str, Any]:
        inserted = await core.seed(body.memories)
        return {"inserted": inserted}

    @app.post("/offload", dependencies=[Depends(require_auth)])
    async def offload(body: OffloadRequest) -> dict[str, Any]:
        return await core.offload(body.session_key, body.content, body.label)

    @app.get("/offload/{node_id}", dependencies=[Depends(require_auth)])
    async def retrieve_ref(node_id: str) -> dict[str, Any]:
        content = await core.retrieve_ref(node_id)
        if content is None:
            raise HTTPException(status_code=404, detail=f"Unknown node_id: {node_id}")
        return {"node_id": node_id, "content": content}

    @app.get("/canvas/{session_key}", dependencies=[Depends(require_auth)])
    async def canvas(session_key: str) -> dict[str, Any]:
        return {"session_key": session_key, "mermaid": await core.get_canvas(session_key)}

    @app.post("/export", dependencies=[Depends(require_auth)])
    async def export_memory() -> dict[str, Any]:
        return await core.export_memory()

    @app.post("/import", dependencies=[Depends(require_auth)])
    async def import_memory(body: dict[str, Any]) -> dict[str, Any]:
        try:
            return await core.import_memory(body)
        except ValueError as err:
            raise HTTPException(status_code=400, detail=str(err))

    @app.post("/consolidate", dependencies=[Depends(require_auth)])
    async def consolidate() -> dict[str, Any]:
        return await core.consolidate()

    @app.get("/audit", dependencies=[Depends(require_auth)])
    async def audit(limit: int = 100) -> dict[str, Any]:
        return {"entries": core.audit_log(min(max(limit, 1), 1000))}

    @app.get("/dashboard", dependencies=[Depends(require_auth)], response_class=HTMLResponse)
    async def dashboard() -> str:
        return DASHBOARD_HTML

    @app.get("/api/overview", dependencies=[Depends(require_auth)])
    async def overview() -> dict[str, Any]:
        assert core.store is not None
        recent = core.store.get_l1_filtered(limit=25)
        persona = (
            core.cfg.persona_path.read_text(encoding="utf-8") if core.cfg.persona_path.exists() else ""
        )
        scenes = sorted(p.name for p in core.cfg.scenes_dir.glob("*.md")) if core.cfg.scenes_dir.exists() else []
        skills = sorted(p.name for p in core.cfg.skills_dir.glob("*.md")) if core.cfg.skills_dir.exists() else []
        superseded = sum(1 for r in core.store.get_all_l1() if r.get("superseded_by"))
        ledger = getattr(core, "ledger", None)
        ledger_entries = 0
        if ledger is not None and ledger.enabled and ledger.entries_path.exists():
            ledger_entries = sum(1 for line in ledger.entries_path.read_text(encoding="utf-8").splitlines() if line.strip())
        return {
            "version": __version__,
            **core.stats(),
            "superseded": superseded,
            "ledger": {"enabled": bool(ledger is not None and ledger.enabled), "entries": ledger_entries},
            "recent_memories": [
                {"content": r["content"], "type": r["type"], "scope": r.get("scope", "user")} for r in recent
            ],
            "persona": persona,
            "scenes": scenes,
            "skills": skills,
            "audit": core.audit_log(25) if cfg.audit_enabled else [],
        }

    return app
