"""Async client for any OpenAI-compatible embeddings endpoint.
When unconfigured, the system degrades gracefully to keyword-only search."""
from __future__ import annotations

import logging
from pathlib import Path

import httpx

from .config import Settings
from .llm_cache import LLMCache

log = logging.getLogger("zanii_memory.embedding")


class EmbeddingClient:
    def __init__(self, cfg: Settings):
        self.base_url = cfg.resolved_embedding_base_url.rstrip("/")
        self.api_key = cfg.resolved_embedding_api_key
        self.model = cfg.embedding_model
        self.dimensions = cfg.embedding_dimensions
        self.enabled = cfg.embedding_enabled
        self._client: httpx.AsyncClient | None = None
        self.cache = LLMCache(Path(cfg.llm_cache_path)) if cfg.llm_cache_path else None

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            headers = {"Content-Type": "application/json"}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"
            self._client = httpx.AsyncClient(headers=headers)
        return self._client

    async def embed(self, texts: list[str], timeout: float = 30.0) -> list[list[float]]:
        if not self.enabled:
            raise RuntimeError("Embeddings are not configured (set ZANII_EMBEDDING_MODEL)")
        cache_key = None
        if self.cache is not None:
            cache_key = self.cache.key_for("embed", self.model, {"input": texts})
            cached = self.cache.get(cache_key)
            if cached is not None:
                return cached
        payload = {"model": self.model, "input": texts}
        resp = await self._http().post(f"{self.base_url}/embeddings", json=payload, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()["data"]
        # API may return out of order; sort by index.
        data.sort(key=lambda d: d.get("index", 0))
        vectors = [d["embedding"] for d in data]
        if self.cache is not None and cache_key is not None:
            self.cache.put(cache_key, "embed", vectors)
        return vectors

    async def embed_one(self, text: str, timeout: float = 30.0) -> list[float]:
        return (await self.embed([text], timeout=timeout))[0]

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
        if self.cache is not None:
            self.cache.close()
            self.cache = None
