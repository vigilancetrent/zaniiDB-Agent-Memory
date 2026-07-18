import json
import re

import httpx

from zanii_memory.config import Settings
from zanii_memory.llm import LLMClient
from zanii_memory.pipeline.scenes import maybe_condense_scene
from zanii_memory.pipeline.supersede import parse_supersede, resolve_conflicts
from zanii_memory.store import SqliteStore
from zanii_memory.types import MemoryRecord


async def test_resolve_conflicts_never_crosses_types(tmp_path):
    store = SqliteStore(tmp_path / "g.db", dimensions=4, want_vectors=True)
    assert store.vec_enabled
    same_type = MemoryRecord(content="The user prefers coffee", type="persona")
    cross_type = MemoryRecord(content="The user ordered a coffee yesterday", type="episodic")
    store.insert_l1(same_type, [1.0, 0.0, 0.0, 0.0])
    store.insert_l1(cross_type, [0.995, 0.0999, 0.0, 0.0])  # semantically very close
    new = MemoryRecord(content="The user switched to tea", type="persona")
    store.insert_l1(new, [0.98, 0.199, 0.0, 0.0])

    def handler(request: httpx.Request) -> httpx.Response:
        # aggressive judge: supersedes EVERY candidate it is shown
        body = json.loads(request.content)["messages"][-1]["content"]
        olds = re.findall(r"EXISTING ([0-9a-f]{32})", body)
        news = re.findall(r"NEW ([0-9a-f]{32})", body)
        assert cross_type.id not in olds  # guard filtered it before the LLM ever saw it
        return httpx.Response(
            200, json={"choices": [{"message": {"content": json.dumps([{"new_id": news[0], "supersedes": olds}])}}]}
        )

    cfg = Settings(_env_file=None, llm_base_url="http://mock/v1", llm_api_key="k", llm_model="m")
    llm = LLMClient(cfg)
    llm._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    superseded = await resolve_conflicts(store, llm, cfg, [(new, [0.98, 0.199, 0.0, 0.0])])
    assert superseded == 1
    by_id = {r["id"]: r for r in store.get_all_l1()}
    assert by_id[same_type.id]["superseded_by"] == new.id  # same-type conflict resolved
    assert by_id[cross_type.id]["superseded_by"] == ""  # cross-type memory untouched
    await llm.close()
    store.close()


def test_mark_superseded_excludes_from_all_search_paths(tmp_path):
    store = SqliteStore(tmp_path / "s.db")
    old = MemoryRecord(content="The user prefers coffee in the morning")
    new = MemoryRecord(content="The user switched to tea in the morning")
    store.insert_l1(old)
    store.insert_l1(new)
    assert store.count_l1() == 2

    assert store.mark_superseded([old.id], new.id) == 1
    assert store.count_l1() == 1
    # keyword search, filtered fetch and hybrid all exclude the superseded memory
    assert all(h["id"] != old.id for h in store.keyword_search_l1("coffee morning"))
    assert all(r["id"] != old.id for r in store.get_l1_filtered(limit=10))
    assert all(h["id"] != old.id for h in store.hybrid_search_l1("morning drink"))
    # but history is preserved white-box for audit/export
    exported = {r["id"]: r for r in store.get_all_l1()}
    assert exported[old.id]["superseded_by"] == new.id
    # idempotent: already-superseded rows are not re-marked
    assert store.mark_superseded([old.id], "someone-else") == 0
    store.close()


async def test_duplicate_verdict_drops_new_copy(tmp_path):
    store = SqliteStore(tmp_path / "dup.db", dimensions=4, want_vectors=True)
    original = MemoryRecord(content="The user is interested in diversified portfolios", type="persona")
    store.insert_l1(original, [1.0, 0.0, 0.0, 0.0])
    paraphrase = MemoryRecord(content="The user is exploring diversified portfolios", type="persona")
    store.insert_l1(paraphrase, [0.97, 0.243, 0.0, 0.0])

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps(
                [{"new_id": paraphrase.id, "duplicate_of": original.id}]
            )}}]},
        )

    cfg = Settings(_env_file=None, llm_base_url="http://mock/v1", llm_api_key="k", llm_model="m")
    llm = LLMClient(cfg)
    llm._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    superseded = await resolve_conflicts(store, llm, cfg, [(paraphrase, [0.97, 0.243, 0.0, 0.0])])
    assert superseded == 0  # nothing superseded — the paraphrase was dropped instead
    remaining = {r["id"]: r for r in store.get_all_l1()}
    assert original.id in remaining and remaining[original.id]["superseded_by"] == ""
    assert paraphrase.id not in remaining  # new copy deleted, no churn
    await llm.close()
    store.close()


def test_parse_supersede_lenient():
    assert parse_supersede('[{"new_id": "a", "supersedes": ["b"]}]') == [{"new_id": "a", "supersedes": ["b"]}]
    assert parse_supersede("```json\n[]\n```") == []
    assert parse_supersede("no json") == []
    assert parse_supersede('[{"supersedes": ["x"]}]') == []  # missing new_id dropped


async def test_maybe_condense_scene(tmp_path):
    cfg = Settings(_env_file=None, llm_base_url="http://mock/v1", llm_api_key="k", llm_model="m")
    condensed = "# Scene: Coffee habits\n\n## Current state\n- [persona|p80|abc] The user drinks tea (updated from: coffee)\n"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": condensed}}]})

    llm = LLMClient(cfg)
    llm._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    path = tmp_path / "coffee-habits.md"
    path.write_text("# Scene: Coffee habits\n" + "- [persona|p60|x] filler fact\n" * 200, encoding="utf-8")
    assert await maybe_condense_scene(path, llm, max_chars=1000)
    assert path.read_text(encoding="utf-8").startswith("# Scene: Coffee habits")
    assert "updated from: coffee" in path.read_text(encoding="utf-8")

    # small files are left alone; max_chars=0 disables
    small = tmp_path / "small.md"
    small.write_text("# Scene: tiny\n- fact\n", encoding="utf-8")
    assert not await maybe_condense_scene(small, llm, max_chars=1000)
    assert not await maybe_condense_scene(path, llm, max_chars=0)
    await llm.close()
