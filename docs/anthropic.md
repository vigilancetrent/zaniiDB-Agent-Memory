# Using Claude (Anthropic) with ZaniiDB Agent Memory

ZaniiDB works with Claude two ways. Both power the LLM-driven pipeline
(extraction, persona, conflict resolution, the Memory Firewall screen) — the
choice is just how the request reaches Claude.

| Option | When to use | Config |
| :--- | :--- | :--- |
| **A. Native Claude API** | Direct Anthropic account, no gateway | `ZANII_LLM_PROVIDER=anthropic` |
| **B. OpenAI-compatible route** | Anthropic's compat layer, or a gateway (LiteLLM / OpenRouter / Vercel AI Gateway) already in your stack | default `ZANII_LLM_PROVIDER=openai` + a base URL |

## The one caveat: embeddings

**Anthropic has no embeddings API.** Claude powers the *LLM* half; the *vector*
half needs embeddings from elsewhere. ZaniiDB keeps the two independent
(`ZANII_EMBEDDING_*` is separate from `ZANII_LLM_*`), so pair Claude with either:

- **OpenAI embeddings** — `text-embedding-3-small` (1536 dims)
- **Local embeddings** — Ollama `nomic-embed-text` (768 dims), fully self-hosted, free
- **No embeddings at all** — omit them and run keyword-only (BM25) recall; capture,
  extraction, and search still work (graceful degradation).

In native Anthropic mode, embeddings never fall back to the Anthropic base URL —
you must set `ZANII_EMBEDDING_BASE_URL` explicitly (or leave embeddings off).

---

## Option A — Native Claude API (`/v1/messages`)

```bash
# LLM: Claude, direct
ZANII_LLM_PROVIDER=anthropic
ZANII_LLM_API_KEY=sk-ant-...
ZANII_LLM_MODEL=claude-opus-4-8        # or claude-sonnet-5, claude-haiku-4-5, ...
# ZANII_LLM_BASE_URL defaults to https://api.anthropic.com/v1 — override only for a proxy
# ZANII_ANTHROPIC_VERSION=2023-06-01   # override the anthropic-version header if needed

# Embeddings: from OpenAI (Claude has none)
ZANII_EMBEDDING_BASE_URL=https://api.openai.com/v1
ZANII_EMBEDDING_API_KEY=sk-...
ZANII_EMBEDDING_MODEL=text-embedding-3-small
```

The client sends `x-api-key` + `anthropic-version` headers, puts the system
prompt in the top-level `system` field, the content in `messages`, and reads the
response's content blocks — no gateway, no shim.

### Fully self-hosted embeddings (no OpenAI at all)

```bash
ZANII_LLM_PROVIDER=anthropic
ZANII_LLM_API_KEY=sk-ant-...
ZANII_LLM_MODEL=claude-opus-4-8
ZANII_EMBEDDING_BASE_URL=http://localhost:11434/v1   # Ollama
ZANII_EMBEDDING_API_KEY=ollama
ZANII_EMBEDDING_MODEL=nomic-embed-text
ZANII_EMBEDDING_DIMENSIONS=768                        # nomic-embed-text is 768-dim
```

---

## Option B — Claude via an OpenAI-compatible endpoint

Leave the default provider (`openai`) and point the base URL at any
`/chat/completions` endpoint that serves Claude. No code change; the client's
`max_tokens` ↔ `max_completion_tokens` negotiation handles parameter differences.

**Anthropic's OpenAI-compatibility endpoint:**

```bash
ZANII_LLM_BASE_URL=https://api.anthropic.com/v1   # Anthropic's OpenAI-compat layer
ZANII_LLM_API_KEY=sk-ant-...
ZANII_LLM_MODEL=claude-opus-4-8
```

**A gateway (LiteLLM / OpenRouter / Vercel AI Gateway):**

```bash
ZANII_LLM_BASE_URL=https://your-gateway/v1
ZANII_LLM_API_KEY=<gateway key>
ZANII_LLM_MODEL=anthropic/claude-opus-4-8   # gateway's model-string convention
```

Add the same embeddings block as Option A — a gateway that also proxies
embeddings can serve both from one base URL.

---

## Model notes

- Use current Claude model IDs (e.g. `claude-opus-4-8`, `claude-sonnet-5`,
  `claude-haiku-4-5`). `claude-haiku-4-5` is the cheapest and a good default for
  high-volume extraction; larger models improve persona and firewall-screen quality.
- The **provenance guard** applies in both modes: ZaniiDB logs a warning if the
  endpoint reports serving a different model than requested — you always know what
  actually answered.
- Verify a setup end-to-end with `zanii-memory bench` (retrieval quality) once
  keys are in place.
