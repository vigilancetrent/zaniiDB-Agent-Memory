# ZaniiDB Agent Skill

A portable **Agent Skill** that makes any AI coding assistant a ZaniiDB Agent
Memory expert. Drop it into your agent's skills directory and, whenever a task
involves agent memory / recall / the `zaniidb-agent-memory` package, the model
gets the right mental model, real API signatures, and the rules it must follow.

Progressive disclosure: `SKILL.md` (short — always considered) points to
`reference/*.md` (loaded only when a task needs the depth).

```
skills/zaniidb/
  SKILL.md               # mental model, workflow, the rules
  reference/python.md    # SDK, hooks, auto-offload, store protocol, pipeline
  reference/api.md       # gateway HTTP API, MCP tools, CLI
  reference/patterns.md  # patterns + gotchas models get wrong
```

## Install it

**Claude Code** — copy the folder into a skills directory:
```sh
# this project only
mkdir -p .claude/skills && cp -r skills/zaniidb .claude/skills/
# or for every project (personal)
mkdir -p ~/.claude/skills && cp -r skills/zaniidb ~/.claude/skills/
```

**Codex / other agents** — point the agent's skill/instructions mechanism at
`skills/zaniidb/SKILL.md`, or paste its contents into the project's `AGENTS.md`.

**Any agent** — plain Markdown; include `SKILL.md` in the model's context and
load `reference/*.md` on demand.

## Keep it accurate

Written for `zaniidb-agent-memory` **0.10.0**. If the SDK, gateway routes, or
env vars change, update `SKILL.md` and the matching `reference/*.md` in the
same change — the whole value of a skill is that it's *correct*.
