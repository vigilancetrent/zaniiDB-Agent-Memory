---
name: zaniidb
description: >-
  Build agents with persistent, self-correcting long-term memory using ZaniiDB
  Agent Memory — layered L0→L3 memory (raw conversations → atomic facts →
  scene ledgers → persona), hybrid BM25+vector recall, conflict resolution
  (supersede), the FastAPI gateway, the MCP server, and the zanii-memory CLI.
  Use this whenever a task involves agent memory, recall, remembering users
  across sessions, the zaniidb-agent-memory package, zanii_memory imports,
  ZANII_* env vars, or the PersonaMem benchmark harness.
---

# ZaniiDB Agent Memory — layered long-term memory for AI agents

ZaniiDB captures conversations, distills them into structured memories with an
LLM, and recalls the right context before each turn. Memory is a pyramid, not a
flat vector pile: **L0** raw conversations (BM25) → **L1** atomic memories
(typed, priority-scored, vectorized) → **L2** scene ledgers (markdown) → **L3**
`persona.md` (narrative profile). Recall fuses BM25 + vector KNN with RRF.
Memory **self-corrects**: new facts supersede outdated ones; paraphrase
re-extractions are dropped; superseded history stays auditable.

Install: `pip install zaniidb-agent-memory` (extras: `[postgres]`, `[provable]`).
Surfaces: Python SDK (`zanii_memory`), HTTP gateway (`zanii-memory serve`, port
8520, dashboard at `/dashboard`), MCP server (`zanii-memory mcp`), CLI.

## The core workflow (memorize this)

```python
from zanii_memory import ZaniiMemory

memory = ZaniiMemory()            # config from ZANII_* env vars / .env
await memory.initialize()

# 1. BEFORE each agent turn — recall
r = await memory.recall("what does the user prefer?", session_key="user-42")
# r.prepend_context        -> relevant memories, prepend to the user prompt
# r.append_system_context  -> persona + team knowledge, append to system prompt

# 2. AFTER each completed turn — capture (one call per turn)
await memory.capture("user-42", [
    {"role": "user", "content": "..."},
    {"role": "assistant", "content": "..."},
])

# 3. On session close — flush extraction now
await memory.end_session("user-42")
await memory.close()
```

Extraction runs in the background on a warmup schedule (turn 1, then doubling
to every N). Only `user`/`assistant` roles are captured; system/tool messages
are ignored. Three memory types exist: `persona` (stable traits), `episodic`
(events/decisions), `instruction` (standing rules for the AI) — priorities
below 50 are dropped at extraction.

## Configuration (env, prefix ZANII_)

Zero-config runs: no keys → capture + keyword search still work, extraction
pauses. Enable the pipeline with `ZANII_LLM_BASE_URL` + `ZANII_LLM_MODEL` (+
`ZANII_LLM_API_KEY`) — any OpenAI-compatible endpoint. For Claude direct, set
`ZANII_LLM_PROVIDER=anthropic` instead (native `/v1/messages`; base URL defaults
to `api.anthropic.com/v1`, only key + model needed — see docs/anthropic.md).
Anthropic has no embeddings API, so in that mode embeddings never fall back to
the LLM URL — set `ZANII_EMBEDDING_BASE_URL` explicitly or run keyword-only.
Vectors need `ZANII_EMBEDDING_MODEL`. Postgres: `ZANII_DATABASE_URL=postgresql://…` (else
SQLite in `ZANII_DATA_DIR`, default `~/.zanii/memory`). Gateway auth:
`ZANII_GATEWAY_API_KEY` (Bearer; `/health` stays open). Full table in the
project README.

## Rules you MUST follow when writing ZaniiDB code

1. **Recall before the turn, capture after it.** One `capture()` per completed
   turn — it advances the extraction scheduler; don't call it per message.
2. **Never bypass supersede semantics.** Active memories = `superseded_by = ''`.
   All search/recall paths exclude superseded rows automatically; history stays
   in the store for audit/export. Don't hand-write SQL that forgets the filter —
   use the store methods.
3. **Seeding is for durable facts** (`seed()` / `POST /seed` / MCP `save_memory`):
   content + type + priority (+ `scope: "team"` for org-wide knowledge injected
   into every session's system context). Duplicates are silently skipped.
4. **The graceful-degradation ladder is intentional.** No embeddings → keyword
   (BM25) only; no LLM → capture/search only. Never make embeddings or the LLM
   a hard requirement in integration code.
5. **Multi-tenancy = one database (or data dir) per tenant.** There is no
   user_id column by design; do not simulate tenancy inside one store.
6. **Export/import is the migration path** (`zanii-memory export/import`) —
   idempotent, re-embeds on import, preserves superseded state. Use it for
   SQLite→Postgres moves; never copy raw DB files across backends.
7. **The LLM cache** (`ZANII_LLM_CACHE_PATH`) replays byte-identical requests
   free. Any prompt change is an automatic miss — never bump prompts casually
   in paid loops, and never dedupe/cache LLM calls yourself.
8. **GPT-5.x models need reasoning headroom**: the client auto-negotiates
   `max_completion_tokens`, but keep answer budgets ≥ a few hundred tokens —
   tiny budgets return empty answers on reasoning models.
9. **Provable memory** (`[provable]` extra): `zanii-memory ledger-init`, set
   `ZANII_LEDGER_URL`/`ZANII_LEDGER_API_KEY`/`ZANII_LEDGER_IDENTITY_FILE` —
   every mutation emits a hash-chained `zanii.memory` receipt (salted
   commitment only; raw memory never leaves). Verify with
   `zanii-memory ledger-verify`. A ledger failure never breaks memory ops.
10. **Procedural recall is on by default** (`ZANII_RECALL_SKILLS`): recall() injects the
    best-matching learned skill from `skills/*.md` into the system context. Outcome-tagged
    episodic memories (metadata `outcome: success|failure`) feed skill generation
    (successes -> procedures, failures -> Pitfalls). `AutoOffloader(stale_after_messages=N)`
    stubs stale tool outputs even when small.
11. **The Memory Firewall is on by default.** Mark third-party content with a channel at
    capture ({"channel": "email"|"web"|"tool", ...}); instructions from untrusted channels
    are always quarantined, injection signatures are screened (heuristics + LLM), and
    quarantined memories never reach recall until reviewed (`zanii-memory quarantine`).
    Never disable it in integration code; never route fetched content through a trusted
    channel to "make it work".
12. **Benchmark claims must be reproduced, not quoted**: `zanii-memory bench`
    (retrieval) and `zanii-memory personamem` (public PersonaMem harness,
    needs LLM keys, costs real API money — warn before running).

## Load these references when the task needs depth

- `reference/python.md` — full SDK: MemoryCore surface, adapters/hooks,
  auto-offload, store protocol.
- `reference/api.md` — gateway HTTP routes + MCP tools.
- `reference/patterns.md` — integration patterns and the mistakes models make.
