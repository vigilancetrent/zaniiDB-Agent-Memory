---
name: zanii
description: >-
  Build, instrument, or audit AI agents with Zanii — verifiable did:key identity,
  scoped delegation, signed hash-chained proof-of-action receipts, offline
  verification, audit bundles, the deterministic runtime, and the MCP proxy. Use
  this whenever a task involves agent accountability, a tamper-proof record of what
  an AI agent did, "prove who did what", or the @zanii/* (npm) or zanii (Python)
  SDKs, or the ledger.zanii.agency API.
---

# Zanii — verifiable identity & proof-of-action for AI agents

Zanii gives every AI agent a cryptographic identity and turns each action into a
signed, hash-chained **receipt** in an append-only Merkle transparency log,
anchored on-chain. Anyone can verify *who did what, under whose authority* —
**offline, without trusting the server**. The ledger stores only a hash of each
payload, so business data never leaves the caller's systems.

## Which package to use

| Need | npm | Python |
|---|---|---|
| Pure protocol + **verify** offline (no I/O) | `@zanii/core` | `zanii.core` |
| **Instrument an agent** (identity, delegation, record, verify) — start here | `@zanii/sdk` | `zanii` |
| **Deterministic rails** (propose→gate→record; enforce authority/status/human-gate) | `@zanii/runtime` | `zanii.runtime` |
| **Receipt every MCP tool call**, zero agent changes | `@zanii/mcp-proxy` | `zanii.mcp_proxy` (`zanii[mcp]`) |
| **Instrument framework tools** in one line (Vercel AI SDK) | `@zanii/ai` | *(use the SDK's `wrap_tool`)* |
| **Receive + verify webhooks** (`X-Zanii-Signature`) | `@zanii/webhooks` | `zanii.webhooks` |
| **Test agents offline** (in-memory ledger + fixtures) | `@zanii/testing` | `zanii.testing` |
| **Independently monitor** a log (append-only + anchors) | `@zanii/monitor` | `zanii.monitor` (`zanii-monitor` CLI) |
| **Trust UI** — client-side verifying React components | `@zanii/react` | *(JS only)* |

Thirty-three more optional packages, **published** (`v0.1.0` npm; `@zanii/retention` + `@zanii/swarm`
`v0.2.0`; Python parity in `zanii` 0.15.0) — see `reference/ecosystem.md` for signatures:

| Need | npm |
|---|---|
| **CLI** — identities/delegation/verify/export from the terminal | `@zanii/cli` |
| **Proxy** any HTTP API so every call is receipted | `@zanii/gateway` |
| **Compliance report** from an audit bundle | `@zanii/compliance` |
| **Seal keys at rest** (scrypt + AES-256-GCM) | `@zanii/kms` |
| **Co-sign** a log as an independent witness | `@zanii/witness` |
| **Pre-action policy** (amount caps, allow-lists, rate limits) | `@zanii/policy` |
| **OpenTelemetry spans** for every action | `@zanii/otel` |
| **Correct money** for payment receipts (bigint minor units) | `@zanii/payments` |
| **"Verified by Zanii" badges** for any site | `@zanii/embed` |
| **OpenAI/Anthropic tool-call** proof recording | `@zanii/connectors` |
| **LangChain / LangGraph** — receipt a whole run | `@zanii/langchain` |
| **OpenAI Agents SDK** — receipt via RunHooks | `@zanii/openai-agents` |
| **CrewAI** (Python-only) — `zanii[crewai]` | *(zanii.crewai)* |
| **GDPR deletion attestations** (+ the inverse: proof records were *kept*) | `@zanii/retention` |
| **Selective disclosure** (prove one field, hide the rest) | `@zanii/redact` |
| **A2A discovery** — resolve a DID to its verified history | `@zanii/a2a-directory` |
| **Verify a payment's on-chain settlement** (x402/AP2) | `@zanii/x402` |
| **ERC-8004 identity** — register/resolve agents on-chain | `@zanii/erc8004` |
| **PDPL consent receipts** (grant/withdrawal) | `@zanii/consent` |
| **Court-ready evidence pack** (bilingual AR/EN, UAE 46/2021) | `@zanii/admissibility` |
| **FTA filing evidence** — "prepares, never files" + Tax-Agent handoff | `@zanii/fta` |
| **Vertical walls** — SCA trading/RERA/TDRA/Legal/Consumer + DIFC/ADGM | `@zanii/walls` |
| **Provable agent memory** — hash-chained "why did it decide that?" | `@zanii/memory` |
| **Know Your Agent** — screen a counterparty before transacting | `@zanii/kya` |
| **Which code ran** — bind a TEE/runtime attestation to a receipt | `@zanii/attest` |
| **N-party (3+) co-signed receipts** — swarm teams (`POST /v1/swarm`, SPEC §14) | `@zanii/swarm` |
| **Per-subject auditability** — end users verify their own slice (`/v1/subjects/{tag}`) | `@zanii/subject` |
| **Content credentials** — "made by a known, accountable agent" (anti-deepfake) | `@zanii/provenance` |
| **Supply-chain custody** — co-signed handoff chains for physical goods | `@zanii/custody` |
| **Auditable algorithmic decisions** — completeness + rule-consistency + committed factors | `@zanii/decisions` |
| **Behavioral monitoring** — drift detection, "antivirus for agents" | `@zanii/sentinel` |
| **Verifiable credentials** — diplomas/licences, domain-bound issuer root-of-trust | `@zanii/credentials` |
| **Public-sector accountability** — state decisions + citizen appeal pack | `@zanii/gov` |
| **Medical audit trails** — per-episode *unlinkable* tags; break-glass is loud, not impossible | `@zanii/health` |

Install: `npm i @zanii/sdk` or `pip install zanii`. Everything above is published; the stable
core is `@zanii/{core,sdk,runtime,mcp-proxy}` + `zanii` (PyPI), and the rest are optional
add-ons (npm packages, and Python modules inside `zanii` with extras like `zanii[langchain]`).
Server: `https://ledger.zanii.agency`.

## The core workflow (memorize this)

1. **Identity** — `generateKeypair()` → an Ed25519 `did:key`. The DID *is* the public key (no lookup to verify).
2. **Delegation** — the owner signs a scoped, expiring cert granting the agent authority.
3. **Instrument** — create a `ZaniiAgent`, then `wrapTool(name, fn)` (every call receipted) or `record({target, payload})`.
4. **Verify** — `fetchAndVerifyProof(server, hash)` or `verifyAuditBundle(bundle)`, offline, zero trust.

**TypeScript:**
```ts
import { ZaniiAgent, generateKeypair, createCert, fetchAndVerifyProof } from '@zanii/sdk';

const owner = generateKeypair();
const agent = generateKeypair();
const cert = createCert(
  { issuer: owner.did, subject: agent.did, scopes: ['crm.*'], exp: '2027-01-01T00:00:00Z' },
  owner.privateKey,
);
const zanii = new ZaniiAgent({
  serverUrl: 'https://ledger.zanii.agency',
  agentDid: agent.did, agentPrivateKey: agent.privateKey,
  delegation: [cert], apiKey: process.env.ZANII_API_KEY,
});
const lookup = zanii.wrapTool('crm.lookup', (email: string) => crm.find(email)); // every call receipted
const { hash } = await zanii.record({ target: 'crm.lookup', payload: { email: 'a@b.co' } });
await zanii.flush();
const proof = await fetchAndVerifyProof('https://ledger.zanii.agency', hash);
if (!proof.ok) throw new Error(proof.error);
```

**Python:**
```python
from zanii import ZaniiAgent, fetch_and_verify_proof
from zanii.core import generate_keypair, create_cert

owner, agent = generate_keypair(), generate_keypair()
cert = create_cert(issuer=owner.did, subject=agent.did, scopes=["crm.*"],
                   exp="2027-01-01T00:00:00Z", issuer_private_key=owner.private_key)
zanii = ZaniiAgent(server_url="https://ledger.zanii.agency", agent_did=agent.did,
                   agent_private_key=agent.private_key, delegation=[cert], api_key=API_KEY)
receipt, h = zanii.record(target="crm.lookup", payload={"email": "a@b.co"})
zanii.flush()
assert fetch_and_verify_proof("https://ledger.zanii.agency", h).ok
```

## Accountability features (core/sdk/runtime 0.3.0 — know these)

- **`record()` salts the payload by default** now: `payload_hash = sha256(nonce ‖ payload)`, so two
  identical payloads differ on the log (privacy/PDPL). It returns/stores a `nonce` — pass a `nonceStore`
  (or keep the returned `nonce`) if you need to *prove* a payload later with `verifyPayload(payload, nonce, hash)`.
  Opt out with `record({ …, salt: false })` for a deterministic hash. Receipt validity is unchanged.
- **Owner-signed confirmations** (Article VI): `new Runtime(agent, { …, ownerDid })` makes `confirm()`
  require a valid `ActionConfirmation`. `propose()` returns `actionHash`; the owner signs it with
  `createConfirmation({ ownerId, actionHash, confirmedAt }, ownerKey)`; pass it to `confirm(cid, conf)`.
  It's recorded as an `action_confirmation` receipt — evidence a human approved.
- **Provenance + compliance anchoring**: `record({ …, provenance: { runtimeHash, modelId, manifestHash } })`
  or `new Runtime(agent, { manifestHash, runtimeHash, modelId, intentReceipts: true })` — stamps which
  rulebook governed each action; `intentReceipts` emits an `action_intent` before the tool runs (omission-evidence).
- **Segregation of duties**: `createCoSignature`/`verifyCoSignature` (an infra key co-signs a receipt; the
  co-signer must differ from the agent) + `reconcile(ledgerRefs, providerRefs)` in `@zanii/compliance`
  (surfaces unreported actions). SPEC §12 (confirmations), §13 (co-sign).

## Rules you MUST follow when writing Zanii code

1. **Never send raw payloads.** The ledger stores a **hash** (`payloadHash`) only; the data stays in the caller's systems. Pass the real payload to `record`/`wrapTool` — the SDK hashes it. Never put secrets/PII where you think the *hash input* is logged.
2. **Scopes gate targets.** A receipt's `target` must be covered by a delegation scope. `crm.*` covers `crm.lookup`; wildcards end in `.*`; `*` covers everything. An out-of-scope action is rejected.
3. **Delegation is owner→agent, scoped and expiring.** An agent can only *narrow* authority, never widen it. `exp` is required. Revocation is a first-class ledger entry.
4. **Writes need an API key** (`zk_live_…`) as `apiKey` / `api_key`. **Reads are public** (proofs, verify, stats, export) — no key.
5. **Receipts are content-addressed → idempotent.** Resubmitting the same receipt returns `{"status":"duplicate"}`, not an error. **Do not invent your own idempotency keys.**
6. **Always verify offline.** Never trust the server's assertion — use `verifyAuditBundle` / `fetchAndVerifyProof` (they check signature → delegation → scope → Merkle inclusion → signed tree head).
7. **Timestamps are UTC ISO-8601 with `Z`** (e.g. `2027-01-01T00:00:00Z`).
8. **For enforced action rules** (no-external-receipt→no-"sent", human gate for money/irreversible actions), use **`zanii.runtime` / `@zanii/runtime`** — do not hand-roll it. See `reference/*` .
9. **Keys are secrets.** Ed25519 private keys and `zk_live_`/`zk_admin_` keys are shown once — write them to files (mode 600) or a secrets manager, never hardcode or commit.

## Load these references when the task needs depth

- `reference/typescript.md` — full TS: SDK, verify, runtime, MCP proxy, cross-org receipts.
- `reference/python.md` — full Python equivalents (incl. `zanii.runtime`, `zanii.mcp_proxy`).
- `reference/api.md` — the ledger HTTP API (self-serve accounts, keys, webhooks, proofs, export, stats).
- `reference/patterns.md` — common patterns and the mistakes models make.
- `reference/ecosystem.md` — the optional packages (all published): `@zanii/{ai,webhooks,testing,monitor,react}`, the ten standalone (`cli,gateway,compliance,kms,witness,policy,otel,payments,embed,connectors`), the framework/privacy set (`langchain,openai-agents,retention,redact` + `zanii.crewai`), the standards-landing set (`a2a-directory,x402,erc8004`), the UAE-compliance set (`consent,admissibility,fta,walls`), `memory` (provable hash-chained agent memory), and the trust-boundary set (`kya,attest,swarm` — swarm has the on-ledger authority layer for `POST /v1/swarm`).
