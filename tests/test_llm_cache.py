import json

import httpx

from zanii_memory.config import Settings
from zanii_memory.embedding import EmbeddingClient
from zanii_memory.llm import LLMClient


def make_cfg(tmp_path) -> Settings:
    return Settings(
        _env_file=None,
        llm_base_url="http://mock/v1",
        llm_api_key="k",
        llm_model="m",
        embedding_base_url="http://mock/v1",
        embedding_model="e",
        llm_cache_path=str(tmp_path / "cache.sqlite"),
    )


async def test_chat_cache_replays_identical_requests_free(tmp_path):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "answer"}}]})

    cfg = make_cfg(tmp_path)
    llm = LLMClient(cfg)
    llm._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    assert await llm.complete("q1") == "answer"
    assert await llm.complete("q1") == "answer"  # identical -> cache hit, no API call
    assert await llm.complete("q2") == "answer"  # different prompt -> miss
    assert len(calls) == 2
    assert llm.cache.hits == 1 and llm.cache.misses == 2
    await llm.close()

    # cache persists across client instances (i.e. across benchmark runs)
    llm2 = LLMClient(cfg)
    llm2._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    assert await llm2.complete("q1") == "answer"
    assert len(calls) == 2  # served from disk, still no new API call
    await llm2.close()


async def test_embedding_cache(tmp_path):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(200, json={"data": [{"index": 0, "embedding": [0.1, 0.2]}]})

    cfg = make_cfg(tmp_path)
    emb = EmbeddingClient(cfg)
    emb._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    assert await emb.embed(["hello"]) == [[0.1, 0.2]]
    assert await emb.embed(["hello"]) == [[0.1, 0.2]]
    assert len(calls) == 1
    await emb.close()


async def test_cache_off_by_default(tmp_path):
    cfg = Settings(_env_file=None, llm_base_url="http://mock/v1", llm_api_key="k", llm_model="m")
    llm = LLMClient(cfg)
    assert llm.cache is None
    await llm.close()
