"""Async client for any OpenAI-compatible chat completions endpoint."""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import httpx

from .config import Settings
from .llm_cache import LLMCache

log = logging.getLogger("zanii_memory.llm")


class LLMClient:
    def __init__(self, cfg: Settings):
        self.base_url = cfg.llm_base_url.rstrip("/")
        self.api_key = cfg.llm_api_key
        self.model = cfg.llm_model
        self.enabled = cfg.llm_enabled
        self._client: httpx.AsyncClient | None = None
        self.cache = LLMCache(Path(cfg.llm_cache_path)) if cfg.llm_cache_path else None
        # Older models + OSS servers use "max_tokens"; GPT-5.x/o-series require
        # "max_completion_tokens". Negotiated on first call, then cached.
        self._token_param: str | None = None
        # Provenance: the model name the endpoint REPORTS serving (may differ from
        # the requested one behind redirects/routers). Warned once on mismatch.
        self.served_model: str | None = None
        self._warned_served_mismatch = False

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            headers = {"Content-Type": "application/json"}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"
            self._client = httpx.AsyncClient(headers=headers)
        return self._client

    async def complete(
        self,
        prompt: str,
        system: str | None = None,
        timeout: float = 120.0,
        max_tokens: int = 4096,
    ) -> str:
        if not self.enabled:
            raise RuntimeError("LLM is not configured (set ZANII_LLM_BASE_URL and ZANII_LLM_MODEL)")
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        cache_key = None
        if self.cache is not None:
            cache_key = self.cache.key_for("chat", self.model, {"messages": messages, "max_tokens": max_tokens})
            cached = self.cache.get(cache_key)
            if cached is not None:
                return cached

        token_param = self._token_param or "max_tokens"
        last_err: Exception | None = None
        for attempt in range(3):  # allows one param renegotiation + one transient retry
            payload = {"model": self.model, "messages": messages, token_param: max_tokens}
            try:
                resp = await self._http().post(
                    f"{self.base_url}/chat/completions", json=payload, timeout=timeout
                )
                if (
                    resp.status_code == 400
                    and token_param == "max_tokens"
                    and "max_completion_tokens" in resp.text
                ):
                    log.info("Model %s requires max_completion_tokens; switching", self.model)
                    token_param = "max_completion_tokens"
                    continue
                resp.raise_for_status()
                self._token_param = token_param
                data = resp.json()
                served = str(data.get("model") or "")
                if served:
                    self.served_model = served
                    if not served.startswith(self.model.split(":")[0]) and not self._warned_served_mismatch:
                        log.warning(
                            "PROVENANCE: requested model %r but endpoint reports serving %r — "
                            "results belong to the served model", self.model, served,
                        )
                        self._warned_served_mismatch = True
                content = data["choices"][0]["message"]["content"] or ""
                if self.cache is not None and cache_key is not None:
                    self.cache.put(cache_key, "chat", content)
                return content
            except (httpx.HTTPError, KeyError, IndexError) as err:
                last_err = err
                # repr(): timeouts like httpx.ReadTimeout stringify to ''
                log.warning("LLM call failed (attempt %d/3): %r", attempt + 1, err)
                await asyncio.sleep(2.0 * (attempt + 1))
        raise RuntimeError(f"LLM call failed after retry: {last_err!r}")

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
        if self.cache is not None:
            if self.cache.hits or self.cache.misses:
                log.info("LLM cache: %d hits (free), %d misses (paid)", self.cache.hits, self.cache.misses)
            self.cache.close()
            self.cache = None
