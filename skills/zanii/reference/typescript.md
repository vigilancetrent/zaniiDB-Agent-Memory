# Zanii — TypeScript reference

Packages (npm): `@zanii/core`, `@zanii/sdk` (both **v0.4.0**), `@zanii/runtime` (**v0.3.0**), `@zanii/mcp-proxy`.
Import rule: **`@zanii/sdk` is a superset** — the `ZaniiAgent` client, `fetchAndVerifyProof`,
and (as of **v0.2.1**) all the protocol + verification helpers re-exported from core
(`generateKeypair`, `createCert`, `createRevocation`, `verifyReceipt`, `verifyAuditBundle`,
`verifySTH`, `verifyInclusion`, `verifyConsistency`, `verifyChain`, `verifyA2AReceipt`, …).
So **`@zanii/sdk` alone builds AND verifies.** Use `@zanii/core` only when you want the
pure helpers with no client (zero extra deps).

Optional add-ons (all published) live in `reference/ecosystem.md`: framework adapters
`@zanii/{ai,langchain,openai-agents,connectors}`, `@zanii/{webhooks,testing,monitor,react,cli,
gateway,compliance,kms,witness,policy,otel,payments,embed,retention,redact}`, the
standards-landing set `@zanii/{a2a-directory,x402,erc8004}`, the UAE-compliance set
`@zanii/{consent,admissibility,fta,walls}`, `@zanii/memory` (provable hash-chained agent memory),
the trust-boundary set `@zanii/{kya,attest,swarm}` (counterparty screening, which-code-ran,
N-party co-signed receipts — `swarm` v0.2.0 with the on-ledger authority layer for `POST /v1/swarm`),
the real-world provenance set `@zanii/{provenance,custody,decisions}` (content credentials,
supply-chain custody chains, auditable algorithmic decisions), `@zanii/sentinel`
(runtime behavioral monitoring), the institutional-trust set `@zanii/{credentials,gov}`
(domain-bound verifiable credentials; public-sector algorithmic accountability), and `@zanii/health`
(medical audit trails with per-episode *unlinkable* tags).

Accountability (0.3.0): `record()` **salts** the payload by default (keep the returned `nonce`
or pass a `nonceStore` to prove it later with `verifyPayload`; `salt: false` to opt out);
`createConfirmation`/`verifyConfirmation` + `new Runtime(agent, { ownerDid })` (signed human
approvals); receipt provenance via `record({ provenance: { manifestHash } })` /
`new Runtime(agent, { manifestHash, intentReceipts: true })`; `createCoSignature` +
`@zanii/compliance` `reconcile` (segregation of duties). SPEC §12/§13.

## Identity & delegation
```ts
import { generateKeypair, createCert, createRevocation } from '@zanii/sdk';

const kp = generateKeypair();                 // { privateKey: Uint8Array, publicKey, did: 'did:key:z…' }
const cert = createCert(
  { issuer: owner.did, subject: agent.did, scopes: ['email.*', 'crm.read'], exp: '2027-01-01T00:00:00Z' },
  owner.privateKey,                            // signed by the OWNER
);
const rev = createRevocation(cert, owner.privateKey);   // revoke: becomes a ledger entry
```

## Instrument an agent
```ts
import { ZaniiAgent } from '@zanii/sdk';

const zanii = new ZaniiAgent({
  serverUrl: 'https://ledger.zanii.agency',
  agentDid: agent.did,
  agentPrivateKey: agent.privateKey,
  delegation: [cert],
  apiKey: process.env.ZANII_API_KEY,           // zk_live_… — required for writes
  // flushMs?: 300, flushSize?: 20, fetchImpl?: custom fetch
});

// (a) wrap a tool — every call is signed + recorded (result on success, error on failure)
const sendEmail = zanii.wrapTool('email.send', (to: string, subj: string) => mail.send(to, subj));
await sendEmail('a@b.co', 'Hi');

// (b) record explicitly
const { receipt, hash } = await zanii.record({ target: 'crm.lookup', payload: { email: 'a@b.co' } });
await zanii.flush();                            // ship queued receipts
```

## Verify (offline, zero trust)
```ts
import { fetchAndVerifyProof, verifyReceipt, verifyAuditBundle } from '@zanii/sdk';

const proof = await fetchAndVerifyProof('https://ledger.zanii.agency', hash); // fetch + verify
if (!proof.ok) throw new Error(proof.error);

const r = verifyReceipt(receipt);              // just signature + delegation + scope, no network
const report = verifyAuditBundle(bundle);      // a whole exported history, offline
report.ok; report.checks; report.stats;
```

## Deterministic runtime — `@zanii/runtime`
The model proposes; tested code disposes. Status is EARNED from the tool's result.
```ts
import { Runtime, tool, type ToolResult } from '@zanii/runtime';

const send = tool('email.send', 'email.*', async ({ to }): Promise<ToolResult> => {
  const providerId = await mail.send(to as string);   // your integration
  return { ok: true, receiptId: providerId };         // provider receipt ⇒ status 'sent'
}, { irreversible: true });                            // money/messages/deletes ⇒ human gate

const rt = new Runtime(zanii, { tools: [send], delegation: [cert] }); // pass delegation explicitly (TS)
let d = await rt.propose('email.send', { to: 'a@b.co' }, { intent: 'follow up', confidence: 0.9 });
// irreversible ⇒ d.status === 'awaiting_confirmation'; nothing sent yet
d = await rt.confirm(d.confirmationId!);              // owner says yes ⇒ d.status === 'sent', recorded
```
Status: no `receiptId` ⇒ `attempted` (never `sent`); `confirmed:true` ⇒ `confirmed`; thrown ⇒ `failed`;
`partial:true` ⇒ `partial`. Unknown/out-of-scope tool ⇒ `rejected`; low `confidence` ⇒ `clarify`.

## MCP proxy — `@zanii/mcp-proxy`
Front any MCP server so every tool call is receipted, with no agent changes.
```ts
import { createZaniiProxy } from '@zanii/mcp-proxy';
const proxy = createZaniiProxy(upstreamClient, zanii); // upstream = connected @modelcontextprotocol Client
// serve `proxy` to your agent in place of the real server; each call recorded as mcp.<tool>
```

## Cross-org (A2A) receipts
Two agents from different orgs co-sign one neutral receipt (`POST /v1/interactions`). See
`@zanii/core` `buildA2ABody` / `signA2ABody` / `assembleA2AReceipt` / `verifyA2AReceipt`.
