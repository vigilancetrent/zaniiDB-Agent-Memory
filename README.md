# ZaniiDB Agent Memory

<p align="center">
  <img src="assets/hero.png" alt="ZaniiDB Agent Memory — layered long-term memory for AI agents" width="920" />
</p>

<p align="center">
  <img src="assets/demo.gif" alt="ZaniiDB Agent Memory demo: install, serve, capture, search, benchmark" width="760" />
</p>

**Layered long-term memory for AI agents.** Agents remember; humans stop repeating themselves.

ZaniiDB Agent Memory captures conversations, distills them into structured memories with an LLM, and recalls the right context before each turn — as a Python SDK, an HTTP gateway, or a CLI.

## Architecture: the memory pyramid

Memory is never flat. Both formation and recall are hierarchical:

| Layer | What | Where |
| :--- | :--- | :--- |
| **L3 Persona** | Narrative user profile (archetype, preferences, interaction protocol) | `persona.md` — human-readable |
| **L2 Scenes** | Scene blocks grouping related facts | `scenes/*.md` — human-readable |
| **L1 Atoms** | Atomic memories: `persona` / `episodic` / `instruction`, priority-scored | SQLite (+ vectors) |
| **L0 Conversations** | Raw captured turns | SQLite, BM25-searchable |

- **Hybrid recall**: FTS5 BM25 + sqlite-vec cosine KNN, fused with Reciprocal Rank Fusion.
- **Self-correcting memory**: new facts supersede outdated ones (LLM conflict resolution with a same-type guard); paraphrase re-extractions are dropped, not hoarded. Superseded history stays auditable via `superseded_by`.
- **Scene synthesis**: oversized scene ledgers are LLM-condensed into resolved current-state narratives ("newest wins", update history preserved).
- **Provenance guard**: the client records which model the endpoint *reports serving* and warns on mismatch — benchmark and production results can't be silently mislabeled.
- **White-box**: the top layers are plain markdown files — open them and read what the agent knows.
- **Graceful degradation**: no embedding key → keyword-only search; no LLM key → capture and search still work, extraction pauses.
- **Zero infra**: one SQLite file. No servers required to start.

## Install

```bash
pip install -e .              # SQLite backend (default)
pip install -e ".[postgres]"  # + PostgreSQL/pgvector backend
```

Requires Python 3.11+.

## Storage backends

**SQLite (default)** — zero config, one file, ideal for local agents and single-user deployments.

**PostgreSQL + pgvector** — for production/server deployments:

```bash
export ZANII_DATABASE_URL="postgresql://user:pass@host:5432/dbname"
```

The store creates its schema (and the `vector` extension) on first start. If pgvector isn't available on the server, it degrades to keyword-only search — same contract as SQLite. Works with Neon, Supabase, RDS, or any Postgres 14+.

**Multi-tenancy**: run one database (or one `ZANII_DATA_DIR`) per tenant — hard isolation, no cross-tenant leak surface, and per-tenant export/deletion for free. Point each gateway/MCP instance at its tenant's database.

**Migration between backends** is export/import:

```bash
zanii-memory export backup.json                          # from the current backend
ZANII_DATABASE_URL=postgresql://... zanii-memory import backup.json   # into Postgres
```

## Configuration (environment variables)

Everything has a default; the system runs with zero configuration. Set `ZANII_LLM_*` to enable memory extraction.

| Variable | Default | Description |
| :--- | :--- | :--- |
| `ZANII_DATA_DIR` | `~/.zanii/memory` | Data directory (db, scenes, persona, refs, canvas) |
| `ZANII_DATABASE_URL` | — | `postgresql://...` selects the Postgres backend; empty = SQLite |
| `ZANII_LLM_BASE_URL` | — | OpenAI-compatible endpoint, e.g. `https://api.openai.com/v1` |
| `ZANII_LLM_API_KEY` | — | API key |
| `ZANII_LLM_MODEL` | — | Model name, e.g. `gpt-4o-mini` |
| `ZANII_EMBEDDING_BASE_URL` | LLM base URL | Embeddings endpoint (falls back to LLM endpoint) |
| `ZANII_EMBEDDING_API_KEY` | LLM key | Embeddings key |
| `ZANII_EMBEDDING_MODEL` | — | e.g. `text-embedding-3-small` |
| `ZANII_EMBEDDING_DIMENSIONS` | `1536` | Vector dimensions |
| `ZANII_RECALL_STRATEGY` | `hybrid` | `keyword` / `embedding` / `hybrid` |
| `ZANII_RECALL_MAX_RESULTS` | `5` | Memories injected per recall |
| `ZANII_RECALL_MAX_TOTAL_CHARS` | `4000` | Char budget for recalled memories |
| `ZANII_PIPELINE_EVERY_N_TURNS` | `5` | Extract memories every N turns |
| `ZANII_PIPELINE_WARMUP` | `true` | New sessions extract at turn 1, doubling up to N |
| `ZANII_PIPELINE_IDLE_TIMEOUT_S` | `600` | Flush pending turns after idle |
| `ZANII_PIPELINE_PERSONA_EVERY_N` | `50` | Regenerate persona every N new memories |
| `ZANII_PIPELINE_SKILLS` | `true` | Distill skill/SOP docs after each persona regeneration |
| `ZANII_FTS_TOKENIZER` | `unicode61` | SQLite FTS tokenizer: `unicode61` / `trigram` (CJK) |
| `ZANII_PG_TEXT_SEARCH_CONFIG` | `simple` | Postgres text-search config name |
| `ZANII_DEDUP_MAX_DISTANCE` | `0.08` | Cosine distance for near-duplicate consolidation |
| `ZANII_RETENTION_EPISODIC_DAYS` | `0` | Episodic memory retention (0 = forever) |
| `ZANII_RETENTION_KEEP_PRIORITY` | `90` | Episodic memories at/above this priority never decay |
| `ZANII_AUDIT_ENABLED` | `false` | Record every memory operation to the audit log |
| `ZANII_LLM_CACHE_PATH` | — | Exact-request LLM/embedding response cache (SQLite); identical requests replay free. The benchmark enables it automatically |
| `ZANII_GATEWAY_HOST` / `_PORT` | `127.0.0.1:8520` | Gateway bind |
| `ZANII_GATEWAY_API_KEY` | — | When set, all routes except `/health` require `Authorization: Bearer <key>` |
| `ZANII_CORS_ORIGINS` | — | Comma-separated CORS allow-list (empty = none) |

A `.env` file in the working directory is also read.

## SDK

```python
import asyncio
from zanii_memory import ZaniiMemory

async def main():
    memory = ZaniiMemory()  # config from ZANII_* env vars
    await memory.initialize()

    # Before each agent turn: recall relevant context
    recall = await memory.recall("what stack does the user prefer?", session_key="s1")
    print(recall.prepend_context)        # relevant memories -> prepend to the user prompt
    print(recall.append_system_context)  # persona -> append to the system prompt

    # After each completed turn: capture it
    await memory.capture("s1", [
        {"role": "user", "content": "From now on always answer in French."},
        {"role": "assistant", "content": "Bien sûr!"},
    ])

    # On session end: flush extraction immediately
    await memory.end_session("s1")
    await memory.close()

asyncio.run(main())
```

## HTTP gateway

```bash
zanii-memory serve            # http://127.0.0.1:8520 — OpenAPI docs at /docs
```

| Route | Body |
| :--- | :--- |
| `GET /health` | — (always open, no auth) |
| `POST /recall` | `{"query", "session_key"}` |
| `POST /capture` | `{"session_key", "messages": [{"role", "content", "timestamp?"}], "session_id?"}` |
| `POST /search/memories` | `{"query", "limit?", "type?"}` |
| `POST /search/conversations` | `{"query", "limit?", "session_key?"}` |
| `POST /session/end` | `{"session_key"}` |
| `POST /seed` | `{"memories": [{"content", "type?", "priority?"}]}` |
| `POST /offload` | `{"session_key", "content", "label?"}` |
| `GET /offload/{node_id}` | — |
| `GET /canvas/{session_key}` | — |
| `POST /export` | — |
| `POST /import` | an `export` snapshot |

```bash
curl -X POST http://127.0.0.1:8520/recall \
  -H "Content-Type: application/json" \
  -d '{"query": "user preferences", "session_key": "s1"}'
```

## MCP server

Give any MCP-capable agent (Claude Code, IDE agents, custom clients) direct access to the user's memory:

```bash
# Claude Code
claude mcp add zanii-memory -- zanii-memory mcp
```

Or in a generic MCP client config:

```json
{
  "mcpServers": {
    "zanii-memory": {
      "command": "zanii-memory",
      "args": ["mcp"],
      "env": { "ZANII_DATA_DIR": "~/.zanii/memory" }
    }
  }
}
```

| Tool | Purpose |
| :--- | :--- |
| `memory_search` | Hybrid search over long-term memories (optional `type` filter) |
| `conversation_search` | Keyword search over raw captured conversations |
| `save_memory` | Store a durable fact / instruction directly |
| `get_persona` | The user's narrative persona profile |

The server runs over stdio and shares the same `ZANII_*` configuration and data directory as the SDK and gateway — memories are shared across all three surfaces.

## Observability dashboard

<p align="center"><img src="assets/dashboard-light.png" alt="ZaniiDB dashboard: stat tiles, memory search, type-chipped memories, audit trail, persona" width="860" /></p>

`zanii-memory serve`, then open **http://127.0.0.1:8520/dashboard** — live stats, memory search, recent memories, persona, scenes, skills, and the audit trail on one page. When `ZANII_GATEWAY_API_KEY` is set, append `?token=<key>`.

## Benchmark

Measure retrieval quality of your exact configuration (backend, tokenizer, keyword vs hybrid) on a built-in eval of 20 queries against seeded facts + distractors:

```bash
zanii-memory bench
```

Measured results (SQLite backend):

| Mode | recall@1 | recall@5 | MRR |
| :--- | :---: | :---: | :---: |
| keyword only (zero config) | 80% | 95% | 0.867 |
| hybrid (OpenAI `text-embedding-3-small`) | **100%** | **100%** | **1.000** |

Uses a throwaway data dir — never touches real memory.

### Public benchmark: PersonaMem

`zanii-memory personamem` runs the [PersonaMem](https://github.com/bowen-upenn/PersonaMem) (COLM 2025) benchmark against the live product — multi-session conversations with evolving personas, 4-way multiple-choice questions about the user's *current* profile. Our protocol is **stricter than the official full-context eval**: the dataset's ground-truth persona system messages are excluded (memory is built from dialogue alone), and questions are answered from a few hundred tokens of *recalled memory* instead of the full 32k context.

```bash
zanii-memory personamem --contexts 1 --max-questions 15 --baseline
```

`--baseline` also scores a no-memory control to show the uplift. Scale up with `--contexts` / `--max-questions` / `--size 128k` (LLM cost scales with ingested contexts).

Measured (gpt-4o, seven independent 150-question runs, 2026-07-18; recommended configuration = `--scenes`, which adds the L2 chronological fact ledger to the answering context):

| Setup | Accuracy |
| :--- | :---: |
| No memory (control), pooled n=750 | 43.1% |
| Frontier models with the FULL 32k context (paper) | ~52% |
| ZaniiDB memory, all runs pooled n=1050 | **55.2%** |
| — recommended config (`--scenes`), pooled n=600 | 56.2% (best single run 61.3%) |

On `gpt-5.6-luna` with v0.5.x (conflict resolution + scene synthesis): **58.0–58.7%** across two runs, with record per-type results (preference-aligned recommendations 9/9, reasons-behind-updates 82–93% on every run across both models).

A robust, many-times-replicated **+12–16-point uplift** over the no-memory control, matching or exceeding frontier full-context reading from ~100× less context per answer. Run-to-run variance on this eval is ±4pp — we report pooled numbers and label the 61.3% for what it is: the best single run, not the expected value. Every number here is reproducible with:

```bash
zanii-memory personamem --contexts 12 --max-questions 150 --baseline --scenes
```

## Agent integration

**Hooks for any framework** (LangGraph, CrewAI, Pydantic-AI, OpenAI Agents — recipes in `adapters.py`):

```python
from zanii_memory.adapters import AgentMemoryHooks

hooks = AgentMemoryHooks(memory, session_key="user-42")
injection = await hooks.before_turn(user_text)          # memories + persona
messages = hooks.inject(messages, injection)            # OpenAI-style message list
...
await hooks.after_turn(user_text, assistant_text)       # capture the turn
```

**Automatic context offload** — stubs out oversized tool outputs transparently:

```python
from zanii_memory.autooffload import AutoOffloader

auto = AutoOffloader(memory, "task-1", threshold_chars=4000)
messages = await auto.filter_messages(messages)   # before each LLM call
```

## Temporal search

`search_memories` (SDK/gateway/MCP) accepts `since`/`until` bounds — "what did the user decide last week?":

```bash
curl -X POST .../search/memories -d '{"query": "deploy decision", "since": "2026-07-10"}'
```

## Team memory

Memories with `scope: "team"` are shared org knowledge — injected into every session's system context alongside the persona:

```bash
zanii-memory seed team_sops.json   # entries: {"content": ..., "scope": "team"}
```

The MCP `save_memory` tool takes the same `scope` parameter.

## Skills (SOPs distilled from memory)

The pipeline distills recurring task patterns from episodic + instruction memories into reusable procedure docs in `skills/*.md` — automatically after each persona regeneration, or on demand with `zanii-memory skills`. Disable auto mode with `ZANII_PIPELINE_SKILLS=false`.

## Consolidation & retention

`zanii-memory consolidate` (also `POST /consolidate`, and automatic each persona cycle):

- merges semantically near-duplicate memories (vector distance ≤ `ZANII_DEDUP_MAX_DISTANCE`, higher priority wins)
- deletes episodic memories older than `ZANII_RETENTION_EPISODIC_DAYS` (default 0 = keep forever) unless priority ≥ `ZANII_RETENTION_KEEP_PRIORITY` — persona and instruction memories never decay

## Provable memory (Zanii ledger)

ZaniiDB is the memory *engine*; [Zanii](https://ledger.zanii.agency) is the proof-of-action *ledger*. With the `[provable]` extra, every memory mutation (extract, seed, supersede, persona update) emits a hash-chained `zanii.memory` receipt to an append-only, Merkle-verified transparency log — a tamper-evident record of **what your agent remembered and when**, verifiable offline by anyone. Only a salted content commitment leaves the machine; raw memories never do.

```bash
pip install "zaniidb-agent-memory[provable]"
zanii-memory ledger-init                    # identity + scoped delegation (memory.*)
export ZANII_LEDGER_URL=https://ledger.zanii.agency
export ZANII_LEDGER_API_KEY=zk_live_...
# ... use memory normally; then, any time:
zanii-memory ledger-verify                  # offline tamper check of the whole chain
```

A ledger outage never breaks memory operations. Combined with `superseded_by` history, this answers "why did the agent believe X, and when did that change?" with cryptographic evidence.

## Agent Skill

`skills/zaniidb/` is a portable Agent Skill that makes any coding assistant (Claude Code, Codex, ...) a ZaniiDB expert — mental model, real signatures, and the rules. `cp -r skills/zaniidb ~/.claude/skills/` and your agent stops needing ZaniiDB explained every session.

## Security & compliance

- **Audit log**: `ZANII_AUDIT_ENABLED=true` records every capture/recall/search/seed/consolidate with timestamps — `zanii-memory audit` or `GET /audit`.
- **Encryption at rest**: delegate to the storage layer — full-disk encryption for the SQLite file, or Postgres-native options (cloud-provider TDE, encrypted volumes, `pgcrypto`). The app layer stays encryption-agnostic by design.
- **Right to erasure**: per-tenant database + `export`/delete covers GDPR data portability and deletion.

## Multilingual / CJK search

- SQLite: `ZANII_FTS_TOKENIZER=trigram` enables CJK-friendly matching. Queries shorter than 3 contiguous characters (e.g. 2-char Chinese words) automatically fall back to a substring scan, so nothing is unfindable. Applies at database creation.
- Postgres: `ZANII_PG_TEXT_SEARCH_CONFIG` selects the text-search config (`simple`, `english`, or a custom CJK config like zhparser).
- Hybrid mode with embeddings is language-agnostic and the best option for multilingual corpora.

## Context offload (short-term memory)

In long tasks, verbose tool outputs are the biggest token drain. Offload them and keep only a compact stub + a symbolic task canvas in context:

```python
result = await memory.offload("task-1", huge_tool_output, label="build logs")
# result["stub"]  -> '[offloaded:N1a2b3c4d] build logs'   (keep this in context)
full = await memory.retrieve_ref(result["node_id"])       # drill down on demand
print(await memory.get_canvas("task-1"))                  # Mermaid graph of task steps
```

The canvas is a Mermaid graph (`canvas/<session>.mmd`) where each node is an offloaded step — the agent reasons over the symbol graph and retrieves raw text by `node_id` only when needed. Gateway routes: `POST /offload`, `GET /offload/{node_id}`, `GET /canvas/{session_key}`. All artifacts are plain files under the data directory: `refs/*.md` and `canvas/*.mmd`.

## Export / import

Portable, idempotent memory snapshots — backup, migration, and cross-device sync:

```bash
zanii-memory export backup.json     # memories + conversations + persona + scenes
zanii-memory import backup.json     # skips entries that already exist
```

Also available as `POST /export` / `POST /import` on the gateway and `export_memory()` / `import_memory()` in the SDK. Imports re-embed memories when embeddings are enabled, so vectors survive backend or model changes.

## CLI

```bash
zanii-memory serve                  # run the gateway
zanii-memory mcp                    # run the MCP server (stdio)
zanii-memory seed facts.json        # bulk-insert memories (JSON array)
zanii-memory search "coffee"        # search L1 memories
zanii-memory search -c "kafka"      # search raw conversations
zanii-memory export backup.json     # portable memory snapshot
zanii-memory import backup.json     # idempotent restore / migration
zanii-memory inspect                # stats + persona
```

## Development

```bash
pip install -e ".[dev]"
pytest
```

## Roadmap

- [x] L0→L3 layered memory, hybrid RRF recall, gateway, CLI
- [x] MCP server (`memory_search`, `conversation_search`, `save_memory`, `get_persona`)
- [x] Postgres + pgvector backend behind the store interface
- [x] Short-term context offload (symbolic Mermaid task canvas) + automatic offload middleware
- [x] Memory export / import / migration (idempotent, re-embedding)
- [x] Multi-tenancy via database-per-tenant isolation
- [x] Retrieval benchmark harness (`zanii-memory bench`)
- [x] Observability dashboard (`/dashboard`)
- [x] Framework-agnostic agent hooks (`adapters.py`)
- [x] Consolidation (near-duplicate merge) + retention decay
- [x] Temporal search (`since`/`until`)
- [x] Skill/SOP generation from memories
- [x] Team memory scope (shared org knowledge)
- [x] CJK tokenizer options, audit log, encryption guidance

MIT © Zanii
