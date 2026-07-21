"""SQLite storage: L0 conversations + L1 memories.

Search stack:
- FTS5 (bm25) keyword search over both layers
- sqlite-vec KNN over L1 (cosine) when embeddings are configured
- Reciprocal Rank Fusion (RRF) to merge the two rankings

If the sqlite-vec extension cannot be loaded, the store silently degrades to
keyword-only search.
"""
from __future__ import annotations

import json
import logging
import re
import sqlite3
import threading
from pathlib import Path
from typing import Any

from ..types import MemoryRecord, now_ms

log = logging.getLogger("zanii_memory.store")

try:
    import sqlite_vec

    _HAS_VEC = True
except ImportError:  # pragma: no cover
    _HAS_VEC = False

RRF_K = 60


def rrf_fuse(rankings: list[list[int]], k: int = RRF_K) -> list[tuple[int, float]]:
    """Merge ranked rowid lists: score = sum over lists of 1/(k + rank)."""
    scores: dict[int, float] = {}
    for ranking in rankings:
        for rank, rowid in enumerate(ranking):
            scores[rowid] = scores.get(rowid, 0.0) + 1.0 / (k + rank + 1)
    return sorted(scores.items(), key=lambda item: -item[1])


def fts_query(text: str, min_token_len: int = 1) -> str:
    """Build a safe FTS5 OR-query from free text (quotes each token).
    Tokens shorter than min_token_len are dropped (trigram mode needs >= 3)."""
    tokens = [t for t in re.findall(r"\w+", text, re.UNICODE) if len(t) >= min_token_len]
    return " OR ".join(f'"{t}"' for t in tokens[:32])


_ALLOWED_TOKENIZERS = {"unicode61", "trigram"}


class SqliteStore:
    def __init__(
        self,
        path: Path,
        dimensions: int = 1536,
        want_vectors: bool = False,
        fts_tokenizer: str = "unicode61",
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.dimensions = dimensions
        if fts_tokenizer not in _ALLOWED_TOKENIZERS:
            raise ValueError(f"fts_tokenizer must be one of {sorted(_ALLOWED_TOKENIZERS)}")
        # Applied at table creation only; changing it on an existing DB requires a rebuild.
        self.fts_tokenizer = fts_tokenizer
        # Trigram FTS cannot match tokens under 3 chars; such queries use a LIKE fallback.
        self._min_token_len = 3 if fts_tokenizer == "trigram" else 1
        self.vec_enabled = False
        if want_vectors and _HAS_VEC:
            try:
                self.db.enable_load_extension(True)
                sqlite_vec.load(self.db)
                self.db.enable_load_extension(False)
                self.vec_enabled = True
            except (AttributeError, sqlite3.OperationalError) as err:
                log.warning("sqlite-vec unavailable, falling back to keyword-only search: %s", err)
        elif want_vectors:
            log.warning("sqlite-vec package not installed; keyword-only search")
        self._create_schema()

    # ============================
    # Schema
    # ============================

    def _create_schema(self) -> None:
        with self._lock:
            self.db.executescript(
                """
                CREATE TABLE IF NOT EXISTS l0_conversations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_key TEXT NOT NULL,
                    session_id TEXT NOT NULL DEFAULT '',
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    channel TEXT NOT NULL DEFAULT 'user',
                    timestamp INTEGER NOT NULL,
                    recorded_at INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_l0_session ON l0_conversations(session_key, id);
                CREATE INDEX IF NOT EXISTS idx_l0_timestamp ON l0_conversations(timestamp);

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
                    metadata TEXT NOT NULL DEFAULT '{}',
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_l1_type ON l1_records(type);
                CREATE INDEX IF NOT EXISTS idx_l1_session ON l1_records(session_key);
                CREATE INDEX IF NOT EXISTS idx_l1_scene ON l1_records(scene_name);

                CREATE TABLE IF NOT EXISTS audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    op TEXT NOT NULL,
                    detail TEXT NOT NULL,
                    ts INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS pipeline_state (
                    session_key TEXT PRIMARY KEY,
                    watermark INTEGER NOT NULL DEFAULT 0,
                    pending INTEGER NOT NULL DEFAULT 0,
                    threshold INTEGER NOT NULL DEFAULT 1
                );

                CREATE TABLE IF NOT EXISTS kv_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                """
            )
            # column migrations for pre-existing databases
            for ddl in (
                "ALTER TABLE l1_records ADD COLUMN scope TEXT NOT NULL DEFAULT 'user'",
                "ALTER TABLE l1_records ADD COLUMN superseded_by TEXT NOT NULL DEFAULT ''",
                "ALTER TABLE l1_records ADD COLUMN quarantine TEXT NOT NULL DEFAULT ''",
                "ALTER TABLE l0_conversations ADD COLUMN channel TEXT NOT NULL DEFAULT 'user'",
            ):
                try:
                    self.db.execute(ddl)
                except sqlite3.OperationalError:
                    pass  # column already exists
            self.db.executescript(
                f"""
                CREATE VIRTUAL TABLE IF NOT EXISTS l0_fts USING fts5(
                    content, content='l0_conversations', content_rowid='id', tokenize='{self.fts_tokenizer}'
                );
                CREATE TRIGGER IF NOT EXISTS l0_ai AFTER INSERT ON l0_conversations BEGIN
                    INSERT INTO l0_fts(rowid, content) VALUES (new.id, new.content);
                END;
                CREATE TRIGGER IF NOT EXISTS l0_ad AFTER DELETE ON l0_conversations BEGIN
                    INSERT INTO l0_fts(l0_fts, rowid, content) VALUES ('delete', old.id, old.content);
                END;

                CREATE VIRTUAL TABLE IF NOT EXISTS l1_fts USING fts5(
                    content, content='l1_records', content_rowid='rowid', tokenize='{self.fts_tokenizer}'
                );
                CREATE TRIGGER IF NOT EXISTS l1_ai AFTER INSERT ON l1_records BEGIN
                    INSERT INTO l1_fts(rowid, content) VALUES (new.rowid, new.content);
                END;
                CREATE TRIGGER IF NOT EXISTS l1_ad AFTER DELETE ON l1_records BEGIN
                    INSERT INTO l1_fts(l1_fts, rowid, content) VALUES ('delete', old.rowid, old.content);
                END;
                """
            )
            if self.vec_enabled:
                self.db.execute(
                    f"""CREATE VIRTUAL TABLE IF NOT EXISTS l1_vec USING vec0(
                        embedding float[{self.dimensions}] distance_metric=cosine
                    )"""
                )
            self.db.commit()

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
            cur = self.db.execute(
                "INSERT INTO l0_conversations (session_key, session_id, role, content, channel,"
                " timestamp, recorded_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (session_key, session_id, role, content, channel, timestamp or now_ms(), now_ms()),
            )
            self.db.commit()
            return int(cur.lastrowid)

    def get_l0_after(self, session_key: str, after_id: int, limit: int = 200) -> list[dict[str, Any]]:
        with self._lock:
            rows = self.db.execute(
                "SELECT * FROM l0_conversations WHERE session_key = ? AND id > ? ORDER BY id LIMIT ?",
                (session_key, after_id, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_l0_before(self, session_key: str, before_id: int, limit: int = 6) -> list[dict[str, Any]]:
        with self._lock:
            rows = self.db.execute(
                "SELECT * FROM l0_conversations WHERE session_key = ? AND id <= ? ORDER BY id DESC LIMIT ?",
                (session_key, before_id, limit),
            ).fetchall()
        return [dict(r) for r in reversed(rows)]

    def search_l0(self, query: str, limit: int = 10, session_key: str | None = None) -> list[dict[str, Any]]:
        """Keyword (BM25) search over raw conversations.

        ponytail: L0 is keyword-only in v1 — no embeddings are stored for raw
        turns. Add an l0_vec table + deferred embedding if semantic
        conversation search proves necessary.
        """
        match = fts_query(query, self._min_token_len)
        if not match:
            return self._like_search(
                "l0_conversations", query, limit, extra_where="session_key = ?" if session_key else "",
                extra_params=[session_key] if session_key else [],
            )
        sql = (
            "SELECT c.*, bm25(l0_fts) AS rank FROM l0_fts"
            " JOIN l0_conversations c ON c.id = l0_fts.rowid"
            " WHERE l0_fts MATCH ?"
        )
        params: list[Any] = [match]
        if session_key:
            sql += " AND c.session_key = ?"
            params.append(session_key)
        sql += " ORDER BY rank LIMIT ?"
        params.append(limit)
        with self._lock:
            rows = self.db.execute(sql, params).fetchall()
        return [{**dict(r), "score": -r["rank"]} for r in rows]

    def _like_search(
        self,
        table: str,
        query: str,
        limit: int,
        extra_where: str = "",
        extra_params: list[Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Substring fallback for queries the FTS tokenizer cannot serve
        (e.g. 2-char CJK words in trigram mode). Sequential scan — fine at
        the corpus sizes where trigram mode is in play."""
        tokens = re.findall(r"\w+", query, re.UNICODE)[:8]
        if not tokens:
            return []
        clauses = " OR ".join("content LIKE ? ESCAPE '\\'" for _ in tokens)
        escaped = [t.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") for t in tokens]
        params: list[Any] = [f"%{t}%" for t in escaped]
        sql = f"SELECT rowid AS _rowid, * FROM {table} WHERE ({clauses})"
        if table == "l1_records":
            sql += " AND superseded_by = '' AND quarantine = ''"
        if extra_where:
            sql += f" AND {extra_where}"
            params.extend(extra_params or [])
        order = "priority DESC, created_at DESC" if table == "l1_records" else "id DESC"
        sql += f" ORDER BY {order} LIMIT ?"
        params.append(limit)
        with self._lock:
            rows = self.db.execute(sql, params).fetchall()
        return [{**dict(r), "score": 0.0} for r in rows]

    # ============================
    # L1 memories
    # ============================

    def insert_l1(
        self, record: MemoryRecord, embedding: list[float] | None = None, quarantine: str = ""
    ) -> int:
        with self._lock:
            cur = self.db.execute(
                "INSERT INTO l1_records (id, type, content, priority, scope, scene_name, session_key,"
                " session_id, metadata, created_at, updated_at, superseded_by, quarantine)"
                f" VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '', ?)",
                (
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
                    quarantine,
                ),
            )
            rowid = int(cur.lastrowid)
            if embedding is not None and self.vec_enabled:
                self.db.execute(
                    "INSERT INTO l1_vec(rowid, embedding) VALUES (?, ?)",
                    (rowid, sqlite_vec.serialize_float32(embedding)),
                )
            self.db.commit()
            return rowid

    def l1_content_exists(self, content: str) -> bool:
        with self._lock:
            row = self.db.execute("SELECT 1 FROM l1_records WHERE content = ? LIMIT 1", (content,)).fetchone()
        return row is not None

    def count_l1(self) -> int:
        """Active (non-superseded, non-quarantined) memories."""
        with self._lock:
            return int(
                self.db.execute(
                    "SELECT COUNT(*) FROM l1_records WHERE superseded_by = '' AND quarantine = ''"
                ).fetchone()[0]
            )

    def quarantine_l1(self, ids: list[str], reason: str) -> int:
        if not ids:
            return 0
        placeholders = ",".join("?" * len(ids))
        with self._lock:
            cur = self.db.execute(
                f"UPDATE l1_records SET quarantine = ?, updated_at = ? WHERE id IN ({placeholders})",
                [reason[:300], now_ms(), *ids],
            )
            self.db.commit()
            return cur.rowcount

    def release_l1(self, ids: list[str]) -> int:
        """Human review approved: memory rejoins active recall."""
        if not ids:
            return 0
        placeholders = ",".join("?" * len(ids))
        with self._lock:
            cur = self.db.execute(
                f"UPDATE l1_records SET quarantine = '', updated_at = ? WHERE id IN ({placeholders})"
                " AND quarantine != ''",
                [now_ms(), *ids],
            )
            self.db.commit()
            return cur.rowcount

    def get_quarantined(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock:
            rows = self.db.execute(
                "SELECT id, type, content, priority, scope, scene_name, session_key, session_id,"
                " metadata, created_at, updated_at, quarantine FROM l1_records"
                " WHERE quarantine != '' ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def mark_superseded(self, old_ids: list[str], new_id: str) -> int:
        """Conflict resolution: old memories are kept (white-box history) but
        excluded from every search/recall path."""
        if not old_ids:
            return 0
        placeholders = ",".join("?" * len(old_ids))
        with self._lock:
            cur = self.db.execute(
                f"UPDATE l1_records SET superseded_by = ?, updated_at = ? WHERE id IN ({placeholders})"
                " AND superseded_by = ''",
                [new_id, now_ms(), *old_ids],
            )
            self.db.commit()
            return cur.rowcount

    def get_all_l1(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self.db.execute(
                "SELECT id, type, content, priority, scope, scene_name, session_key, session_id,"
                " metadata, created_at, updated_at, superseded_by, quarantine"
                " FROM l1_records ORDER BY created_at"
            ).fetchall()
        return [dict(r) for r in rows]

    def get_l1_filtered(
        self,
        type: str | None = None,
        scope: str | None = None,
        created_before: int | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        sql = (
            "SELECT id, type, content, priority, scope, scene_name, session_key, session_id,"
            " metadata, created_at, updated_at FROM l1_records WHERE superseded_by = '' AND quarantine = ''"
        )
        params: list[Any] = []
        if type:
            sql += " AND type = ?"
            params.append(type)
        if scope:
            sql += " AND scope = ?"
            params.append(scope)
        if created_before is not None:
            sql += " AND created_at < ?"
            params.append(created_before)
        sql += " ORDER BY priority DESC, created_at DESC LIMIT ?"
        params.append(limit)
        with self._lock:
            rows = self.db.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def delete_l1(self, ids: list[str]) -> int:
        if not ids:
            return 0
        placeholders = ",".join("?" * len(ids))
        with self._lock:
            if self.vec_enabled:
                rowids = [
                    r[0]
                    for r in self.db.execute(
                        f"SELECT rowid FROM l1_records WHERE id IN ({placeholders})", ids
                    ).fetchall()
                ]
                if rowids:
                    vec_ph = ",".join("?" * len(rowids))
                    self.db.execute(f"DELETE FROM l1_vec WHERE rowid IN ({vec_ph})", rowids)
            cur = self.db.execute(f"DELETE FROM l1_records WHERE id IN ({placeholders})", ids)
            self.db.commit()
            return cur.rowcount

    def find_near_duplicate_pairs(self, max_distance: float) -> list[tuple[str, str]]:
        """(keep_id, drop_id) pairs of semantically near-duplicate memories.
        Keeps the higher-priority record; on ties, the older one."""
        if not self.vec_enabled:
            return []
        with self._lock:
            vec_rows = self.db.execute("SELECT rowid, embedding FROM l1_vec").fetchall()
            raw_pairs: list[tuple[int, int]] = []
            for vec_row in vec_rows:
                hits = self.db.execute(
                    "SELECT rowid, distance FROM l1_vec WHERE embedding MATCH ? AND k = 2",
                    (vec_row["embedding"],),
                ).fetchall()
                for hit in hits:
                    other = hit["rowid"]
                    if other != vec_row["rowid"] and hit["distance"] <= max_distance:
                        raw_pairs.append((min(vec_row["rowid"], other), max(vec_row["rowid"], other)))
        pairs: list[tuple[str, str]] = []
        rows = self._fetch_l1_rows(sorted({rid for pair in set(raw_pairs) for rid in pair}))
        for a, b in sorted(set(raw_pairs)):
            ra, rb = rows.get(a), rows.get(b)
            if not ra or not rb:
                continue
            keep, drop = (ra, rb) if (ra["priority"], -ra["created_at"]) >= (rb["priority"], -rb["created_at"]) else (rb, ra)
            pairs.append((keep["id"], drop["id"]))
        return pairs

    def audit(self, op: str, detail: str) -> None:
        with self._lock:
            self.db.execute(
                "INSERT INTO audit_log (op, detail, ts) VALUES (?, ?, ?)", (op, detail, now_ms())
            )
            self.db.commit()

    def get_audit(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock:
            rows = self.db.execute(
                "SELECT op, detail, ts FROM audit_log ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    def get_all_l0(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self.db.execute(
                "SELECT id, session_key, session_id, role, content, timestamp, recorded_at"
                " FROM l0_conversations ORDER BY id"
            ).fetchall()
        return [dict(r) for r in rows]

    def l0_exists(self, session_key: str, role: str, content: str, timestamp: int) -> bool:
        with self._lock:
            row = self.db.execute(
                "SELECT 1 FROM l0_conversations WHERE session_key = ? AND role = ?"
                " AND content = ? AND timestamp = ? LIMIT 1",
                (session_key, role, content, timestamp),
            ).fetchone()
        return row is not None

    def _fetch_l1_rows(self, rowids: list[int]) -> dict[int, dict[str, Any]]:
        if not rowids:
            return {}
        placeholders = ",".join("?" * len(rowids))
        with self._lock:
            rows = self.db.execute(
                f"SELECT rowid AS _rowid, * FROM l1_records WHERE rowid IN ({placeholders})", rowids
            ).fetchall()
        return {r["_rowid"]: dict(r) for r in rows}

    def keyword_search_l1(
        self,
        query: str,
        limit: int = 10,
        type: str | None = None,
        since: int | None = None,
        until: int | None = None,
    ) -> list[dict[str, Any]]:
        match = fts_query(query, self._min_token_len)
        if not match:
            extra, extra_params = [], []
            if type:
                extra.append("type = ?")
                extra_params.append(type)
            if since is not None:
                extra.append("created_at >= ?")
                extra_params.append(since)
            if until is not None:
                extra.append("created_at <= ?")
                extra_params.append(until)
            return self._like_search(
                "l1_records", query, limit, extra_where=" AND ".join(extra), extra_params=extra_params
            )
        sql = (
            "SELECT r.rowid AS _rowid, r.*, bm25(l1_fts) AS rank FROM l1_fts"
            " JOIN l1_records r ON r.rowid = l1_fts.rowid WHERE l1_fts MATCH ?"
            " AND r.superseded_by = '' AND r.quarantine = ''"
        )
        params: list[Any] = [match]
        if type:
            sql += " AND r.type = ?"
            params.append(type)
        if since is not None:
            sql += " AND r.created_at >= ?"
            params.append(since)
        if until is not None:
            sql += " AND r.created_at <= ?"
            params.append(until)
        sql += " ORDER BY rank LIMIT ?"
        params.append(limit)
        with self._lock:
            rows = self.db.execute(sql, params).fetchall()
        return [{**dict(r), "score": -r["rank"]} for r in rows]

    def vector_search_l1(self, embedding: list[float], limit: int = 10) -> list[dict[str, Any]]:
        if not self.vec_enabled:
            return []
        with self._lock:
            hits = self.db.execute(
                "SELECT rowid, distance FROM l1_vec WHERE embedding MATCH ? AND k = ? ORDER BY distance",
                (sqlite_vec.serialize_float32(embedding), limit),
            ).fetchall()
        rows = self._fetch_l1_rows([h["rowid"] for h in hits])
        results = []
        for h in hits:
            row = rows.get(h["rowid"])
            if row and not row.get("superseded_by") and not row.get("quarantine"):
                results.append({**row, "score": 1.0 - h["distance"], "distance": h["distance"]})
        return results

    def hybrid_search_l1(
        self,
        query: str,
        embedding: list[float] | None = None,
        limit: int = 5,
        type: str | None = None,
        since: int | None = None,
        until: int | None = None,
    ) -> list[dict[str, Any]]:
        """RRF fusion of BM25 + vector rankings; falls back to whichever is available."""
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
        fused = rrf_fuse([[h["_rowid"] for h in keyword_hits], [h["_rowid"] for h in vector_hits]])
        by_rowid = {h["_rowid"]: h for h in keyword_hits + vector_hits}
        return [{**by_rowid[rid], "score": score} for rid, score in fused[:limit]]

    def nearest_l1_distance(self, embedding: list[float]) -> float | None:
        """Cosine distance to the closest existing memory (for dedup)."""
        hits = self.vector_search_l1(embedding, limit=1)
        return hits[0]["distance"] if hits else None

    # ============================
    # Pipeline state / metadata
    # ============================

    def get_pipeline_state(self, session_key: str) -> dict[str, int]:
        with self._lock:
            row = self.db.execute(
                "SELECT watermark, pending, threshold FROM pipeline_state WHERE session_key = ?",
                (session_key,),
            ).fetchone()
        return dict(row) if row else {"watermark": 0, "pending": 0, "threshold": 1}

    def set_pipeline_state(self, session_key: str, watermark: int, pending: int, threshold: int) -> None:
        with self._lock:
            self.db.execute(
                "INSERT INTO pipeline_state (session_key, watermark, pending, threshold) VALUES (?, ?, ?, ?)"
                " ON CONFLICT(session_key) DO UPDATE SET watermark=excluded.watermark,"
                " pending=excluded.pending, threshold=excluded.threshold",
                (session_key, watermark, pending, threshold),
            )
            self.db.commit()

    def get_kv(self, key: str) -> str | None:
        with self._lock:
            row = self.db.execute("SELECT value FROM kv_meta WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None

    def set_kv(self, key: str, value: str) -> None:
        with self._lock:
            self.db.execute(
                "INSERT INTO kv_meta (key, value) VALUES (?, ?)"
                " ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )
            self.db.commit()

    def stats(self) -> dict[str, Any]:
        with self._lock:
            l0 = int(self.db.execute("SELECT COUNT(*) FROM l0_conversations").fetchone()[0])
            l1 = int(self.db.execute("SELECT COUNT(*) FROM l1_records").fetchone()[0])
            sessions = int(
                self.db.execute("SELECT COUNT(DISTINCT session_key) FROM l0_conversations").fetchone()[0]
            )
        return {
            "backend": "sqlite",
            "l0_messages": l0,
            "l1_memories": l1,
            "sessions": sessions,
            "vectors": self.vec_enabled,
        }

    def close(self) -> None:
        with self._lock:
            self.db.close()
