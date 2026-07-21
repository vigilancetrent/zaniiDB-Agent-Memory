"""Async LLM client — OpenAI-compatible /chat/completions by default, with an
optional native Anthropic Messages (/v1/messages) mode (ZANII_LLM_PROVIDER=anthropic)."""
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
        self.provider = cfg.llm_provider
        self.base_url = cfg.resolved_llm_base_url.rstrip("/")
        self.api_key = cfg.llm_api_key
        self.model = cfg.llm_model
        self.enabled = cfg.llm_enabled
        self.timeout_override = cfg.llm_timeout_s
        self.anthropic_version = cfg.anthropic_version
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
            self._client = httpx.AsyncClient()
        return self._client

    def _headers(self) -> dict[str, str]:
        # Per-request so injected transports (tests) still get auth headers.
        headers = {"Content-Type": "application/json"}
        if self.provider == "anthropic":
            if self.api_key:
                headers["x-api-key"] = self.api_key
            headers["anthropic-version"] = self.anthropic_version
        elif self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _check_provenance(self, served: str) -> None:
        if not served:
            return
        self.served_model = served
        if not served.startswith(self.model.split(":")[0]) and not self._warned_served_mismatch:
            log.warning(
                "PROVENANCE: requested model %r but endpoint reports serving %r — "
                "results belong to the served model", self.model, served,
            )
            self._warned_served_mismatch = True

    async def complete(
        self,
        prompt: str,
        system: str | None = None,
        timeout: float = 120.0,
        max_tokens: int = 4096,
    ) -> str:
        if not self.enabled:
            raise RuntimeError("LLM is not configured (set ZANII_LLM_MODEL and a key/base URL)")
        if self.timeout_override > 0:
            timeout = self.timeout_override

        cache_key = None
        if self.cache is not None:
            if self.provider == "anthropic":
                payload = {"anthropic": True, "system": system, "prompt": prompt, "max_tokens": max_tokens}
            else:
                # Byte-identical to the pre-provider key so existing caches still hit.
                messages = ([{"role": "system", "content": system}] if system else []) + [
                    {"role": "user", "content": prompt}
                ]
                payload = {"messages": messages, "max_tokens": max_tokens}
            cache_key = self.cache.key_for("chat", self.model, payload)
            cached = self.cache.get(cache_key)
            if cached is not None:
                return cached

        if self.provider == "anthropic":
            content = await self._complete_anthropic(prompt, system, timeout, max_tokens)
        else:
            content = await self._complete_openai(prompt, system, timeout, max_tokens)
        if self.cache is not None and cache_key is not None:
            self.cache.put(cache_key, "chat", content)
        return content

    async def _complete_openai(self, prompt, system, timeout, max_tokens) -> str:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        token_param = self._token_param or "max_tokens"
        last_err: Exception | None = None
        for attempt in range(3):  # allows one param renegotiation + one transient retry
            payload = {"model": self.model, "messages": messages, token_param: max_tokens}
            try:
                resp = await self._http().post(
                    f"{self.base_url}/chat/completions", json=payload, headers=self._headers(), timeout=timeout
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
                self._check_provenance(str(data.get("model") or ""))
                return data["choices"][0]["message"]["content"] or ""
            except (httpx.HTTPError, KeyError, IndexError) as err:
                last_err = err
                # repr(): timeouts like httpx.ReadTimeout stringify to ''
                log.warning("LLM call failed (attempt %d/3): %r", attempt + 1, err)
                await asyncio.sleep(2.0 * (attempt + 1))
        raise RuntimeError(f"LLM call failed after retry: {last_err!r}")

    async def _complete_anthropic(self, prompt, system, timeout, max_tokens) -> str:
        """Native Claude Messages API: system is top-level, user goes in messages,
        the response is a list of content blocks (concatenate the text ones)."""
        payload: dict = {
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system:
            payload["system"] = system

        last_err: Exception | None = None
        for attempt in range(3):
            try:
                resp = await self._http().post(f"{self.base_url}/messages", json=payload, headers=self._headers(), timeout=timeout)
                resp.raise_for_status()
                data = resp.json()
                self._check_provenance(str(data.get("model") or ""))
                blocks = data.get("content") or []
                return "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
            except (httpx.HTTPError, KeyError, IndexError) as err:
                last_err = err
                log.warning("Anthropic LLM call failed (attempt %d/3): %r", attempt + 1, err)
                await asyncio.sleep(2.0 * (attempt + 1))
        raise RuntimeError(f"Anthropic LLM call failed after retry: {last_err!r}")

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
        if self.cache is not None:
            if self.cache.hits or self.cache.misses:
                log.info("LLM cache: %d hits (free), %d misses (paid)", self.cache.hits, self.cache.misses)
            self.cache.close()
            self.cache = None
