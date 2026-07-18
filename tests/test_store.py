from zanii_memory.store import SqliteStore, fts_query, rrf_fuse
from zanii_memory.types import MemoryRecord


def make_store(tmp_path) -> SqliteStore:
    return SqliteStore(tmp_path / "test.db", want_vectors=False)


def test_rrf_fuse_prefers_items_in_both_rankings():
    fused = rrf_fuse([[1, 2, 3], [3, 4, 1]])
    ids = [rowid for rowid, _ in fused]
    assert ids[0] in (1, 3)  # items present in both lists rank first
    assert set(ids) == {1, 2, 3, 4}
    scores = dict(fused)
    assert scores[1] > scores[2]
    assert scores[3] > scores[4]


def test_fts_query_quotes_tokens():
    assert fts_query("hello world's fts5(syntax)") == '"hello" OR "world" OR "s" OR "fts5" OR "syntax"'
    assert fts_query("!!!") == ""


def test_l1_insert_and_keyword_search(tmp_path):
    store = make_store(tmp_path)
    store.insert_l1(MemoryRecord(content="The user prefers dark roast coffee in the morning", type="persona"))
    store.insert_l1(MemoryRecord(content="The user deployed the billing service on July 3", type="episodic"))
    store.insert_l1(MemoryRecord(content="The user requires the AI to answer in bullet points", type="instruction"))

    hits = store.keyword_search_l1("coffee preference")
    assert hits and "coffee" in hits[0]["content"]

    typed = store.keyword_search_l1("user", type="instruction")
    assert all(h["type"] == "instruction" for h in typed)

    assert store.l1_content_exists("The user prefers dark roast coffee in the morning")
    assert not store.l1_content_exists("nonexistent")
    assert store.count_l1() == 3
    store.close()


def test_hybrid_falls_back_to_keyword_without_vectors(tmp_path):
    store = make_store(tmp_path)
    store.insert_l1(MemoryRecord(content="The user lives in Istanbul"))
    hits = store.hybrid_search_l1("Istanbul", embedding=None, limit=5)
    assert len(hits) == 1
    store.close()


def test_l0_record_and_search(tmp_path):
    store = make_store(tmp_path)
    store.record_l0("s1", "user", "How do I configure the Kafka consumer group?")
    store.record_l0("s1", "assistant", "Set group.id in the consumer config.")
    store.record_l0("s2", "user", "Unrelated question about pandas dataframes")

    hits = store.search_l0("kafka consumer")
    assert hits and hits[0]["session_key"] == "s1"

    scoped = store.search_l0("question", session_key="s2")
    assert all(h["session_key"] == "s2" for h in scoped)

    rows = store.get_l0_after("s1", 0)
    assert len(rows) == 2
    store.close()


def test_pipeline_state_roundtrip(tmp_path):
    store = make_store(tmp_path)
    assert store.get_pipeline_state("s1") == {"watermark": 0, "pending": 0, "threshold": 1}
    store.set_pipeline_state("s1", watermark=42, pending=3, threshold=4)
    assert store.get_pipeline_state("s1") == {"watermark": 42, "pending": 3, "threshold": 4}
    store.set_kv("k", "v1")
    store.set_kv("k", "v2")
    assert store.get_kv("k") == "v2"
    store.close()
