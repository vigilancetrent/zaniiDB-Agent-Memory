# Zanii Agent Skill

A portable **Agent Skill** that makes any AI coding assistant a Zanii expert. Drop
it into your agent's skills directory and, whenever a task involves verifiable AI
agents / proof-of-action / the `@zanii/*` or `zanii` SDKs, the model gets the right
mental model, real API signatures, and the rules it must follow — injected
automatically, so you don't re-explain Zanii every session.

Progressive disclosure: `SKILL.md` (short — always considered) points to
`reference/*.md` (loaded only when a task needs the depth).

```
skills/zanii/
  SKILL.md                 # mental model, workflow, the rules
  reference/typescript.md  # @zanii/sdk · core · runtime · mcp-proxy
  reference/python.md      # zanii · zanii.core · zanii.runtime · zanii.mcp_proxy
  reference/api.md         # the ledger HTTP API
  reference/patterns.md    # patterns + gotchas models get wrong
```

## Install it

**Claude Code** — copy the folder into a skills directory:
```sh
# this project only
mkdir -p .claude/skills && cp -r skills/zanii .claude/skills/
# or for every project (personal)
mkdir -p ~/.claude/skills && cp -r skills/zanii ~/.claude/skills/
```
Claude Code discovers it by the `description` in `SKILL.md` and loads it when relevant.

**Codex / other agents** — point the agent's skill/instructions mechanism at
`skills/zanii/SKILL.md`, or paste its contents into the project's `AGENTS.md` (Codex
reads `AGENTS.md`). The reference files can be linked or included as needed.

**Any agent** — the skill is plain Markdown; include `SKILL.md` in the model's
context (system prompt / tool docs) and load `reference/*.md` on demand.

## Keep it accurate

The skill is written for the **published SDKs** (`@zanii/{core,sdk}` `v0.4.0`, `zanii` `0.15.0`). If the SDK
API or the HTTP API changes, update `SKILL.md` and the matching `reference/*.md` in
the same change — the whole value of a skill is that it's *correct*.

## Distribute it

- Ship it alongside the SDK docs, or publish it to a skills marketplace / plugin.
- Because it's self-contained Markdown, users need nothing installed to benefit —
  their coding agent just gets better at Zanii.
