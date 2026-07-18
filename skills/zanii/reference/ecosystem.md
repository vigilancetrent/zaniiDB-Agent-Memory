# Zanii — optional ecosystem packages

Install only what a task needs. TS on npm; Python modules ship inside `zanii` (0.15.0).
All packages below are **published**. 38 optional npm packages: the five ecosystem
(`ai,webhooks,testing,monitor,react`), the ten standalone, four framework/privacy
(`langchain,openai-agents,retention,redact`), three standards-landing
(`a2a-directory,x402,erc8004`), four UAE-compliance
(`consent,admissibility,fta,walls`), `memory` (provable hash-chained agent memory), and
three trust-boundary (`kya,attest,swarm`), `subject` (per-subject auditability), three
real-world provenance (`provenance,custody,decisions`), `sentinel` (runtime behavioral monitoring), two
institutional-trust (`credentials,gov`), and `health` (medical audit trails).

## `@zanii/ai` — one-line framework tool instrumentation (npm)
Wrap a Vercel-AI-SDK-style tools map (or any tool with `execute`) so every call is receipted.
```ts
import { withZanii } from '@zanii/ai';        // peerDep @zanii/sdk
const tools = withZanii(myTools, { agent });  // every tool.execute → a receipt
```
Python: no separate package — use the SDK's `zanii.wrap_tool('email.send', fn)` on the callable.

## `@zanii/webhooks` / `zanii.webhooks` — receive + verify webhooks
```ts
import { createWebhookReceiver } from '@zanii/webhooks';   // zero-dep, Node 18+
const receive = createWebhookReceiver({ secret, on: { 'receipt.recorded': fn, 'receipt.rejected': fn } });
const { status } = await receive(rawBody, req.header('x-zanii-signature')); // 401 on bad sig, never dispatches
```
```python
from zanii.webhooks import create_webhook_receiver
receive = create_webhook_receiver(secret, on={"receipt.recorded": save})
res = receive(raw_body, request.headers.get("X-Zanii-Signature"))   # {"ok","status","event"}
```
Always pass the **raw** body (the exact bytes that were signed). Get `secret` from `POST /v1/account/webhooks`.

## `@zanii/testing` / `zanii.testing` — test agents offline
```ts
import { createTestLedger, makeIdentity, makeCert } from '@zanii/testing';
const ledger = createTestLedger();
const zanii = new ZaniiAgent({ /* … */, fetchImpl: ledger.fetch });
await zanii.record({ target: 'crm.lookup', payload: {} }); await zanii.flush();
expect(ledger.hasRecorded('crm.lookup')).toBe(true);
```
```python
from zanii.testing import fake_ledger, make_identity, make_cert
with fake_ledger() as ledger:              # monkeypatches the SDK's HTTP to an in-memory ledger
    z = ZaniiAgent(server_url="http://test", agent_did=agent.did, agent_private_key=agent.private_key, delegation=[cert])
    z.record(target="crm.lookup", payload={}); z.flush()
    assert ledger.has_recorded("crm.lookup") and ledger.verify_all()
```
Real Merkle proofs — `fetchAndVerifyProof` / `verify_audit_bundle` verify against it.

## `@zanii/monitor` / `zanii.monitor` — independent append-only + anchor watchdog
```sh
zanii-monitor --server https://ledger.zanii.agency --once            # exit 1 on violation
python -m zanii.monitor --server https://ledger.zanii.agency --once
```
```ts
import { checkOnce } from '@zanii/monitor';
const r = await checkOnce(server, prevState);   // persist r.state; r.violations lists any rewrite/anchor failure
```
Proves the log never rewrote history (consistency proof from the last size) — the "trust no one" guarantee, enforced.

## `@zanii/react` — client-side trust UI (npm, JS only)
```tsx
import { VerifiedBadge, ProofViewer, AgentProfile, LedgerTicker } from '@zanii/react';
<VerifiedBadge did={did} /> <ProofViewer hash={hash} />   // verify in the browser, zero trust
```

---

## The ten standalone packages (published — v0.1.0 npm · Python parity)

TS source in `packages/<name>`; Python parity ships inside `zanii` (9 of 10 — `gateway` is
TS-only). Reach for one only when the task fits.

- **`@zanii/cli`** / **`zanii.cli`** (the `zanii` console script) — `keygen`, `did`, `delegate`,
  `revoke`, `verify`, `bundle`, `export`, `stats`, `agent`. `--json` on any command; `verify`/`bundle`
  exit non-zero on failure (drops into CI). TS also `import { run } from '@zanii/cli'`.
- **`@zanii/gateway`** (TS-only) — transparent HTTP proxy; receipts every forwarded call as `http.<method>.<path>`.
  `createZaniiHandler({ upstream, agent })` (fetch/edge), `createZaniiGateway` (Node), `zanii-gateway` CLI.
  *Python:* wrap your HTTP client function with the SDK's `wrap_tool`.
- **`@zanii/compliance`** / **`zanii.compliance`** — audit bundle → auditor report.
  `buildComplianceReport(bundle, { controls })` / `build_compliance_report(bundle, controls=…)`
  (offline verify + action breakdown + anchoring coverage + flags), `renderComplianceMarkdown` / `render_compliance_markdown`.
- **`@zanii/kms`** / **`zanii.kms`** — seal keys at rest (scrypt + AES-256-GCM). `sealIdentity`/`seal_identity`,
  `openIdentity`/`open_identity` → `{ did, privateKey }` for a new agent. Sealed-key format is cross-language compatible.
- **`@zanii/witness`** / **`zanii.witness`** — independent co-signer. `createWitness(keypair).cosign(sth, { consistencyProof })`
  verifies append-only then counter-signs; `verifyCosignature`/`verify_cosignature`. (Contrast `@zanii/monitor`, which only watches.)
- **`@zanii/policy`** / **`zanii.policy`** — pre-action `allow`/`deny`/`require_approval` on payload conditions.
  `createPolicyEngine({ rules, default }).evaluate(...)` / `create_policy_engine(...)`. Ops: `eq ne lt lte gt gte in nin`; fixed-window `rateLimit`.
- **`@zanii/otel`** / **`zanii.otel`** (`zanii[otel]`) — `withTracing(agent)` / `with_tracing(agent)` makes every
  `record` an OpenTelemetry span (`zanii.target`/`action`/`hash`). Peers: `@opentelemetry/api`, `opentelemetry-api`.
- **`@zanii/payments`** / **`zanii.payments`** — correct money: `parseMoney('49.99','USD')` / `parse_money(...)` → integer
  minor units, never a float. `buildPayment` / `build_payment` → validated payload for `recordPayment`/`record_payment`. `registerCurrency` for new codes.
- **`@zanii/embed`** / **`zanii.embed`** — framework-free "Verified by Zanii" badges (escaped SVG + snippet).
  `agentBadge`/`agent_badge`, `badgeSVG`/`badge_svg`, `proofBadgeSVG`/`proof_badge_svg`, `embedSnippet`/`embed_snippet`.
- **`@zanii/connectors`** / **`zanii.connectors`** — one-call proof recording for LLM tool calls.
  `wrapToolbox`/`wrap_toolbox`, `runToolCalls`/`run_tool_calls` (OpenAI + Anthropic shapes), `normalizeToolCall`/`normalize_tool_call`.

---

## Framework adapters + privacy (published — v0.1.0 npm · Python parity)

Integrate via each framework's **own hook** (not per-tool wrapping) — attach once, the whole run is receipted.

- **`@zanii/langchain`** / **`zanii.langchain`** (`zanii[langchain]`) — receipt every tool call in a
  LangChain **or LangGraph** run via one callback handler. `new ZaniiCallbackHandler({ agent })` /
  `zanii_callbacks(agent)` → pass in `config.callbacks`. TS also `withZaniiConfig(config, agent)`.
- **`@zanii/openai-agents`** / **`zanii.openai_agents`** (`zanii[openai-agents]`) — OpenAI Agents SDK
  lifecycle hooks. `new ZaniiRunHooks(agent)` → `Runner.run(agent, input, { hooks })` / `hooks=`. Records tool + output.
- **`zanii.crewai`** (`zanii[crewai]`, Python-only) — `instrument_crew(crew, agent)` attaches a receipting
  `step_callback` (chains any existing). CrewAI has no JS SDK.
- **`@zanii/retention`** / **`zanii.retention`** (v0.2.0) — GDPR Art. 17 deletion **attestations** (you can't prove
  absence; a signed timestamped receipt is the evidence). `buildRetentionAttestation({ subject, policy, executedAt })`
  → `data.retention.<action>` receipt with a salted subject commitment (no raw PII). `verifyRetention`, `commitSubject`, `verifySubject`.
  Also the **inverse** — `buildRetentionHold({ subject, category, legalBasis, retainUntil })` / `build_retention_hold`
  → a `data.retention.hold` receipt proving records were *kept* (UAE 5-yr rule requires proving this). `verifyRetentionHold`.
- **`@zanii/redact`** / **`zanii.redact`** — **selective disclosure** (SPEC §11). `commit(fields)` → an envelope
  (Merkle root + field names) you record as the payload; `disclose(result, key)` → a proof; `verifyDisclosure(d, envelope)`.
  Prove an agent acted on specific data without revealing the rest. No server change (root is opaque to the log).

---

## Standards-landing packages (published — v0.1.0 npm · zanii 0.15.0 Python)

For the A2A / agentic-commerce era. TS + Python parity.

- **`@zanii/a2a-directory`** / **`zanii.a2a_directory`** — resolve an agent DID (e.g. from an A2A
  agent card) to its **verified** history. `resolveAgent(did)` (trust summary via `/v1/reputation`),
  `resolveAndVerify(did)` (pulls the audit bundle + `verifyAuditBundle` offline — trust the maths,
  not the counts), `summarize`, `agentDidFromCard`. Python: `resolve_agent`, `resolve_and_verify`.
- **`@zanii/x402`** / **`zanii.x402`** — bind a payment receipt to its on-chain settlement.
  `verifySettlement({ txHash, to, minValue }, txFetcher)` (tx exists/succeeded/right recipient/value),
  `buildX402Payment(...)` (reuses `@zanii/payments`), zero-dep `jsonRpcTxFetcher(rpcUrl)` for any EVM
  chain. Chain reads injected → testable offline. Python: `verify_settlement`, `json_rpc_tx_fetcher`.
- **`@zanii/erc8004`** / **`zanii.erc8004`** — register/resolve agents as ERC-8004 identities wired to
  Zanii proofs. `buildRegistrationFile(...)`, `toDataUri`, `resolveRegistration(agentUri)`,
  `verifyResolvedAgent(agentUri)` (verifies the resolved agent's history offline). Mint tx is your
  wallet's job. Python: `build_registration_file`, `resolve_registration`, `verify_resolved_agent`.

---

## UAE-compliance packages (published — v0.1.0 npm · zanii 0.15.0 Python)

Regional law as product. TS + Python parity.

- **`@zanii/consent`** / **`zanii.consent`** — **PDPL consent receipts**. `buildConsentReceipt({ subject, purpose, scope, action, basis })`
  (`action` = `'granted'` | `'withdrawn'`) → a `consent.<action>` receipt with a salted subject commitment; `verifyConsent`. Zero-dep.
- **`@zanii/admissibility`** / **`zanii.admissibility`** — court-ready **bilingual (Arabic/English)** evidence pack for UAE
  Electronic Transactions Law 46/2021. `buildEvidencePack(bundle)` (verifies via `verifyAuditBundle`, emits the 6
  verification steps written for a judge/expert + the legal basis + offline reproduce commands);
  `renderEvidencePackMarkdown(pack, 'en'|'ar'|'both')`. Dep `@zanii/core`.
- **`@zanii/fta`** / **`zanii.fta`** — Federal Tax Authority filing evidence (Meezan/Books). `buildFilingPrepReceipt(...)`
  → `fta.filing.prepared` inside the `FTA_WALL` ("prepares, never files/advises"); `buildTaxAgentHandoff(...)`
  → `fta.filing.handoff` (the licensed Tax-Agent handoff, as its own receipt); `verifyFilingEvidence`. Zero-dep.
- **`@zanii/walls`** / **`zanii.walls`** — UAE vertical **wall presets** as enforceable, auditable artifacts. `WALLS`
  (`sca-trading` "education only, never buy this", `rera-realty`, `tdra-messaging`, `legal-drafting`, `consumer-due`,
  and the `difc-dp`/`adgm-dp` free-zone variants — which differ from federal PDPL); `wallPolicy(wall)` → a `@zanii/policy`
  deny config; `wallManifestHash(wall)` → receipt the enforced rulebook per deploy; `checkOutput(wall, text)` → heuristic
  crossing detector; `buildEvalReceipt(wall, { passed, failed })`. Dep `@zanii/core`.

---

## Provable agent memory (published — v0.1.0 npm · zanii 0.15.0 Python)

- **`@zanii/memory`** / **`zanii.memory`** — hash-chained agent memory: a `memory.write` receipt records what an
  agent remembered and when, with a **salted content commitment** (raw memory never leaves your system) and a
  tamper-evident `prev`→`entry_hash` link. `appendMemory(prev, { content, kind, ts })` / `append_memory(prev, ...)`
  auto-links + increments `seq` (pass `null` for the first entry); `buildMemoryWrite(...)` for manual `prev`/`seq`;
  `verifyMemory(payload)` checks one entry's `entry_hash` is self-consistent (catches an edited entry);
  `verifyMemoryChain(entries)` also checks the links + `seq` (catches an inserted/deleted entry); `commitContent` /
  `verifyContent` prove what a specific entry remembered. `entry_hash` is RFC 8785 canonical (`@zanii/core` `jcsHash`),
  so a chain verifies **byte-identically** in TS and Python. Answers "why did it decide that?" for long-running agents.
  Dep `@zanii/core`.

---

## Trust-boundary packages (published — kya/attest v0.1.0, swarm v0.2.0 npm · zanii 0.15.0 Python)

Close the accountability gaps: who you transact with, which code ran, and N-party teams.

- **`@zanii/kya`** / **`zanii.kya`** — "Know Your Agent": screen a counterparty **before** transacting.
  `screenAgent(did, { denyList, provider })` / `screen_agent(...)` checks a caller deny-list + an
  **injected** sanctions/KYB `provider` (x402-style — the list is yours, the rails are ours);
  `buildScreeningReceipt` → `kya.screening`; `verifyScreening`. `resolveAndScreen` pulls history via
  `@zanii/a2a-directory` first. Honest limit: a `did:key` is only as screenable as its owner is disclosed.
  Dep `@zanii/core` + `@zanii/a2a-directory`.
- **`@zanii/attest`** / **`zanii.attest`** — bind *which code ran* to a receipt. `attestationField(a)` adds an
  `attestation_hash` provenance field (the TEE down payment on `runtime_hash`); `verifyAttestation(a, { verifyQuote })`
  checks structure and **delegates SGX/Nitro/TPM quote verification to an injected verifier** — no verifier ⇒
  `quoteVerified: null` (unknown), never a false "verified". Dep `@zanii/core`.
- **`@zanii/swarm`** / **`zanii.swarm`** — N-party (3+) co-signed receipts for agent teams: genuine **M-of-N
  Ed25519 threshold**. Offline: `buildSwarmBody`, `signSwarm`, `verifySwarm` (signatures only). **On-ledger
  (SPEC §14, live at `POST /v1/swarm`):** `swarmSigner`/`swarm_signer` + `buildSwarmReceipt` + the
  authority-complete `verifySwarmReceipt`/`verify_swarm_receipt` — per signer: signature + owner-rooted
  unrevoked/unexpired delegation + target-in-scope + prev == chain head; then threshold; then **distinct-owner
  segregation** (default on — one owner's agents can't fake an M-of-N). TS↔Python↔server verified byte-for-byte.
  Dep `@zanii/core` (+ `@noble/curves`, `@noble/hashes`). *Don't confuse `verifySwarm` (offline) with
  `verifySwarmReceipt` (authority).*

---

## Per-subject auditability (published — v0.1.0 npm · zanii 0.15.0 Python · core/sdk 0.4.0)

- **`@zanii/subject`** / **`zanii.subject`** — the **end user's own slice** of the ledger: a platform's
  millions of end users each hold their own `did:key` and independently verify what agents did on *their*
  account, without seeing anyone else's. The platform stamps a pseudonymous, platform-scoped tag on each
  receipt: `subjectTag(subjectDid, platformId)` (RFC 8785 — byte-identical TS/Python), passed as
  `record({ subjectTag })` / `record(..., subject_tag=...)` — a **signature-covered** SPEC §3 field
  (core/sdk ≥0.4.0). The subject computes the same tag and pulls `GET /v1/subjects/{tag}`, then
  `fetchSubjectHistory` / `fetch_subject_history` **offline-verifies every receipt** (signature +
  delegation + tag match — foreign/invalid receipts are flagged, never silently shown).
  `subjectIdentity`/`subject_identity`, `signSubjectClaim`/`verifySubjectClaim` ("this is my slice").
  Same subject ⇒ **different tag per platform** (no cross-platform linkage); a tag is not reversible to an
  identity. Honest limit: the slice is only as complete as the platform's stamping. Dep `@zanii/core`.

---

## Real-world provenance (published — v0.1.0 npm · zanii 0.15.0 Python)

The same receipt that makes an AI agent accountable makes a shipment, an artwork, and an
algorithm accountable. TS + Python parity.

- **`@zanii/provenance`** / **`zanii.provenance`** — content credentials (anti-deepfake): the artifact's hash
  signed by the creating agent's did:key. `buildContentCredential({ artifact | artifactHash, agentDid, createdAt, meta })`,
  `verifyContentCredential(cred, artifact?)` (offline), `credentialReceipt` → `content.created` (anti-backdating),
  `resolveCreator` → the creator's **verified** history via a2a-directory. Limits: who-*signed* not who-*authored*;
  absence proves nothing; hash breaks on re-encode (`meta.derivative_of` for derivatives); **C2PA not v1**.
- **`@zanii/custody`** / **`zanii.custody`** — supply-chain custody chains. `itemTag(itemId, namespace)`
  (pseudonymous — serials never on-ledger; the item's slice is `GET /v1/subjects/{tag}`); `buildHandoff`
  (a2a 2-party co-sign via `/v1/interactions`, tag inside the signed body, evidence always salt-committed);
  `buildCustodyEvent` (swarm N-party via `/v1/swarm`); `verifyCustodyChain(entries, { tag })` — **continuity**:
  receiver of *n* = giver of *n+1*, ts monotonic, tag-bound; `custodySummary`. Limit: **attestations, not atoms** —
  fraud becomes attributable, not impossible.
- **`@zanii/decisions`** / **`zanii.decisions`** — auditable algorithmic decisions (gig/creator fairness).
  `buildDecisionReceipt({ subjectDid, platform, kind, manifestHash, outcome, factors, ts })` — **`manifestHash`
  required** (no rulebook ⇒ rejected); factors salt-committed (dispute disclosure is provably what was committed);
  `verifyDecision`; `ruleConsistency(payloads)` → rulebook windows; **interleaved rulebooks = the red flag**
  (rules differed between people at the same time). Proves completeness + rule-consistency + committed factors —
  **never "the algorithm is fair"**. Deps `@zanii/core` + `@zanii/subject`.

---

## Runtime behavioral monitoring (published — v0.1.0 npm · zanii 0.15.0 Python)

- **`@zanii/sentinel`** / **`zanii.sentinel`** — "antivirus for agents": the behavioral layer between
  `@zanii/monitor` (log integrity) and `@zanii/policy` (pre-action rules). `buildBaseline(agentId, { receipts, delegation })`
  → declared scopes (from the delegation chain) + learned habits (target prefixes, rate, intent ratio, active
  hours; **float-free integer milli-units** so `baselineHash` is byte-identical TS/Python).
  `scan(receipts, baseline, opts)` → findings from six detectors — `novel-target` (high when outside declared
  scopes), `scope-edge` (fed by `receipt.rejected` webhooks), `rate-spike`, `intent-gap`, `sequence` (default:
  the exfil shape read→archive→external-send), `off-hours` — plus `wall-crossing` in **operator mode** (inject
  `payloadOf` + `checkContent`, e.g. `walls.checkOutput` over raw payloads pre-hash).
  `createWatcher({ server, baselines, cursor, onFinding })` polls `/v1/recent` with a **rolling window** (so a
  multi-step exfil arriving across polls still fires), de-duplicates findings, and takes a **resumable cursor**
  (persist it — otherwise a restart re-alerts). `escalationRule(f)` → a `require_approval` speed bump (returns
  **null** when the finding names no targets — it will not auto-gate the agent's whole surface).
  `buildAlertReceipt` → **`sentinel.alert`**, recorded by the sentinel's OWN did:key (watcher ≠ watched): detection
  is tamper-evident, and silence is checkable. Limits: detection ≠ prevention; false positives are structural;
  in-scope compromise is the hard case. For production prefer webhooks over polling (`/v1/recent` is a global
  feed capped at 100). Dep `@zanii/core`.

---

## Institutional trust (published — v0.1.0 npm · zanii 0.15.0 Python)

- **`@zanii/credentials`** / **`zanii.credentials`** — verifiable institutional credentials (diplomas,
  licences, certifications), offline-verifiable in ms with no call to the registrar. **The package is
  not the credential — it is the root of trust.** `verifyCredential` runs **four** checks and the
  fourth is the one that matters: signature → not expired → not revoked (signed list with an
  **explicit freshness window**) → **the issuer DID resolves to a named institution**, bound to a
  domain it controls (`resolveIssuer` → `https://<domain>/.well-known/zanii-issuer.json`; the doc
  must be served from the domain it claims — no cross-domain vouching).
  `buildCredential`, `buildRevocationList`, `buildPresentation`/`verifyPresentation` — a credential is
  **not a bearer token**: a thief with the file but not the key fails, and presentations don't replay.
  **Nothing is silently assumed** — no resolver ⇒ "institutional identity NOT verified"; no list ⇒
  "revocation NOT checked"; `ok` is never true on an unchecked assumption. *Zanii verifies domain
  control; it is **never** the accreditor.* Dep `@zanii/core`.
- **`@zanii/gov`** / **`zanii.gov`** — public-sector algorithmic accountability (benefits, visas, fines,
  licences). **No new crypto** — a preset over `decisions` + `subject` + the bilingual `admissibility`
  discipline. **`buildGovDecision` THROWS on a missing `manifestHash`** — a state decision with no
  governing rulebook cannot be constructed. **`appealPack(tag)`** is the hero: pull the citizen's slice,
  verify every decision offline, test rule-consistency, and `renderAppealPackMarkdown` a bilingual pack
  for an administrative judge — *the state proves what its algorithm did to you, and you hold the proof*.
  Flags **interleaved rulebooks** (different rules decided people at the same time) and **unruled
  decisions**. The pack states, in both languages, that it proves the **process, never the justice**.
  Deps `@zanii/core` + `@zanii/decisions` + `@zanii/subject`.

---

## Medical audit trails (published — v0.1.0 npm · zanii 0.15.0 Python)

- **`@zanii/health`** / **`zanii.health`** — medical audit trails **without leaking the pattern**. For
  medicine the **metadata IS the sensitive data** (access frequency to an oncology or psychiatric
  record is itself PHI), so this package deliberately breaks Zanii's usual stable per-subject tag.
  - **Per-episode unlinkable tags** — `episodeTag(seed, n)`. An insider sees N unrelated tags, not
    "this person was here 14 times". *An episode is verifiable; a life is not linkable except by the
    patient.* Cross-language identical.
  - **🔴 THE RULE: the patient supplies the TAG, never the SEED.** A provider holding the seed could
    enumerate `n` and reconstruct the entire cross-institution history — privacy gain zero, and
    *illusory*. A **red test in both languages** guards this.
  - **The four-party question:** `buildAccessReceipt` (who — `purpose` **mandatory**),
    `buildRecommendation` (which model + **`manifestHash` REQUIRED** — no protocol, no receipt),
    `buildClinicianConfirmation` (**which named human** signed — the model did not decide, a person did).
  - **`protocolTrail` is deliberately NOT `ruleConsistency`.** "Same rulebook for everyone" is a
    fairness property in `@zanii/gov` and a **clinical error** in medicine — individualised care is
    correct, protocols legitimately coexist. **No uniformity verdict exists to fail.** Deviation is
    recorded, never a defect; a **missing** protocol is the defect.
  - **Break-glass: loud, not impossible.** Mandatory receipt + required reason + the clinician's
    **personal signature** (the deterrent). `pendingBreakGlass()` makes un-reviewed events countable and
    visible to the patient. **The metric, not the mandate** — we cannot enforce an institution's review
    policy, but we make ignoring it undeniable. *A hole we deliberately keep open: a closed one kills patients.*
  - `fetchEpisodes(seed)` — the multi-tag fetch `@zanii/subject` lacks; **only the seed-holder can link
    the chain.** Deps `@zanii/core` + `@zanii/subject`. **Zero server changes.**
