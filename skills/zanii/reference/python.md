# Zanii — Python reference

Package (PyPI): `zanii`. Submodules: `zanii.core` (pure verify), `zanii.runtime`
(rails), `zanii.mcp_proxy` (needs `pip install "zanii[mcp]"`). Ships `py.typed`.
Ecosystem modules (published, `zanii` 0.15.0): `zanii.{webhooks,testing,monitor,cli,
compliance,kms,witness,policy,payments,embed,connectors,retention,redact,a2a_directory,
x402,erc8004,consent,admissibility,fta,walls,memory,kya,attest,swarm,subject,provenance,custody,decisions,sentinel,credentials,gov,health}`; opt-in extras `zanii.otel` (`zanii[otel]`) and framework adapters
`zanii.langchain` (`zanii[langchain]`), `zanii.openai_agents` (`zanii[openai-agents]`),
`zanii.crewai` (`zanii[crewai]`) — see `reference/ecosystem.md`.

Accountability (0.6.0): `record()` **salts** the payload by default (keep the returned nonce or
pass `nonce_store=` to prove a payload later with `verify_payload`; `salt=False` to opt out);
`create_confirmation`/`verify_confirmation` + `Runtime(owner_did=…)` (signed human approvals);
receipt provenance via `record(provenance={"manifest_hash":…})` / `Runtime(manifest_hash=…,
intent_receipts=True)`; `create_cosignature` + `zanii.compliance.reconcile` (segregation of duties).
The `zanii` console script mirrors the CLI (`zanii keygen`,
`zanii verify <hash>`, …).

## Identity & delegation
```python
from zanii.core import generate_keypair, create_cert, create_revocation

kp = generate_keypair()                        # Keypair(private_key: bytes, public_key, did='did:key:z…')
cert = create_cert(
    issuer=owner.did, subject=agent.did,
    scopes=["email.*", "crm.read"], exp="2027-01-01T00:00:00Z",
    issuer_private_key=owner.private_key,       # signed by the OWNER
)
rev = create_revocation(cert, owner.private_key)   # becomes a ledger entry
```

## Instrument an agent
```python
from zanii import ZaniiAgent

zanii = ZaniiAgent(
    server_url="https://ledger.zanii.agency",
    agent_did=agent.did, agent_private_key=agent.private_key,
    delegation=[cert],
    api_key=API_KEY,                            # zk_live_… — required for writes
)
# (a) wrap a tool (sync or async) — every call signed + recorded
lookup = zanii.wrap_tool("crm.lookup", crm.find)
lookup("a@b.co")
# (b) record explicitly
receipt, h = zanii.record(target="crm.lookup", payload={"email": "a@b.co"})
zanii.flush()
```

## Verify (offline, zero trust)
```python
from zanii import fetch_and_verify_proof
from zanii.core import verify_receipt, verify_audit_bundle

assert fetch_and_verify_proof("https://ledger.zanii.agency", h).ok
assert verify_receipt(receipt).ok              # signature + delegation + scope, no network
report = verify_audit_bundle(bundle)           # a whole exported history, offline
assert report.ok, [c for c in report.checks if not c["ok"]]
```

## Deterministic runtime — `zanii.runtime`
```python
from zanii.runtime import Runtime, Tool, ToolResult, tool

def send(to):
    provider_id = mail.send(to)                # your integration
    return ToolResult(ok=True, receipt_id=provider_id)   # provider receipt ⇒ 'sent'

rt = Runtime(zanii, [Tool("email.send", "email.*", send, irreversible=True)])  # reads agent.delegation
d = rt.propose("email.send", {"to": "a@b.co"}, intent="follow up", confidence=0.9)
# irreversible ⇒ d.status == "awaiting_confirmation"; nothing sent yet
d = rt.confirm(d.confirmation_id)              # owner yes ⇒ d.status == "sent", recorded
```
Status: no `receipt_id` ⇒ `attempted` (never `sent`); `confirmed=True` ⇒ `confirmed`;
raised ⇒ `failed`; `partial=True` ⇒ `partial`. Unknown/out-of-scope ⇒ `rejected`; low confidence ⇒ `clarify`.
`tool(name, scope, run, *, irreversible=False)` is a helper that builds a `Tool`.

## MCP proxy — `zanii.mcp_proxy` (`pip install "zanii[mcp]"`)
```python
from zanii.mcp_proxy import create_zanii_proxy
proxy = create_zanii_proxy(upstream_session, zanii)   # upstream = connected mcp ClientSession
# or run standalone over stdio:
#   python -m zanii.mcp_proxy -- npx some-mcp-server   (env ZANII_SERVER / ZANII_IDENTITY / ZANII_API_KEY)
```

## Notes
- `ZaniiAgent` is synchronous (urllib); `record()` syncs the chain head on first call, then batches.
- `wrap_tool` handles both sync and async functions.
- Cross-org (A2A): `zanii.core` has `build_a2a_body` / `sign_a2a_body` / `assemble_a2a_receipt` / `verify_a2a_receipt`.
