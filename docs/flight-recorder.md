# The Agent Flight Recorder

**Make AI agents insurable.** When an autonomous agent causes a loss, three
questions decide the claim — and today nobody can answer them with evidence:

1. **What did the agent know?** (the memory it acted on)
2. **What did it do?** (the actions it took, in order)
3. **What was it authorized to do?** (the authority it held at that moment)

Zanii is the black-box recorder that answers all three — cryptographically,
offline, without trusting the operator.

## How each question is answered

| Question | Evidence | Property |
| :--- | :--- | :--- |
| What did it know? | ZaniiDB provable memory — every memory write/supersede/quarantine emits a hash-chained receipt | Memory history can't be rewritten after the incident |
| What did it do? | Zanii ledger receipts — every action signed by the agent's did:key, Merkle-anchored | Actions can't be added, removed, or reordered |
| What was it authorized to do? | Owner-signed scoped, expiring delegation certs + confirmation receipts | Authority at time-of-action is provable; human approvals are on the record |

Plus the **Memory Firewall**: injection attempts are quarantined *and receipted* —
the record shows not just what the agent believed, but what it was fed and refused.

## The replay

One command reconstructs the incident timeline from the local chain and verifies
it end-to-end before showing a single row:

```console
$ zanii-memory replay --since 2026-07-20T00:00:00Z
=== ZaniiDB Flight Recorder — memory replay ===
Agent:   did:key:z6Mk…
Chain:   4 receipts, VERIFIED — chain intact
Window:  2026-07-20T00:00:00Z .. now — 4 events

2026-07-20T09:00:00Z  [receipt #   0] l1.insert           sha256:37f34caac8729871…
2026-07-20T09:05:00Z  [receipt #   1] l1.seed             sha256:ee6b8c5b53cb25a5…
2026-07-21T14:30:00Z  [receipt #   2] l1.supersede        sha256:588b827224bf2a9f…
2026-07-21T15:00:00Z  [receipt #   3] firewall.quarantine sha256:5bc4469705e3e7b2…
```

A tampered record doesn't produce a subtly wrong report — it fails loudly, naming
the exact entries:

```console
Chain:   4 receipts, TAMPERED: ['entry 1: entry_hash does not match its contents',
         'entry 2: broken link (prev does not match previous entry_hash)']
```

`--json` emits the same timeline machine-readable for claims tooling. Verification
is **offline and zero-trust** — an adjuster runs it without believing the operator
or even Zanii's servers. Privacy holds both ways: the public ledger carries only
salted commitments (business data never leaves the insured's systems), yet any
disputed memory can be *proven* against its commitment using the locally-held salt.

## Why insurers, why now

AI-liability policies are being written today with **zero actuarial evidence
infrastructure**. Underwriters price blind; claims are he-said-she-said against
an operator's mutable logs. A policy that requires the flight recorder gets:

- **Underwriting**: verified capability history instead of a questionnaire
- **Claims**: replayable incident evidence instead of the operator's word
- **Subrogation**: proof of *whose* authority the agent exceeded — operator error,
  owner over-delegation, or third-party injection (firewall receipts)
- **UAE**: records are evidence-grade for Federal Law 46/2021 electronic-record
  workflows (`@zanii/admissibility` produces the bilingual court-ready pack)

The operator's incentive mirrors the insurer's: run the recorder, get the premium
discount — the same dynamic as telematics in motor insurance.

## Pilot shape (2 weeks)

1. Operator installs `zaniidb-agent-memory[provable]` + the Zanii SDK — receipts
   flow from day one; no workflow change.
2. Insurer receives the replay for one simulated incident: memory timeline,
   action receipts, delegation state, firewall record.
3. Both sides verify offline, independently.

**Contact:** info@zanii.agency · ledger: https://ledger.zanii.agency
