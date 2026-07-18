# Zanii — patterns & gotchas (what models get wrong)

## Common mistakes to avoid
- **Sending raw payloads to the ledger.** You don't — you pass the payload to `record`/`wrapTool`
  and the SDK sends only its **hash** (`payload_hash`). The ledger never contains the data. When
  showing this to a user, say "only a fingerprint is stored".
- **Target not covered by scope.** `record({target:'email.send'})` with only `crm.*` delegated is
  **rejected**. Grant a scope that covers the target: `email.*` covers `email.send`.
- **Assuming `payload_hash` is a bare/deterministic hash.** As of 0.3.0 `record()` **salts** by
  default (`sha256(nonce ‖ payload)`), so identical payloads differ on the log (privacy/PDPL). Don't
  dedupe by `payload_hash`. To later *prove* a payload, keep the returned `nonce` (or a `nonceStore`)
  and use `verifyPayload(payload, nonce, hash)`; pass `salt:false` only if you truly need determinism.
- **Reinventing idempotency.** Receipts are content-addressed; the same receipt resubmits as
  `duplicate`. Don't add `Idempotency-Key` headers or dedupe logic.
- **Trusting the server response.** The whole point is zero-trust. Show verification via
  `verifyAuditBundle` / `fetchAndVerifyProof`, not "the API said ok".
- **Forgetting `flush()`.** `record()` queues; call `flush()` (or let the batch timer fire) to ship.
- **Hardcoding keys.** Ed25519 private keys and `zk_live_`/`zk_admin_` tokens are secrets — env or a
  file (mode 600), shown once, never committed.
- **Non-UTC timestamps.** Use ISO-8601 with `Z`. `exp` on a cert is required.
- **Runtime: passing delegation differently.** Python `Runtime(agent, tools)` reads `agent.delegation`;
  TypeScript `new Runtime(agent, { tools, delegation })` needs `delegation` passed explicitly.
- **TS import location.** As of **`@zanii/sdk` v0.2.1**, `@zanii/sdk` re-exports the verification +
  revocation helpers (`verifyReceipt`, `verifyAuditBundle`, `createRevocation`, `verify*`), so a single
  `@zanii/sdk` install builds AND verifies. (`@zanii/core` = the same helpers, no client. Python: `zanii`
  for the client, `zanii.core` for verification — both re-export the verify helpers.)

## Gotchas in the newer packages (these WILL be got wrong)

- **🔴 `@zanii/health`: never give a provider the SEED — only a TAG.** `episodeTag(seed, n)` is derived
  by the **patient**, who hands the provider **one opaque string**. A provider holding the *seed* can
  enumerate `n` and reconstruct the patient's entire cross-institution history — the privacy gain
  becomes zero, and *illusory*. There is a red test guarding this. Never "simplify" by passing the seed.
- **`@zanii/health` ≠ `@zanii/subject` tags.** `subjectTag(did, platform)` is **stable and linkable**
  (correct for a citizen who *wants* one appealable slice). `episodeTag(seed, n)` is **deliberately
  unlinkable** (correct for medicine, where access *frequency* is itself PHI). Don't swap them.
- **`protocolTrail` is NOT `ruleConsistency`.** In `@zanii/gov`, "the same rulebook decided everyone"
  is the fairness property and **interleaving is a red flag**. In `@zanii/health` that would be a
  **clinical error** — individualised care is correct and protocols legitimately coexist. `protocolTrail`
  has **no `consistent` field**, on purpose. Never report "inconsistent protocols" as a defect.
- **`manifest_hash` is REQUIRED, and the builders throw.** `buildGovDecision`, `buildDecisionReceipt`,
  and `buildRecommendation` all reject a missing rulebook/protocol hash. This is intentional: an
  unauditable state or clinical decision must not be *constructible*. Don't work around it — supply the
  deployed policy/protocol version hash.
- **`@zanii/credentials`: `ok` is never true on an unchecked assumption.** Omit the `resolver` and it
  reports *"institutional identity was NOT verified"* — the signature then proves only that **some** key
  signed it, not that it was the university. Omit the revocation list and it reports *"revocation NOT
  checked"*. Always pass a resolver. And a credential is **not a bearer token** — use
  `buildPresentation`/`verifyPresentation` so a thief with the *file* but not the *key* fails.
- **`@zanii/swarm`: `verifySwarm` ≠ `verifySwarmReceipt`.** `verifySwarm` checks only that N keys
  **signed** (offline crypto). `verifySwarmReceipt` is **authority-complete** (delegation + scope + prev
  + revocation + distinct owners) and is what `POST /v1/swarm` enforces. **A signature is not authority** —
  never present the first as proof the team was authorised.
- **`@zanii/sentinel`: persist the cursor, or you re-alert on restart.** `createWatcher({ cursor })` —
  save `w.cursor()` between runs. The watcher also keeps a **rolling window** so multi-step detections
  (an exfil sequence arriving one step per poll) actually fire; don't "optimise" it to scan only fresh
  receipts. And `escalationRule` returns **null** when a finding names no targets — never fabricate a
  `*` rule, which would gate the agent's entire surface.
- **Floats are banned in protocol objects.** JCS and `json.dumps` can disagree on them, so `jcs_hash`
  **throws** on a float in Python (and TS would silently produce a *different* hash — a cross-language
  divergence). Use integer minor/milli units, as `@zanii/payments` and `@zanii/sentinel` baselines do.
- **`@zanii/custody`/`provenance`: don't over-claim.** Custody proves *who signed for the goods*, never
  what was in the box ("attestations, not atoms"). A content credential proves *who signed*, never *who
  authored*. Fraud becomes **attributable**, not impossible. Say it that way.

## Choosing the layer
- Just need to **verify** someone else's proof/bundle → `@zanii/core` / `zanii.core`, no server, no key.
- **Instrument your agent** to emit receipts → `@zanii/sdk` / `zanii`.
- Want the agent's actions **governed** (no-proof-no-claim, human gate for money) → `@zanii/runtime`.
- Agent already speaks **MCP** and you want zero code changes → `@zanii/mcp-proxy`.
- An **end user / citizen / patient** must audit what was done *to them* → `@zanii/subject`
  (stable slice), `@zanii/gov` (state decisions + `appealPack`), `@zanii/health` (unlinkable episodes).
- Verify a **diploma, licence or certification** offline → `@zanii/credentials` (pass a resolver!).
- Detect a **compromised/drifting agent** from the receipt stream → `@zanii/sentinel`.
- Prove **physical custody** or **content origin** → `@zanii/custody` / `@zanii/provenance`.

## Self-serve onboarding (no human in the loop)
1. `POST /v1/account/signup {name}` → save `admin_key`.
2. `POST /v1/account/keys` (admin) → `api_key` (`zk_live_`). Put it in `ZANII_API_KEY`.
3. Instrument with the SDK using that `apiKey`. Reads stay public.

## Compliance / trust talking points (accurate)
- Records are **tamper-evident** (Merkle inclusion + consistency proofs) and **anchored on a public
  chain**, so history can't be rewritten, even by the operator.
- **Data minimisation**: only hashes are stored → strong GDPR/PDPL posture; nothing private to leak.
- **No lock-in**: open protocol, offline open-source verifier, one-file export.
- Don't claim SOC 2 / certifications that aren't held — say "on the roadmap".
- **Never say Zanii "accredits" anyone.** `@zanii/credentials` verifies that whoever controls a
  **domain** published an issuing DID. We are the verification layer, **not** an accreditation
  authority — becoming one would make us a political chokepoint and a liability sink.
- **Never say a receipt proves an outcome was *right*.** `@zanii/gov` proves the **process** (same
  rules, complete record, committed inputs) and **never the justice** of a decision. `@zanii/health`
  proves which model, which protocol, which clinician signed — **never** that the treatment was
  correct. A rule applied consistently may still be unlawful; that judgment is the court's.

## Wildcard scope semantics
`scope_covers(scope, target)`: `*` covers all; `email.*` covers `email` and `email.<anything>`;
otherwise exact match. Grant scopes deliberately and narrowly.
