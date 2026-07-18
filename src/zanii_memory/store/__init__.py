from __future__ import annotations

from typing import TYPE_CHECKING

from .base import MemoryStore
from .sqlite import SqliteStore, fts_query, rrf_fuse

if TYPE_CHECKING:
    from ..config import Settings


def create_store(cfg: "Settings", want_vectors: bool) -> MemoryStore:
    """Backend selection: ZANII_DATABASE_URL set -> Postgres, else SQLite."""
    if cfg.database_url:
        if not cfg.database_url.startswith(("postgres://", "postgresql://")):
            raise ValueError(
                f"Unsupported ZANII_DATABASE_URL scheme: {cfg.database_url.split(':', 1)[0]!r}"
                " (expected postgresql://... or empty for SQLite)"
            )
        from .postgres import PostgresStore

        return PostgresStore(
            cfg.database_url,
            dimensions=cfg.embedding_dimensions,
            want_vectors=want_vectors,
            text_search_config=cfg.pg_text_search_config,
        )
    return SqliteStore(
        cfg.db_path,
        dimensions=cfg.embedding_dimensions,
        want_vectors=want_vectors,
        fts_tokenizer=cfg.fts_tokenizer,
    )


__all__ = ["MemoryStore", "SqliteStore", "create_store", "rrf_fuse", "fts_query"]
