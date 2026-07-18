# Zanii — HTTP API reference

Base URL `https://ledger.zanii.agency`. JSON in/out. Auth via `Authorization: Bearer <token>`.
Prefer the SDKs for anything that builds/verifies proofs; use raw HTTP for account/webhook/dashboard UIs.

## Auth model
- `zk_live_…` (ingest key) → writing receipts.
- `zk_admin_…` (admin key) → managing your org: keys, usage, webhooks.
- No key → all reads, proofs, public pages, stats.

## Accounts (self-serve)
- `POST /v1/account/signup` `{name}` → `{org_id, admin_key}` (**admin_key shown once**).
- `POST /v1/account/keys` (admin) `{label, scopes?:["write"]}` → `{api_key}` (**shown once**).
- `GET /v1/account/keys` (admin) → `{keys:[{id,label,scopes,created_at,last_used_at,revoked}]}`.
- `DELETE /v1/account/keys/{id}` (admin) → `{revoked:true}`.
- `GET /v1/account/usage?since=YYYY-MM-DD` (admin) → `{since,total,by_day:[{day,count}]}`.
- `GET /v1/account/me` (admin) → `{org_id,name,plan,active_keys,usage_30d}`.

## Webhooks (admin) — receipt.recorded / receipt.rejected
- `POST /v1/account/webhooks` `{url(https),events?}` → `{id,secret}` (**shown once**). Only public https URLs.
- `GET /v1/account/webhooks` · `DELETE /v1/account/webhooks/{id}`.
- Each delivery has `X-Zanii-Event` and `X-Zanii-Signature: sha256=<HMAC-SHA256(secret, raw_body)>`. **Verify it.**
- Body: `{event, ts, data:{hash,index,agent_id,action,target,ts}}`.

## Writing (ingest key)
- `POST /v1/receipts` `{receipts:[Receipt]}` (max 100) → `{results:[{status:accepted|duplicate|rejected,hash,index,error?}], sth}`.
- `POST /v1/interactions` `{receipt}` (A2A **2-party** co-signed) → `{status,hash,index,sth}`.
- `POST /v1/swarm` `{receipt}` (**N-party** M-of-N co-signed, SPEC §14) → `{status,hash,index,sth}`.
  Verifies **authority per signer** (sig + owner-rooted delegation + target-in-scope + `prev` == chain
  head + not revoked), then `threshold`, then **distinct owners** (default on — one owner's N agents
  cannot fake an M-of-N). Build with `@zanii/swarm` `buildSwarmReceipt`.
- `POST /v1/revocations` `{revocation}` → `{status,cert_hash,index,sth}`.
- `POST /v1/anchor` (**admin** key) → forces an on-chain anchor of the current STH.

## Reading & proofs (public)
- `GET /v1/sth` → `{v,log_id,size,root,ts,sig}` (signed tree head).
- `GET /v1/proof/{hash}` → `{receipt,hash,index,proof:[…],sth}` (verify offline).
- `GET /v1/consistency?first={size}` → `{first,first_root,second,second_root,proof}` (append-only proof).
- `GET /v1/head/{did}` → `{head}` · `GET /v1/recent?limit=20` · `GET /v1/agents`.
- `GET /v1/reputation/{did}` → `{receipts,a2a_interactions,distinct_counterparties,first_ts,last_ts,revoked,fully_anchored,…}`.
- `GET /v1/subjects/{tag}?limit=200` → `{subject_tag,count,receipts:[{receipt,hash,index}],first_ts,last_ts,sth}`.
  The **per-subject slice**: every receipt stamped with that `subject_tag`. **Public** — the log is
  public, so the *unguessable, platform-scoped tag* is the privacy boundary, and clients **verify every
  returned receipt offline** (`@zanii/subject` `fetchSubjectHistory` does this: signature + delegation +
  tag match; a receipt bearing a different tag is flagged, never silently shown).
  The index is **tag-agnostic** — it also serves `@zanii/custody` item tags and `@zanii/health`
  *per-episode* tags (see patterns.md: episode tags are deliberately **unlinkable**).
- `GET /v1/export/{did}` → the agent's full **audit bundle** (verify with `verifyAuditBundle`).
- `GET /v1/anchors` · `GET /v1/revocations` · `GET /v1/stats` (`{receipts,agents,anchors,last_anchor_ts,last_receipt_ts}`) · `GET /v1/stream` (SSE live feed).

## Public pages / embeds (no key)
`/verify/{hash}` (proof page + QR), `/agent/{did}` (shareable profile), `/badge/{did}.svg`,
`/qr/{hash}.svg`, `/dashboard` (live console).

## Data shapes
- **Receipt**: `{v,agent_id,delegation:[Cert],action,target,payload_hash,ts,prev,sig}` — `payload_hash` is a **salted** hash (`sha256(nonce‖payload)`, nonce off-log); the payload never leaves your systems. Optional provenance fields when set: `runtime_hash`, `model_id`, `manifest_hash` (covered by the signature).
- **Cert**: `{v,issuer,subject,scopes,exp,sig}`.
- Identities `did:key` (Ed25519); hashes `sha256:…` over RFC 8785 (JCS) canonical JSON.

## Errors
`{error}` with `400` (validation), `401` (bad/missing key), `403` (scope), `404`, `422` (verification failed), `429` (rate limit), `503` (feature off).
