# ZaniiDB — Python reference

Package (PyPI): `zaniidb-agent-memory`; import `zanii_memory`. Python 3.11+.
Extras: `[postgres]` (psycopg), `[provable]` (zanii SDK), `[dev]` (pytest).

## MemoryCore / ZaniiMemory (the SDK surface)

```python
from zanii_memory import ZaniiMemory, Settings   # ZaniiMemory == MemoryCore

memory = ZaniiMemory()               # or ZaniiMemory(Settings(data_dir=..., llm_model=...))
await memory.initialize()            # opens store, starts scheduler, attaches ledger

await memory.capture(session_key, messages, session_id="")   # one completed turn
r = await memory.recall(query, session_key)                  # RecallResult
hits = await memory.search_memories(query, limit=10, type=None, since=None, until=None)  # epoch-ms bounds
rows = await memory.search_conversations(query, limit=10, session_key=None)
await memory.seed([{ "content": ..., "type": "persona|episodic|instruction",
                     "priority": 80, "scope": "user|team" }])
await memory.end_session(session_key)          # flush extraction now
res = await memory.consolidate()               # near-dup merge + retention decay
n = await memory.generate_skills()             # SOP docs from memories (needs LLM)
q = memory.list_quarantine()                   # Memory Firewall: held-for-review memories
await memory.release_quarantined([id, ...])    # approve -> rejoins recall (receipted)
await memory.reject_quarantined([id, ...])     # reject -> deleted (receipted)
data = await memory.export_memory()            # portable snapshot (incl. superseded state)
await memory.import_memory(data)               # idempotent restore / backend migration
stub = await memory.offload(session_key, big_text, label="")   # context offload -> refs/<node>.md
text = await memory.retrieve_ref(node_id)      # drill-down (node id validated)
mmd  = await memory.get_canvas(session_key)    # mermaid task canvas
memory.stats(); memory.audit_log(100)
await memory.close()
```

`RecallResult`: `prepend_context` (memories block), `append_system_context`
(persona + team knowledge), `memories` (list of {content,type,score}),
`strategy` ("hybrid"|"keyword"|"embedding").

## Memory Firewall (anti-poisoning)

Mark third-party content with a channel at capture so the firewall can source-bind it:
```python
await memory.capture("s1", [
    {"role": "user", "content": "Summarize this email"},
    {"role": "user", "channel": "email", "content": fetched_email},   # untrusted source
])
```
Instructions extracted from untrusted channels are always quarantined; injection signatures
(heuristic + LLM screen) are caught; quarantined memories are excluded from all recall until
`release_quarantined`/`reject_quarantined`. Config: `firewall_enabled` (default on),
`firewall_trusted_channels` ("user,assistant"), `firewall_strict`, `firewall_llm_screen`
(disable on weak local models — they over-flag; see docs/firewall-redteam.md).

## Procedural recall & auto-offload

`recall()` injects the best-matching learned skill (`recall_skills`, default on).
`AutoOffloader(core, session_key, threshold_chars=4000, stale_after_messages=N)` stubs
oversized and (with N>0) stale tool outputs; `find_relevant_skill(skills_dir, query)` is the
matcher. Extraction tags episodic `metadata.outcome` (success|failure) for skill quality.

## Framework hooks (any agent loop, 3 lines)

```python
from zanii_memory.adapters import AgentMemoryHooks

hooks = AgentMemoryHooks(memory, session_key="user-42")
inj = await hooks.before_turn(user_text)       # PromptInjection(prepend, system)
messages = hooks.inject(messages, inj)         # OpenAI-style message list
...
await hooks.after_turn(user_text, assistant_text)
await hooks.end()
```

## Automatic context offload

```python
from zanii_memory.autooffload import AutoOffloader
auto = AutoOffloader(memory, "task-1", threshold_chars=4000)   # roles: tool/function only
messages = await auto.filter_messages(messages)   # oversized bodies -> [offloaded:Nxxxx] stubs
```

## Store protocol (backends: SqliteStore, PostgresStore)

`create_store(cfg, want_vectors)` selects by `ZANII_DATABASE_URL`. Key methods:
`record_l0`, `search_l0`, `insert_l1`, `hybrid_search_l1(query, embedding, limit,
type, since, until)`, `mark_superseded(old_ids, new_id)`, `delete_l1`,
`find_near_duplicate_pairs(max_distance)`, `get_l1_filtered(type, scope,
created_before, limit)`, `get_pipeline_state`/`set_pipeline_state` (watermark),
`get_kv`/`set_kv`, `audit`/`get_audit`, `stats`. All L1 search paths exclude
superseded rows.

## Pipeline internals (when instrumenting or extending)

- `pipeline.extractor.run_extraction(store, llm, embedder, cfg, session_key)` —
  one batch (≤200 L0 rows): scene segmentation + typed extraction + priority
  filter + semantic dedup (< 0.12 cosine) + supersede pass; advances the
  watermark so rows are never re-processed (LLM failure leaves it untouched).
- `pipeline.supersede.resolve_conflicts` — same-type-only candidates ≤ 0.45
  cosine; verdicts: duplicate (drop NEW copy) / supersedes / distinct.
- `pipeline.persona.run_persona`, `pipeline.scenes.maybe_condense_scene`,
  `pipeline.skills.run_skills`, `pipeline.consolidate.consolidate`.
- `provable.ProvableLedger.emit(kind, content)` — hash-chained receipts;
  local `ledger_entries.jsonl` holds full entries (with proof salts).

## Testing offline

Use `httpx.MockTransport` and preset `client._client` on `LLMClient` /
`EmbeddingClient` — no production code changes needed. The e2e suite
(`tests/test_pipeline_e2e.py`) is the reference for mocking extraction,
supersede (echo real ids from the prompt), persona, and embeddings.
