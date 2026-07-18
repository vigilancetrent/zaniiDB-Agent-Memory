import json

import httpx

from zanii_memory.config import Settings
from zanii_memory.llm import LLMClient


def make_client(handler) -> LLMClient:
    cfg = Settings(_env_file=None, llm_base_url="http://mock/v1", llm_api_key="k", llm_model="gpt-x")
    client = LLMClient(cfg)
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return client


async def test_token_param_renegotiation():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        calls.append(body)
        if "max_tokens" in body:
            return httpx.Response(
                400,
                json={"error": {"message": "Unsupported parameter: 'max_tokens' is not supported"
                                           " with this model. Use 'max_completion_tokens' instead."}},
            )
        assert "max_completion_tokens" in body
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    client = make_client(handler)
    assert await client.complete("hi") == "ok"
    assert "max_tokens" in calls[0] and "max_completion_tokens" in calls[1]
    # negotiated param is cached: second call goes straight to max_completion_tokens
    assert await client.complete("again") == "ok"
    assert "max_completion_tokens" in calls[2] and len(calls) == 3
    await client.close()


async def test_legacy_servers_keep_max_tokens():
    def handler(request: httpx.Request) -> httpx.Response:
        assert "max_tokens" in json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    client = make_client(handler)
    assert await client.complete("hi") == "ok"
    await client.close()
