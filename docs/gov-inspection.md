# ZaniiDB Agent Memory — Technical Dossier for Regulatory Inspection

Reference document for government inspectors, auditors, and compliance
assessors evaluating a deployment of `zaniidb-agent-memory`. It describes the
system's architecture, data handling, security controls, and — most
importantly — the **verification procedures an inspector can execute
independently**, without trusting the operator or the vendor.

*This document describes technical capabilities. It is not legal advice.*

---

## 1. System overview

ZaniiDB Agent Memory is a self-hosted memory engine for AI agents. It captures
agent conversations, distills them into structured "memories" using a language
model, and supplies relevant memories back to the agent. All data is processed
and stored **on infrastructure the operator controls**.

Layered data model:

| Layer | Content | Storage |
| :--- | :--- | :--- |
| L0 | Raw conversation turns | Operator's database |
| L1 | Extracted atomic memories (facts, events, standing instructions) | Operator's database |
| L2 | Scene summaries | Operator's database |
| L3 | Persona profile | `persona.md` file in the data directory |

Backends: SQLite (single file, default `~/.zanii/memory`) or PostgreSQL with
pgvector. Version under inspection: `pip show zaniidb-agent-memory`.

## 2. Data residency and third-party flows

- **Memory content never leaves the operator's systems** except as inputs to
  the operator-configured LLM/embedding endpoints (which may themselves be
  self-hosted, e.g. Ollama, for a fully air-gapped deployment).
- With the optional provable-memory feature enabled, the only data transmitted
  to the transparency ledger is a **salted SHA-256 commitment** of each memory
  — a one-way hash. Raw content, names, and identifiers are not transmitted
  and cannot be derived from the commitment.
- No telemetry, analytics, or vendor callbacks exist in the software.

## 3. Security controls

### 3.1 Memory Firewall (anti-poisoning)

Defends the memory store against injection of malicious "memories" by
untrusted content (documents, web pages, tickets). Three enforcement layers:

1. **Source binding** — memories are accepted only from channels the operator
   declared trusted (`ZANII_FIREWALL_TRUSTED_CHANNELS`, default
   `user,assistant`). Content from other channels is quarantined by policy.
2. **Injection screening** — deterministic signature screening for known
   injection patterns in English and Arabic, including de-obfuscation of
   spaced-letter evasion; an additional LLM-based screen is available
   (`ZANII_FIREWALL_LLM_SCREEN`).
3. **Quarantine gate** — suspect memories are held outside recall until a
   human reviews them (`zanii-memory quarantine list | release | reject`).
   Nothing is silently deleted; nothing suspect silently enters recall.

Red-team methodology and measured coverage (attack corpus, per-language
results, false-positive rates) are published in `docs/firewall-redteam.md`.

### 3.2 Integrity and non-repudiation (provable memory)

With the `[provable]` extra enabled, every memory mutation (insert, seed,
supersede, persona update, firewall rejection) emits a **hash-chained receipt**:

- Each entry commits to its content (salted SHA-256), links to the previous
  entry's hash, and carries a monotonic sequence number and UTC timestamp.
- Receipts are signed with the agent's Ed25519 `did:key` identity and appended
  to a Merkle transparency log (`ledger.zanii.agency` or an operator-hosted
  ledger). The full entries, including proof salts, are retained locally in
  `<data_dir>/ledger_entries.jsonl`.
- **Any post-hoc modification of the record is detectable**: editing, deleting,
  or reordering an entry breaks the hash chain at a named position.

### 3.3 Access control and audit

- HTTP gateway supports bearer-token authentication (`ZANII_GATEWAY_API_KEY`);
  the health endpoint alone is unauthenticated.
- An operation audit log is available (`ZANII_AUDIT_ENABLED=true`;
  inspect with `zanii-memory audit`).
- Historic (superseded) memories are retained, not destroyed: corrections
  create a new memory and mark the old one superseded, preserving the history
  for audit while excluding it from recall.

## 4. Inspector verification procedures (independent, offline)

These commands require no cooperation from the vendor and no network trust.

**V1 — Chain integrity.** Verify no memory record was altered after the fact:

```console
$ zanii-memory ledger-verify
128 entries: OK — chain intact          # or: TAMPERED: [named entries] → exit 1
```

**V2 — Incident replay.** Reconstruct what the agent remembered and did over a
period, from verified records only:

```console
$ zanii-memory replay --since 2026-07-01T00:00:00Z --json
```

The command verifies the chain **before** rendering; a tampered record fails
loudly with the exact broken entries and a non-zero exit code.

**V3 — Content proof.** For a disputed memory, the operator discloses the
content and its locally-held salt; the inspector recomputes the salted SHA-256
and compares it to the commitment in the on-ledger receipt. A match proves the
disclosed content is byte-identical to what was recorded at the receipt's
timestamp. Undisclosed memories remain confidential — disclosure is selective.

**V4 — Ledger inclusion.** Receipts can be checked against the transparency
log's signed Merkle root using the open-source `zanii` SDK
(`fetch_and_verify_proof`) — offline verification of signature, authority
scope, and inclusion. Ledger reads are public and require no credentials.

**V5 — Firewall efficacy.** Re-run the published red-team harness
(`scripts/redteam.py`) against the deployed configuration and compare results
with `docs/firewall-redteam.md`.

## 5. Data subject and retention capabilities

- **Export/erasure:** `zanii-memory export` produces a complete portable JSON
  of all stored memory; deleting the data directory (or database) removes all
  content. On-ledger commitments are anonymous one-way hashes and contain no
  personal data.
- **Correction:** supersede semantics record corrections without falsifying
  history — relevant to record-keeping obligations.
- **Multi-tenancy isolation:** one database/data directory per tenant by
  design; there is no shared-store tenancy mode.

## 6. Regulatory context (UAE)

- Receipts, delegation certificates, and the verification procedures above are
  designed for **evidence-grade use** in electronic-record workflows under UAE
  Federal Law No. 46 of 2021 (Electronic Transactions and Trust Services);
  bilingual (AR/EN) evidence packaging is available via the Zanii
  `admissibility` tooling.
- The salted-commitment design (no personal data on the ledger, selective
  disclosure, erasure of local content) supports PDPL-aligned data-protection
  postures. Determinations of legal sufficiency rest with counsel and the
  competent authority.

## 7. Contact

Technical inquiries and inspection support: **info@zanii.agency**
Source and documentation: https://github.com/vigilancetrent/zaniiDB-Agent-Memory · Ledger: https://ledger.zanii.agency
