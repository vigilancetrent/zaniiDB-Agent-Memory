"""Tests for v0.4: temporal search, team scope, consolidation/decay, audit,
skills parsing, bench harness, auto-offload, adapters, dashboard, tokenizers."""
import time

from fastapi.testclient import TestClient

from zanii_memory.adapters import AgentMemoryHooks, PromptInjection
from zanii_memory.autooffload import AutoOffloader
from zanii_memory.bench import run_bench
from zanii_memory.core import MemoryCore
from zanii_memory.gateway import create_app
from zanii_memory.pipeline.consolidate import consolidate
from zanii_memory.pipeline.skills import parse_skills
from zanii_memory.store import SqliteStore
from zanii_memory.types import MemoryRecord, now_ms


# ---- temporal search ----

def test_temporal_filters(tmp_path):
    store = SqliteStore(tmp_path / "t.db")
    old = MemoryRecord(content="The user chose the old blue logo design", created_at=1000)
    new = MemoryRecord(content="The user chose the new blue navbar design")
    store.insert_l1(old)
    store.insert_l1(new)

    all_hits = store.keyword_search_l1("blue design")
    assert len(all_hits) == 2
    recent = store.keyword_search_l1("blue design", since=now_ms() - 60_000)
    assert [h["id"] for h in recent] == [new.id]
    ancient = store.hybrid_search_l1("blue design", until=2000)
    assert [h["id"] for h in ancient] == [old.id]
    store.close()


# ---- team scope + recall injection ----

async def test_team_scope_injected_into_recall(cfg):
    core = MemoryCore(cfg)
    await core.initialize()
    await core.seed(
        [
            {"content": "Team rule: all client emails go through legal review", "type": "instruction", "scope": "team"},
            {"content": "The user likes espresso", "type": "persona"},
        ]
    )
    recall = await core.recall("anything at all", "s1")
    assert "Team knowledge" in recall.append_system_context
    assert "legal review" in recall.append_system_context
    assert "espresso" not in recall.append_system_context  # user-scope memories are search results, not system context
    await core.close()


# ---- chronological recall ordering ----

async def test_chronological_recall_orders_oldest_first(cfg):
    core = MemoryCore(cfg.model_copy(update={"recall_chronological": True}))
    await core.initialize()
    old = MemoryRecord(content="The user preferred blue themes early on", created_at=1000)
    new = MemoryRecord(content="The user now prefers dark themes over blue", created_at=2000)
    core.store.insert_l1(new)  # inserted newest-first to prove sorting, not insert order
    core.store.insert_l1(old)
    recall = await core.recall("themes blue preference", "s1")
    assert "oldest to newest" in recall.prepend_context
    assert recall.prepend_context.index("early on") < recall.prepend_context.index("now prefers")
    await core.close()


# ---- consolidation & decay ----

def test_retention_decay(cfg, tmp_path):
    store = SqliteStore(tmp_path / "d.db")
    week_ms = 7 * 86_400_000
    stale = MemoryRecord(content="The user parked on level 3 once", type="episodic", priority=60,
                         created_at=now_ms() - 100 * 86_400_000)
    important = MemoryRecord(content="The user signed the acquisition deal", type="episodic", priority=95,
                             created_at=now_ms() - 100 * 86_400_000)
    persona = MemoryRecord(content="The user is vegetarian", type="persona", priority=60,
                           created_at=now_ms() - 100 * 86_400_000)
    for r in (stale, important, persona):
        store.insert_l1(r)

    cfg2 = cfg.model_copy(update={"retention_episodic_days": 30})
    result = consolidate(store, cfg2)
    assert result["decayed"] == 1
    remaining = {r["id"] for r in store.get_all_l1()}
    assert stale.id not in remaining
    assert important.id in remaining and persona.id in remaining  # high-priority + non-episodic survive
    # idempotent
    assert consolidate(store, cfg2)["decayed"] == 0
    store.close()


def test_delete_l1_and_filtered(tmp_path):
    store = SqliteStore(tmp_path / "x.db")
    a = MemoryRecord(content="alpha fact", type="episodic")
    b = MemoryRecord(content="beta fact", type="persona", scope="team")
    store.insert_l1(a)
    store.insert_l1(b)
    assert len(store.get_l1_filtered(scope="team")) == 1
    assert store.delete_l1([a.id]) == 1
    assert store.keyword_search_l1("alpha") == []  # fts cleaned by trigger
    store.close()


# ---- audit ----

async def test_audit_log(cfg):
    core = MemoryCore(cfg.model_copy(update={"audit_enabled": True}))
    await core.initialize()
    await core.seed([{"content": "auditable fact"}])
    await core.search_memories("fact")
    entries = core.audit_log()
    ops = [e["op"] for e in entries]
    assert "seed" in ops and "search_memories" in ops
    await core.close()


# ---- skills parsing ----

def test_parse_skills():
    text = """## SKILL: Deploy the billing service
**When to use**: release day
**Procedure**:
1. run canary
2. promote

## SKILL: Format weekly report
**When to use**: fridays
**Procedure**:
1. bullet points only
"""
    skills = parse_skills(text)
    assert [name for name, _ in skills] == ["Deploy the billing service", "Format weekly report"]
    assert "canary" in skills[0][1]
    assert parse_skills("NONE") == []
    assert parse_skills("no headers here") == []


# ---- bench ----

async def test_bench_runs_and_scores(cfg):
    result = await run_bench(cfg)
    assert result["mode"] == "keyword"
    assert result["queries"] == 20
    assert result["recall_at_5"] >= 0.5  # keyword mode still finds most curated cases
    assert 0 <= result["mrr"] <= 1


# ---- auto-offload ----

async def test_autooffload_filters_only_big_tool_messages(cfg):
    core = MemoryCore(cfg)
    await core.initialize()
    auto = AutoOffloader(core, "task-1", threshold_chars=100)
    messages = [
        {"role": "user", "content": "x" * 500},          # user content is never offloaded
        {"role": "tool", "content": "y" * 500, "name": "grep"},
        {"role": "tool", "content": "small"},
    ]
    out = await auto.filter_messages(messages)
    assert out[0]["content"] == "x" * 500
    assert out[1]["content"].startswith("[offloaded:N")
    assert out[2]["content"] == "small"
    # idempotent: stubs are not re-offloaded
    again = await auto.filter_messages(out)
    assert again[1]["content"] == out[1]["content"]
    # drill-down works
    node_id = out[1]["content"].split("]")[0].split(":")[1]
    assert "y" * 100 in (await core.retrieve_ref(node_id))
    await core.close()


# ---- adapters ----

async def test_agent_hooks_roundtrip(cfg):
    core = MemoryCore(cfg)
    await core.initialize()
    hooks = AgentMemoryHooks(core, "sess-1")
    await hooks.after_turn("I always want answers in French", "Bien sûr!")
    await core.seed([{"content": "The user requires the AI to reply in French", "type": "instruction"}])
    injection = await hooks.before_turn("reply language french")
    assert "French" in injection.prepend
    msgs = AgentMemoryHooks.inject(
        [{"role": "system", "content": "base"}, {"role": "user", "content": "hi"}],
        PromptInjection(prepend="MEMS", system="PERSONA"),
    )
    assert msgs[0]["content"] == "base\n\nPERSONA"
    assert msgs[1]["content"].startswith("MEMS\n\n")
    await core.close()


# ---- dashboard + new gateway routes ----

def test_dashboard_and_overview(cfg):
    with TestClient(create_app(cfg)) as client:
        page = client.get("/dashboard")
        assert page.status_code == 200 and "ZaniiDB Agent Memory" in page.text
        overview = client.get("/api/overview").json()
        assert overview["backend"] == "sqlite"
        assert "recent_memories" in overview and "skills" in overview
        assert client.post("/consolidate").json() == {"duplicates_removed": 0, "decayed": 0}
        assert client.get("/audit").json() == {"entries": []}
        # temporal params validated
        assert client.post("/search/memories", json={"query": "x", "since": "not-a-date"}).status_code == 422
        assert client.post("/search/memories", json={"query": "x", "since": "2026-07-01"}).status_code == 200


def test_dashboard_query_token_auth(cfg):
    cfg = cfg.model_copy(update={"gateway_api_key": "sekret"})
    with TestClient(create_app(cfg)) as client:
        assert client.get("/dashboard").status_code == 401
        assert client.get("/dashboard?token=sekret").status_code == 200


# ---- trigram tokenizer (CJK) ----

def test_trigram_tokenizer_matches_cjk(tmp_path):
    store = SqliteStore(tmp_path / "cjk.db", fts_tokenizer="trigram")
    store.insert_l1(MemoryRecord(content="用户喜欢在早晨喝深度烘焙的咖啡"))
    # trigram matching needs a contiguous substring of >= 3 chars
    hits = store.keyword_search_l1("深度烘焙")
    assert hits and "咖啡" in hits[0]["content"]
    # short (2-char) CJK queries fall back to substring scan automatically
    short_hits = store.keyword_search_l1("咖啡")
    assert short_hits and "咖啡" in short_hits[0]["content"]
    assert store.search_l0("咖啡") == []  # fallback respects empty tables too
    # default unicode61 tokenizer cannot match inside CJK text at all
    default_store = SqliteStore(tmp_path / "default.db")
    default_store.insert_l1(MemoryRecord(content="用户喜欢在早晨喝深度烘焙的咖啡"))
    assert default_store.keyword_search_l1("深度烘焙") == []
    default_store.close()
    store.close()


def test_invalid_tokenizer_rejected(tmp_path):
    import pytest

    with pytest.raises(ValueError, match="fts_tokenizer"):
        SqliteStore(tmp_path / "bad.db", fts_tokenizer="jieba'); DROP TABLE l1_records;--")
