"""PostgreSQL backend: tsvector full-text search + pgvector cosine KNN,
fused with the same RRF as the SQLite backend.

Requires: pip install "zaniidb-agent-memory[postgres]"
Select it with ZANII_DATABASE_URL=postgresql://user:pass@host:5432/dbname

If the `vector` extension cannot be created (managed DB without pgvector),
the store degrades to keyword-only search — same contract as SQLite.

ponytail: single connection + RLock, same concurrency model as the SQLite
backend; switch to a psycopg connection pool if gateway throughput demands it.
"""
from __future__ import annotations

import json
import logging
import re
import threading
from typing import Any

from ..types import MemoryRecord, now_ms
from .sqlite import rrf_fuse

log = logging.getLogger("zanii_memory.store")

try:
    import psycopg
    from psycopg.rows import dict_row

    _HAS_PSYCOPG = True
except ImportError:  # pragma: no cover
    _HAS_PSYCOPG = False

_L0_COLS = 'id, session_key, session_id, role, content, channel, "timestamp", recorded_at'
_L1_COLS = (
    "id, type, content, priority, scope, scene_name, session_key, session_id,"
    " metadata, created_at, updated_at, superseded_by, quarantine"
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS l0_conversations (
    id BIGSERIAL PRIMARY KEY,
    session_key TEXT NOT NULL,
    session_id TEXT NOT NULL DEFAULT '',
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    channel TEXT NOT NULL DEFAULT 'user',
    "timestamp" BIGINT NOT NULL,
    recorded_at BIGINT NOT NULL,
    fts tsvector GENERATED ALWAYS AS (to_tsvector('{ts_config}', content)) STORED
);
CREATE INDEX IF NOT EXISTS idx_l0_session ON l0_conversations(session_key, id);
CREATE INDEX IF NOT EXISTS idx_l0_fts ON l0_conversations USING GIN(fts);

CREATE TABLE IF NOT EXISTS l1_records (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    content TEXT NOT NULL,
    priority INTEGER NOT NULL DEFAULT 60,
    scope TEXT NOT NULL DEFAULT 'user',
    superseded_by TEXT NOT NULL DEFAULT '',
    quarantine TEXT NOT NULL DEFAULT '',
    scene_name TEXT NOT NULL DEFAULT '',
    session_key TEXT NOT NULL DEFAULT '',
    session_id TEXT NOT NULL DEFAULT '',
    metadata TEXT NOT NULL DEFAULT '{{}}',
    created_at BIGINT NOT NULL,
    updated_at BIGINT NOT NULL,
    fts tsvector GENERATED ALWAYS AS (to_tsvector('{ts_config}', content)) STORED
);
ALTER TABLE l1_records ADD COLUMN IF NOT EXISTS scope TEXT NOT NULL DEFAULT 'user';
ALTER TABLE l1_records ADD COLUMN IF NOT EXISTS superseded_by TEXT NOT NULL DEFAULT '';
ALTER TABLE l1_records ADD COLUMN IF NOT EXISTS quarantine TEXT NOT NULL DEFAULT '';
ALTER TABLE l0_conversations ADD COLUMN IF NOT EXISTS channel TEXT NOT NULL DEFAULT 'user';
CREATE INDEX IF NOT EXISTS idx_l1_type ON l1_records(type);
CREATE INDEX IF NOT EXISTS idx_l1_fts ON l1_records USING GIN(fts);

CREATE TABLE IF NOT EXISTS pipeline_state (
    session_key TEXT PRIMARY KEY,
    watermark BIGINT NOT NULL DEFAULT 0,
    pending INTEGER NOT NULL DEFAULT 0,
    threshold INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS kv_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_log (
    id BIGSERIAL PRIMARY KEY,
    op TEXT NOT NULL,
    detail TEXT NOT NULL,
    ts BIGINT NOT NULL
);
"""


def _tsquery(text: str) -> str:
    tokens = re.findall(r"\w+", text, re.UNICODE)
    return " | ".join(tokens[:32])


def _vec_literal(embedding: list[float]) -> str:
    return "[" + ",".join(f"{x:.8g}" for x in embedding) + "]"


class PostgresStore:
    def __init__(
        self,
        dsn: str,
        dimensions: int = 1536,
        want_vectors: bool = False,
        text_search_config: str = "simple",
    ):
        if not _HAS_PSYCOPG:
            raise RuntimeError(
                'PostgreSQL backend requires psycopg: pip install "zaniidb-agent-memory[postgres]"'
            )
        if not re.fullmatch(r"[a-z_][a-z0-9_]*", text_search_config):
            raise ValueError(f"Invalid text search config name: {text_search_config!r}")
        self.text_search_config = text_search_config
        self._lock = threading.RLock()
        self.db = psycopg.connect(dsn, autocommit=True, row_factory=dict_row)
        self.dimensions = dimensions
        self.vec_enabled = False
        if want_vectors:
            try:
                self.db.execute("CREATE EXTENSION IF NOT EXISTS vector")
                self.vec_enabled = True
            except psycopg.Error as err:
                log.warning("pgvector unavailable, falling back to keyword-only search: %s", err)
        self._create_schema()

    def _create_schema(self) -> None:
        with self._lock:
            self.db.execute(_SCHEMA.format(ts_config=self.text_search_config))
            if self.vec_enabled:
                self.db.execute(
                    f"ALTER TABLE l1_records ADD COLUMN IF NOT EXISTS embedding vector({self.dimensions})"
                )
                try:
                    self.db.execute(
                        "CREATE INDEX IF NOT EXISTS idx_l1_embedding ON l1_records"
                        " USING hnsw (embedding vector_cosine_ops)"
                    )
                except psycopg.Error as err:  # pgvector < 0.5: no HNSW; seq scan is fine at small scale
                    log.info("HNSW index unavailable (%s); vector search uses sequential scan", err)

    # ============================
    # L0 conversations
    # ============================

    def record_l0(
        self,
        session_key: str,
        role: str,
        content: str,
        timestamp: int | None = None,
        session_id: str = "",
        channel: str = "user",
    ) -> int:
        with self._lock:
            row = self.db.execute(
                'INSERT INTO l0_conversations (session_key, session_id, role, content, channel,'
                ' "timestamp", recorded_at)'
                " VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id",
                (session_key, session_id, role, content, channel, timestamp or now_ms(), now_ms()),
            ).fetchone()
            return int(row["id"])

    def get_l0_after(self, session_key: str, after_id: int, limit: int = 200) -> list[dict[str, Any]]:
        with self._lock:
            return self.db.execute(
                f"SELECT {_L0_COLS} FROM l0_conversations WHERE session_key = %s AND id > %s ORDER BY id LIMIT %s",
                (session_key, after_id, limit),
            ).fetchall()

    def get_l0_before(self, session_key: str, before_id: int, limit: int = 6) -> list[dict[str, Any]]:
        with self._lock:
            rows = self.db.execute(
                f"SELECT {_L0_COLS} FROM l0_conversations WHERE session_key = %s AND id <= %s"
                " ORDER BY id DESC LIMIT %s",
                (session_key, before_id, limit),
            ).fetchall()
        return list(reversed(rows))

    def search_l0(self, query: str, limit: int = 10, session_key: str | None = None) -> list[dict[str, Any]]:
        tsq = _tsquery(query)
        if not tsq:
            return []
        cfg = self.text_search_config
        sql = (
            f"SELECT {_L0_COLS}, ts_rank(fts, to_tsquery('{cfg}', %s)) AS score"
            f" FROM l0_conversations WHERE fts @@ to_tsquery('{cfg}', %s)"
        )
        params: list[Any] = [tsq, tsq]
        if session_key:
            sql += " AND session_key = %s"
            params.append(session_key)
        sql += " ORDER BY score DESC LIMIT %s"
        params.append(limit)
        with self._lock:
            return self.db.execute(sql, params).fetchall()

    def get_all_l0(self) -> list[dict[str, Any]]:
        with self._lock:
            return self.db.execute(f"SELECT {_L0_COLS} FROM l0_conversations ORDER BY id").fetchall()

    def l0_exists(self, session_key: str, role: str, content: str, timestamp: int) -> bool:
        with self._lock:
            row = self.db.execute(
                "SELECT 1 FROM l0_conversations WHERE session_key = %s AND role = %s"
                ' AND content = %s AND "timestamp" = %s LIMIT 1',
                (session_key, role, content, timestamp),
            ).fetchone()
        return row is not None

    # ============================
    # L1 memories
    # ============================

    def insert_l1(
        self, record: MemoryRecord, embedding: list[float] | None = None, quarantine: str = ""
    ) -> int:
        cols = _L1_COLS
        placeholders = "%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, '', %s"
        params: list[Any] = [
            record.id,
            record.type,
            record.content,
            record.priority,
            record.scope,
            record.scene_name,
            record.session_key,
            record.session_id,
            json.dumps(record.metadata, ensure_ascii=False),
            record.created_at,
            record.updated_at,
            quarantine[:300],
        ]
        if embedding is not None and self.vec_enabled:
            cols += ", embedding"
            placeholders += ", %s::vector"
            params.append(_vec_literal(embedding))
        with self._lock:
            self.db.execute(f"INSERT INTO l1_records ({cols}) VALUES ({placeholders})", params)
        return 0

    def l1_content_exists(self, content: str) -> bool:
        with self._lock:
            row = self.db.execute("SELECT 1 FROM l1_records WHERE content = %s LIMIT 1", (content,)).fetchone()
        return row is not None

    def count_l1(self) -> int:
        with self._lock:
            return int(
                self.db.execute(
                    "SELECT COUNT(*) AS n FROM l1_records WHERE superseded_by = '' AND quarantine = '' AND quarantine = ''"
                ).fetchone()["n"]
            )

    def mark_superseded(self, old_ids: list[str], new_id: str) -> int:
        if not old_ids:
            return 0
        with self._lock:
            cur = self.db.execute(
                "UPDATE l1_records SET superseded_by = %s, updated_at = %s"
                " WHERE id = ANY(%s) AND superseded_by = '' AND quarantine = ''",
                (new_id, now_ms(), old_ids),
            )
            return cur.rowcount

    def get_all_l1(self) -> list[dict[str, Any]]:
        with self._lock:
            return self.db.execute(f"SELECT {_L1_COLS} FROM l1_records ORDER BY created_at").fetchall()

    def keyword_search_l1(
        self,
        query: str,
        limit: int = 10,
        type: str | None = None,
        since: int | None = None,
        until: int | None = None,
    ) -> list[dict[str, Any]]:
        tsq = _tsquery(query)
        if not tsq:
            return []
        cfg = self.text_search_config
        sql = (
            f"SELECT {_L1_COLS}, ts_rank(fts, to_tsquery('{cfg}', %s)) AS score"
            f" FROM l1_records WHERE fts @@ to_tsquery('{cfg}', %s) AND superseded_by = '' AND quarantine = '' AND quarantine = ''"
        )
        params: list[Any] = [tsq, tsq]
        if type:
            sql += " AND type = %s"
            params.append(type)
        if since is not None:
            sql += " AND created_at >= %s"
            params.append(since)
        if until is not None:
            sql += " AND created_at <= %s"
            params.append(until)
        sql += " ORDER BY score DESC LIMIT %s"
        params.append(limit)
        with self._lock:
            return self.db.execute(sql, params).fetchall()

    def vector_search_l1(self, embedding: list[float], limit: int = 10) -> list[dict[str, Any]]:
        if not self.vec_enabled:
            return []
        vec = _vec_literal(embedding)
        with self._lock:
            rows = self.db.execute(
                f"SELECT {_L1_COLS}, (embedding <=> %s::vector) AS distance FROM l1_records"
                " WHERE embedding IS NOT NULL AND superseded_by = '' AND quarantine = '' AND quarantine = ''"
                " ORDER BY embedding <=> %s::vector LIMIT %s",
                (vec, vec, limit),
            ).fetchall()
        return [{**r, "score": 1.0 - r["distance"]} for r in rows]

    def hybrid_search_l1(
        self,
        query: str,
        embedding: list[float] | None = None,
        limit: int = 5,
        type: str | None = None,
        since: int | None = None,
        until: int | None = None,
    ) -> list[dict[str, Any]]:
        keyword_hits = self.keyword_search_l1(query, limit=limit * 3, type=type, since=since, until=until)
        vector_hits = self.vector_search_l1(embedding, limit=limit * 3) if embedding else []
        vector_hits = [
            h
            for h in vector_hits
            if (not type or h["type"] == type)
            and (since is None or h["created_at"] >= since)
            and (until is None or h["created_at"] <= until)
        ]
        if not vector_hits:
            return keyword_hits[:limit]
        if not keyword_hits:
            return vector_hits[:limit]
        fused = rrf_fuse([[h["id"] for h in keyword_hits], [h["id"] for h in vector_hits]])
        by_id = {h["id"]: h for h in keyword_hits + vector_hits}
        return [{**by_id[rid], "score": score} for rid, score in fused[:limit]]

    def nearest_l1_distance(self, embedding: list[float]) -> float | None:
        hits = self.vector_search_l1(embedding, limit=1)
        return hits[0]["distance"] if hits else None

    def get_l1_filtered(
        self,
        type: str | None = None,
        scope: str | None = None,
        created_before: int | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        sql = f"SELECT {_L1_COLS} FROM l1_records WHERE superseded_by = '' AND quarantine = ''"
        params: list[Any] = []
        if type:
            sql += " AND type = %s"
            params.append(type)
        if scope:
            sql += " AND scope = %s"
            params.append(scope)
        if created_before is not None:
            sql += " AND created_at < %s"
            params.append(created_before)
        sql += " ORDER BY priority DESC, created_at DESC LIMIT %s"
        params.append(limit)
        with self._lock:
            return self.db.execute(sql, params).fetchall()

    def delete_l1(self, ids: list[str]) -> int:
        if not ids:
            return 0
        with self._lock:
            cur = self.db.execute("DELETE FROM l1_records WHERE id = ANY(%s)", (ids,))
            return cur.rowcount

    def quarantine_l1(self, ids: list[str], reason: str) -> int:
        if not ids:
            return 0
        with self._lock:
            cur = self.db.execute(
                "UPDATE l1_records SET quarantine = %s, updated_at = %s WHERE id = ANY(%s)",
                (reason[:300], now_ms(), ids),
            )
            return cur.rowcount

    def release_l1(self, ids: list[str]) -> int:
        if not ids:
            return 0
        with self._lock:
            cur = self.db.execute(
                "UPDATE l1_records SET quarantine = '', updated_at = %s"
                " WHERE id = ANY(%s) AND quarantine != ''",
                (now_ms(), ids),
            )
            return cur.rowcount

    def get_quarantined(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock:
            return self.db.execute(
                f"SELECT {_L1_COLS} FROM l1_records WHERE quarantine != ''"
                " ORDER BY created_at DESC LIMIT %s",
                (limit,),
            ).fetchall()

    def find_near_duplicate_pairs(self, max_distance: float) -> list[tuple[str, str]]:
        """(keep_id, drop_id) near-duplicate pairs by cosine distance.
        Per-row nearest-neighbor via LATERAL, so the HNSW index serves each
        probe — n index lookups instead of an n^2 cross join."""
        if not self.vec_enabled:
            return []
        with self._lock:
            rows = self.db.execute(
                "SELECT a.id AS a_id, a.priority AS a_pri, a.created_at AS a_created,"
                " n.id AS b_id, n.priority AS b_pri, n.created_at AS b_created"
                " FROM l1_records a"
                " JOIN LATERAL ("
                "   SELECT b.id, b.priority, b.created_at,"
                "          (b.embedding <=> a.embedding) AS dist"
                "   FROM l1_records b"
                "   WHERE b.id <> a.id AND b.embedding IS NOT NULL AND b.superseded_by = '' AND b.quarantine = ''"
                "   ORDER BY b.embedding <=> a.embedding LIMIT 1"
                " ) n ON n.dist <= %s"
                " WHERE a.embedding IS NOT NULL AND a.superseded_by = '' AND a.quarantine = ''",
                (max_distance,),
            ).fetchall()
        seen: set[tuple[str, str]] = set()
        pairs: list[tuple[str, str]] = []
        for r in rows:
            key = (min(r["a_id"], r["b_id"]), max(r["a_id"], r["b_id"]))
            if key in seen:
                continue  # each pair surfaces twice (a->b and b->a)
            seen.add(key)
            if (r["a_pri"], -r["a_created"]) >= (r["b_pri"], -r["b_created"]):
                pairs.append((r["a_id"], r["b_id"]))
            else:
                pairs.append((r["b_id"], r["a_id"]))
        return pairs

    def audit(self, op: str, detail: str) -> None:
        with self._lock:
            self.db.execute(
                "INSERT INTO audit_log (op, detail, ts) VALUES (%s, %s, %s)", (op, detail, now_ms())
            )

    def get_audit(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock:
            return self.db.execute(
                "SELECT op, detail, ts FROM audit_log ORDER BY id DESC LIMIT %s", (limit,)
            ).fetchall()

    # ============================
    # Pipeline state / metadata
    # ============================

    def get_pipeline_state(self, session_key: str) -> dict[str, int]:
        with self._lock:
            row = self.db.execute(
                "SELECT watermark, pending, threshold FROM pipeline_state WHERE session_key = %s",
                (session_key,),
            ).fetchone()
        return dict(row) if row else {"watermark": 0, "pending": 0, "threshold": 1}

    def set_pipeline_state(self, session_key: str, watermark: int, pending: int, threshold: int) -> None:
        with self._lock:
            self.db.execute(
                "INSERT INTO pipeline_state (session_key, watermark, pending, threshold)"
                " VALUES (%s, %s, %s, %s) ON CONFLICT (session_key) DO UPDATE SET"
                " watermark = EXCLUDED.watermark, pending = EXCLUDED.pending, threshold = EXCLUDED.threshold",
                (session_key, watermark, pending, threshold),
            )

    def get_kv(self, key: str) -> str | None:
        with self._lock:
            row = self.db.execute("SELECT value FROM kv_meta WHERE key = %s", (key,)).fetchone()
        return row["value"] if row else None

    def set_kv(self, key: str, value: str) -> None:
        with self._lock:
            self.db.execute(
                "INSERT INTO kv_meta (key, value) VALUES (%s, %s)"
                " ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
                (key, value),
            )

    def stats(self) -> dict[str, Any]:
        with self._lock:
            l0 = int(self.db.execute("SELECT COUNT(*) AS n FROM l0_conversations").fetchone()["n"])
            l1 = int(self.db.execute("SELECT COUNT(*) AS n FROM l1_records").fetchone()["n"])
            sessions = int(
                self.db.execute("SELECT COUNT(DISTINCT session_key) AS n FROM l0_conversations").fetchone()["n"]
            )
        return {
            "backend": "postgres",
            "l0_messages": l0,
            "l1_memories": l1,
            "sessions": sessions,
            "vectors": self.vec_enabled,
        }

    def close(self) -> None:
        with self._lock:
            self.db.close()
