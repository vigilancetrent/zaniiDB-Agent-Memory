"""PostgreSQL backend tests.

Live tests need a reachable Postgres and are skipped otherwise:
    set ZANII_TEST_PG_DSN=postgresql://user:pass@localhost:5432/zanii_test
"""
import os

import pytest

from zanii_memory.config import Settings
from zanii_memory.store import SqliteStore, create_store
from zanii_memory.types import MemoryRecord

PG_DSN = os.environ.get("ZANII_TEST_PG_DSN", "")


def test_factory_defaults_to_sqlite(cfg):
    store = create_store(cfg, want_vectors=False)
    assert isinstance(store, SqliteStore)
    store.close()


def test_factory_rejects_unknown_scheme(cfg):
    bad = cfg.model_copy(update={"database_url": "mysql://localhost/db"})
    with pytest.raises(ValueError, match="Unsupported ZANII_DATABASE_URL scheme"):
        create_store(bad, want_vectors=False)


def test_postgres_import_error_is_helpful(cfg):
    try:
        import psycopg  # noqa: F401

        pytest.skip("psycopg installed — missing-dependency error path not reachable")
    except ImportError:
        pass
    pg = cfg.model_copy(update={"database_url": "postgresql://localhost/db"})
    with pytest.raises(RuntimeError, match="zaniidb-agent-memory\\[postgres\\]"):
        create_store(pg, want_vectors=False)


@pytest.mark.skipif(not PG_DSN, reason="ZANII_TEST_PG_DSN not set")
def test_postgres_roundtrip(cfg):
    pg_cfg = cfg.model_copy(update={"database_url": PG_DSN})
    store = create_store(pg_cfg, want_vectors=False)
    try:
        store.insert_l1(MemoryRecord(content="The user prefers dark roast coffee", type="persona"))
        assert store.l1_content_exists("The user prefers dark roast coffee")
        hits = store.keyword_search_l1("coffee")
        assert hits and "coffee" in hits[0]["content"]

        rowid = store.record_l0("pg-s1", "user", "postgres backend smoke test")
        assert rowid > 0
        assert store.search_l0("postgres smoke")
        assert store.get_l0_after("pg-s1", 0)

        store.set_pipeline_state("pg-s1", 7, 2, 4)
        assert store.get_pipeline_state("pg-s1") == {"watermark": 7, "pending": 2, "threshold": 4}
        store.set_kv("k", "v")
        assert store.get_kv("k") == "v"
        assert store.stats()["backend"] == "postgres"
    finally:
        store.close()
