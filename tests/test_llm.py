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


async def test_native_anthropic_mode():
    """Native /v1/messages: system top-level, user in messages, content blocks out,
    x-api-key + anthropic-version headers, max_tokens (never max_completion_tokens)."""
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["headers"] = dict(request.headers)
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={
            "model": "claude-opus-4-8",
            "content": [{"type": "text", "text": "hello "}, {"type": "text", "text": "world"}],
            "stop_reason": "end_turn",
        })

    cfg = Settings(_env_file=None, llm_provider="anthropic", llm_api_key="sk-ant-xyz",
                   llm_model="claude-opus-4-8")
    assert cfg.llm_enabled  # native mode needs only key + model
    assert cfg.resolved_llm_base_url == "https://api.anthropic.com/v1"
    client = LLMClient(cfg)
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    out = await client.complete("Extract facts", system="You are a memory extractor.", max_tokens=1000)
    assert out == "hello world"                                   # text blocks concatenated
    assert seen["url"].endswith("/v1/messages")                   # native endpoint
    assert seen["headers"]["x-api-key"] == "sk-ant-xyz"           # Anthropic auth
    assert seen["headers"]["anthropic-version"] == "2023-06-01"
    assert "authorization" not in seen["headers"]                 # no Bearer in native mode
    assert seen["body"]["system"] == "You are a memory extractor."  # system is top-level
    assert seen["body"]["messages"] == [{"role": "user", "content": "Extract facts"}]
    assert seen["body"]["max_tokens"] == 1000
    assert client.served_model == "claude-opus-4-8"
    await client.close()


def test_anthropic_config_does_not_borrow_llm_base_for_embeddings():
    # Anthropic has no embeddings API — embeddings must not fall back to the LLM URL
    cfg = Settings(_env_file=None, llm_provider="anthropic", llm_api_key="k", llm_model="claude-opus-4-8")
    assert cfg.resolved_embedding_base_url == ""
    assert not cfg.embedding_enabled
