# ZaniiDB — gateway HTTP API & MCP tools

Gateway: `zanii-memory serve` → `http://127.0.0.1:8520` (OpenAPI at `/docs`,
dashboard at `/dashboard`). When `ZANII_GATEWAY_API_KEY` is set, every route
except `GET /health` requires `Authorization: Bearer <key>` (the dashboard also
accepts `?token=<key>`).

| Route | Body / notes |
|---|---|
| `GET /health` | always open; status, version, counts, capability flags |
| `POST /recall` | `{"query", "session_key"}` → `prepend_context`, `context` (system), `memories`, `strategy` |
| `POST /capture` | `{"session_key", "messages":[{"role","content","timestamp?"}], "session_id?"}` — one completed turn; timestamps are epoch-ms, coerced |
| `POST /search/memories` | `{"query", "limit?", "type?", "since?", "until?"}` — since/until ISO-8601 |
| `POST /search/conversations` | `{"query", "limit?", "session_key?"}` |
| `POST /session/end` | `{"session_key"}` — flush extraction |
| `POST /seed` | `{"memories":[{"content","type?","priority?","scope?"}]}` |
| `POST /offload` | `{"session_key","content","label?"}` → `{node_id, stub, chars}` |
| `GET /offload/{node_id}` | full text (node id format-validated; 404 unknown) |
| `GET /canvas/{session_key}` | mermaid task canvas |
| `POST /export` | full portable snapshot |
| `POST /import` | an export snapshot; idempotent |
| `POST /consolidate` | near-dup merge + retention decay |
| `GET /quarantine?limit=` | Memory Firewall: memories held pending review |
| `POST /quarantine/release` | `{"ids":[...]}` — approve; memory rejoins active recall |
| `POST /quarantine/reject` | `{"ids":[...]}` — reject; poisoned memory is deleted |
| `GET /audit?limit=` | audit entries (needs `ZANII_AUDIT_ENABLED=true`) |
| `GET /api/overview` | dashboard data: stats (incl. `superseded`, `quarantined`), recent + quarantined memories, persona, scenes, skills, ledger status |

## MCP server

`zanii-memory mcp` (stdio). Register in Claude Code:
`claude mcp add zanii-memory -- zanii-memory mcp`

| Tool | Purpose |
|---|---|
| `memory_search(query, limit, type, since, until)` | hybrid search over long-term memories |
| `conversation_search(query, limit, session_key)` | keyword search over raw history |
| `save_memory(content, type, priority, scope)` | store a durable fact/rule (`scope:"team"` = org-wide) |
| `get_persona()` | the user's narrative profile |

The server ships MCP `instructions` telling agents to check memory before
preference-dependent answers. All three surfaces (SDK, HTTP, MCP) share the
same data directory and config.

## CLI

`serve · mcp · seed <file> · search [-c] · export <file> · import <file> ·
bench · personamem · consolidate · skills · audit · inspect ·
quarantine list|release|reject · ledger-init · ledger-verify`
