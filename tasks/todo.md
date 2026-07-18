# zaniiDB-Agent-Memory — build plan

## v0.1.0 (2026-07-18)

- [x] Package skeleton: pyproject.toml, src layout, ZANII_* env config
- [x] SQLite store: L0/L1 tables, FTS5 + triggers, sqlite-vec KNN, RRF hybrid fusion
- [x] LLM + embedding clients (any OpenAI-compatible endpoint, graceful degradation)
- [x] L1 extraction: scene segmentation + persona/episodic/instruction + priority + dedup
- [x] L2 scene markdown blocks (white-box)
- [x] L3 persona.md generation (four-layer deep scan)
- [x] Pipeline scheduler: every-N-turns, warmup doubling, idle flush, persisted watermark
- [x] Recall: hybrid search + persona injection with char budgets
- [x] FastAPI gateway: 7 routes, Bearer auth, CORS allow-list, OpenAPI docs
- [x] CLI: serve / seed / search / inspect
- [x] Tests: 14 passing (store, RRF, parser, scheduler, scenes, gateway, auth)
- [x] Verified: pytest green, CLI smoke test, sqlite-vec KNN confirmed on this machine

## Review

Deliberate v1 simplifications (each marked `ponytail:` in code):
- L0 conversation search is keyword-only (no raw-turn embeddings)
- L2 scenes are fact ledgers, no LLM summarization pass
- Scheduler session state persists watermark/pending/threshold in DB; in-memory task handles reset on restart (warmup re-covers)

## v0.2.0 (2026-07-18)

- [x] MCP server (stdio): memory_search, conversation_search, save_memory, get_persona
- [x] CLI `zanii-memory mcp` subcommand; shares ZANII_* config and data dir with SDK/gateway
- [x] Tests: tool registration + call_tool roundtrips (17 total passing)
- [x] Verified: live JSON-RPC initialize + tools/list handshake over stdio

## v0.3.0 (2026-07-18)

- [x] MemoryStore protocol (store/base.py) + create_store factory
- [x] PostgresStore: tsvector GIN full-text + pgvector cosine KNN + HNSW index, same RRF hybrid
      — verified live against pgvector/pgvector:pg16 in Docker (keyword, vectors, hybrid, state)
- [x] `[postgres]` optional extra; graceful degradation when pgvector extension unavailable
- [x] Context offload: refs/*.md + Mermaid task canvas (canvas/*.mmd), node_id drill-down,
      path-traversal-safe retrieval; SDK + gateway routes
- [x] Export/import: portable JSON snapshot (L0+L1+persona+scenes), idempotent, re-embeds on import;
      CLI + gateway + SDK; doubles as sqlite→postgres migration
- [x] Multi-tenancy: database-per-tenant isolation, documented in README
- [x] Tests: 26 passed + live PG suite (3 more with ZANII_TEST_PG_DSN)

## v0.4.0 (2026-07-18) — the 10 growth features

- [x] 1. Benchmark harness: `zanii-memory bench` — 20-query eval, recall@1/@5 + MRR
      (baseline on this machine, keyword mode: 80% / 95% / 0.867)
- [x] 2. Observability dashboard: /dashboard (self-contained HTML) + /api/overview
- [x] 3. Automatic offload middleware: AutoOffloader.filter_messages / guard
- [x] 4. Framework adapters: AgentMemoryHooks (before_turn/after_turn/inject) + recipes
- [x] 5. Consolidation & decay: near-duplicate merge (stored vectors) + episodic retention;
      auto-runs each persona cycle; CLI + POST /consolidate
- [x] 6. Temporal search: since/until through store → SDK → gateway → MCP
- [x] 7. Skill/SOP generation: pipeline/skills.py → skills/*.md, auto after persona
- [x] 8. Team memory: scope column (user|team), team knowledge injected into recall
- [x] 9. CJK/multilingual: SQLite trigram tokenizer option, PG text-search config option
- [x] 10. Compliance: audit log (opt-in) + retention policies + encryption guidance in README
- [x] Tests: 39 passed (+2 env-dependent skips)

All 10 shipped.

## v0.4.1 (2026-07-18) — limitations eliminated

- [x] LLM pipeline verified end-to-end via an OpenAI-compatible test double
      (httpx.MockTransport): extraction → priority filter → semantic dedup with live
      sqlite-vec vectors → scene files → persona → skills → hybrid recall. Plus a
      failure-resilience test: LLM outage never loses captured turns (watermark holds).
- [x] PG near-duplicate detection rewritten as LATERAL per-row KNN (HNSW-index-assisted,
      ~n log n) — verified live against pgvector/pgvector:pg16 in Docker with consolidate().
- [x] Trigram short-query gap closed: queries under 3 contiguous chars (2-char CJK words)
      automatically fall back to an escaped LIKE substring scan on both L0 and L1.
- [x] Tests: 41 passed (+2 env-dependent skips)

## Live acceptance (2026-07-18, real OpenAI keys via .env)

- [x] Benchmark, hybrid mode (gpt: text-embedding-3-small): recall@1 100%, recall@5 100%, MRR 1.000
      (keyword baseline: 80% / 95% / 0.867)
- [x] Real conversation through gpt-4o pipeline: extraction produced 3 correctly-typed,
      correctly-prioritized memories — including inferring the absolute date 2026-07-17
      from the word "yesterday" via message timestamps
- [x] Hybrid recall ranked the formatting instruction #1 for a formatting question
- [x] persona.md generated live (narrative profile, correct facts, no hallucination)
- [x] Skills: LLM correctly returned NONE (single event = no recurring pattern yet)

No known limitations remain. Later ideas: LLM scene summarization, L0 embeddings,
per-request user_id scoping, zhparser docs for PG CJK.

## v0.5.x supersede audit chain (2026-07-18, evidence-driven)

- [x] v0.5.0 luna full run: 58.7% — record types (recommendations 9/9, novelty 6/20,
      generalizing 9/12) but fact recall degraded to 12/32; suspected supersede.
      (Earlier same-day: luna reasoning-budget bug found via picked= logging — MCQ
      max_tokens 10 starved GPT-5.x hidden reasoning into empty answers; fixed at 400,
      slice went 40%->80%. Also: provenance guard added after hy3-server mislabeling.)
- [x] Audit slice with SUPERSEDE pair logging: caught paraphrase ping-pong red-handed
      (same fact reworded superseding back and forth); 1 of 4 supersedes legitimate.
- [x] Fixes: cross-type guard (episodic can never kill persona/instruction) + third
      judge verdict "duplicate_of" — paraphrase re-extractions now DROP the new copy
      (no churn, original kept). Unit tests for both.
- [x] Validation on identical 25 questions: 52.0% -> 64.0% (+12pp). Both legitimate
      supersedes still fired; fact recall 1/7 -> 3/7.
- [x] Full 150 run with fix (v0.5.1): 58.0% — hygiene perfect (41 dupes dropped, 4 real
      supersedes, zero churn) but score flat vs 58.7%; the slice's +12pp did not
      generalize (25-question CI is ±19pp — variance discipline re-learned).
      Fact recall 12->14/32. Luna band: 58.0-58.7%.
- [x] Self-review fixes (v0.5.1, no-cost): harness double-extraction race eliminated
      (scheduler triggers disabled during benchmark — was paying twice per row and
      flooding paraphrase dupes); baseline call moved inside resilience guard;
      import now preserves superseded_by (no resurrection on migration); README
      documents v0.5 features + luna numbers.
- [x] LLM response cache (llm_cache.py): exact-request-hash cache for chat + embeddings,
      persistent SQLite, off by default, auto-enabled in the benchmark harness —
      unchanged ingestion/questions replay FREE across runs; any prompt/code change
      is an automatic miss (results stay honest). Hit/miss stats logged per run.
- [ ] Optional next (evidence-backed, now ~$2-4 thanks to cache): duplicate verdict keeps
      the MORE DETAILED version instead of always the old one — targets fact-recall
      detail loss.

## v0.4.2 (2026-07-18) — PersonaMem harness

- [x] personamem.py: downloads PersonaMem-v1 (HF), incremental ingestion respecting each
      question's position (no future info), answers 4-way MCQs from recalled memory only,
      optional no-memory baseline. Stricter protocol than official eval: ground-truth
      persona system messages are EXCLUDED from ingestion.
- [x] CLI: zanii-memory personamem --contexts N --max-questions N --baseline --size 32k|128k|1M
- [x] Unit tests: options parsing (JSON + Python-repr), answer regex, report formatting
- [x] First live run (gpt-4o, 1 context / 15 questions, PRELIMINARY — small sample, ±~24pp CI):
      memory 66.7% vs no-memory baseline 60.0%. Memory recovered 2 questions the baseline
      missed (preference-evolution tracking); lost 1 fact-recall question. Perfect 4/4 on
      "recalling reasons behind previous updates". Reference points: frontier models with
      FULL 32k context score ~52% (paper); the competitor plugin reports 76%.
- [x] Improvements applied: exam-mode recall (20 memories / 8k chars), 10-message
      conversation tail in MCQ context, persona regen only on memory change
- [x] BIG RUN (gpt-4o, 150 questions / 7 contexts): memory 56.0% vs baseline 42.0%
      (+14pp; rescued 35, regressed 14 — significant). ABOVE frontier full-context ~52%.
      Memory-centric subset (excl. suggest_new_ideas): 63.8% vs 46.2%.
      Weakest type: suggest_new_ideas 1/20 (novelty questions punish recall-focused
      answering — the correct option is one the user HASN'T mentioned; needs a prompt
      rule preferring novel-but-profile-consistent options). Also weak:
      recalling_facts_mentioned_by_the_user 1/4 (tiny n).
      Competitor's claimed 76% not yet matched — but our protocol excludes ground-truth
      persona system messages (stricter) and their sample/protocol is unpublished.
- [x] A/B: novelty prompt rule — NO effect (suggest_new_ideas 1/20 -> 2/20; overall
      56.0% -> 53.3%, within +-4pp noise; baseline stable 42.0% -> 41.3%). Reverted.
      Pooled across both 150-question runs: memory 54.7% vs baseline 41.7% (+13pp).
      Diagnosis: suggest_new_ideas is an INFORMATION gap, not an instruction gap — the
      model can't tell which option is novel because memory doesn't inventory everything
      already mentioned.
- [x] Round 3: per-option novelty lookup — WORSE (suggest_new_ideas 0/20, overall 52.7%).
      Root cause: uncalibrated "closest match" snippets look like strong evidence for
      every option (BM25 always finds something), poisoning novelty judgments. Reverted.
- [x] STUCK RULE APPLIED: 3 approaches to suggest_new_ideas failed (1/20, 2/20, 0/20).
      Stopping iteration; documented as a known benchmark-specific weakness. Untried
      idea if ever revisited: similarity-score-THRESHOLDED novelty (only flag matches
      with vector distance < ~0.3 as "previously seen").
- [x] FINAL PUBLISHED NUMBERS (pooled 3 runs, n=450): memory 54.0% (±4.6) vs
      no-memory control 41.8% — stable +12pp uplift, at/above frontier full-context ~52%.
      Best single run 56.0%. Plain prompt confirmed as measured optimum; README updated.

## Crown chase (2026-07-18): two targeted experiments

- [x] Experiment A: THRESHOLD-CALIBRATED novelty (embedding similarity, T=0.6), mini-eval
      on the 20 suggest_new_ideas questions: 3/20 — below the pre-agreed 6/20 gate.
      Similarity logs (n=80 options): smooth continuum 0.20-0.81, median 0.54, NO
      separation at any threshold — options share the user's topic domain, so semantic
      similarity cannot distinguish "already suggested" from "new idea". 4th and FINAL
      attempt on this type; it is adversarial to retrieval-based memory by construction
      (the paper reports all models score worst here). CLOSED.
- [x] Experiment B: full 150 run with --scenes — GATE PASSED: 61.3% (vs 56.0% best prior,
      43.3% baseline; rescued 39 / regressed 12). track_full_preference_evolution
      24/45 -> 30/45 (the chronological ledger carried the preference-change timeline);
      suggest_new_ideas 1/20 -> 5/20 (ledger doubles as an inventory of the familiar);
      reasons-behind-updates 25/28. One dip: recall_user_shared_facts 20/32 -> 15/32
      (4k of ledger may crowd simple fact recall; small-n, unverified).
      61.3% is the NEW PUBLISHED NUMBER; README updated with the reproduce command.
- [ ] Product idea from Experiment B: recall() could optionally include recent scene
      blocks ("include_scenes" recall option) — benchmark-proven signal, one flag.
- [x] Run 5 (ledger 2.5k + repositioned + chronological recall): 54.0% — GATE FAILED,
      reverted to run-4 config. Confounded experiment (3 variables at once — design
      error): evolution dropped 30->24 (trimmed ledger most plausibly cut the timeline
      detail behind run 4's win), fact recall dropped further 15->12. Baseline drifted
      43.3->46.7, confirming +-3-4pp run variance. Lesson recorded: single-variable
      runs only.
- [x] PUBLISHED NUMBER STANDS: 61.3% (run-4 config: wide recall + tail + 4k scene
      ledger after memories). recall_chronological kept as a product option, off by
      default, marked not-yet-validated.
- [x] Single-variable experiments (gpt-4o pinned): A chronological-alone 54.7%,
      B 6k-ledger-alone 54.7% — BOTH GATES FAILED. (Side discovery: luna/GPT-5.x
      rejects max_tokens; LLM client now auto-negotiates max_completion_tokens.)
- [x] STATISTICAL CLOSE-OUT of gpt-4o config tuning (7 runs × 150 q):
      no-scenes band 52.7-56.0 (pooled 54.0), scenes band 54.0-61.3 (pooled 56.2).
      Run 4's 61.3% is the favorable tail of ±4pp run variance, NOT a config effect
      reproducible on demand. Honest numbers: pooled memory 55.2% (n=1050), pooled
      baseline 43.1% (n=750) -> +12pp uplift is the ROBUST claim; ~52% frontier
      full-context is matched/slightly exceeded, not clearly beaten. README revised
      accordingly (best single run 61.3% reported as such, not as the headline).
      Config verdict: --scenes stays recommended (+2pp pooled, consistently
      non-negative). gpt-4o tuning is CLOSED — remaining lever is the model
      (gpt-5.6-luna, client now compatible) and/or the definitive full-589 run.
