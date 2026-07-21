"""Tests for procedural recall (skill injection), outcome tagging, and
staleness-based auto-offload."""
import json

import httpx

from zanii_memory.autooffload import AutoOffloader
from zanii_memory.core import MemoryCore
from zanii_memory.llm import LLMClient
from zanii_memory.pipeline.skills import _memory_line, find_relevant_skill, run_skills
from zanii_memory.store import SqliteStore
from zanii_memory.types import MemoryRecord

DEPLOY_SKILL = """## SKILL: Deploy the billing service
**When to use**: deploying billing to production
**Procedure**:
1. Run the canary pipeline
2. Promote after 15 clean minutes
**Pitfalls**: never deploy on Fridays (2026-05 incident)
"""


# ---- 1. skill injection at recall ----

def make_skills(cfg):
    cfg.skills_dir.mkdir(parents=True, exist_ok=True)
    (cfg.skills_dir / "deploy-billing.md").write_text(DEPLOY_SKILL, encoding="utf-8")
    (cfg.skills_dir / "format-reports.md").write_text(
        "## SKILL: Format weekly reports\n**When to use**: writing the weekly report\n"
        "**Procedure**:\n1. Bullet points only\n", encoding="utf-8")


def test_find_relevant_skill_matches_and_thresholds(cfg):
    make_skills(cfg)
    hit = find_relevant_skill(cfg.skills_dir, "how do I deploy the billing service?")
    assert hit and "canary pipeline" in hit
    assert find_relevant_skill(cfg.skills_dir, "what wine pairs with fish?") is None  # weak match -> nothing
    assert find_relevant_skill(cfg.skills_dir / "missing", "deploy billing") is None


async def test_recall_injects_learned_procedure(cfg):
    core = MemoryCore(cfg)
    await core.initialize()
    make_skills(cfg)
    r = await core.recall("time to deploy the billing service", "s1")
    assert "Learned procedure" in r.append_system_context
    assert "never deploy on Fridays" in r.append_system_context

    r2 = await core.recall("completely unrelated cooking question", "s1")
    assert "Learned procedure" not in r2.append_system_context
    await core.close()


async def test_recall_skills_can_be_disabled(cfg):
    core = MemoryCore(cfg.model_copy(update={"recall_skills": False}))
    await core.initialize()
    make_skills(core.cfg)
    r = await core.recall("deploy the billing service", "s1")
    assert "Learned procedure" not in r.append_system_context
    await core.close()


# ---- 2. outcome tagging ----

def test_memory_line_carries_outcome():
    row = {"type": "episodic", "scene_name": "deploys", "content": "Canary deploy succeeded",
           "metadata": json.dumps({"outcome": "success"})}
    assert _memory_line(row) == "- [episodic|success|deploys] Canary deploy succeeded"
    row["metadata"] = json.dumps({"outcome": "bogus"})
    assert "|bogus|" not in _memory_line(row)  # only success/failure pass through
    row["metadata"] = "not json"
    assert _memory_line(row).startswith("- [episodic|deploys]")


async def test_run_skills_prompt_includes_outcome_tags(cfg, tmp_path):
    store = SqliteStore(tmp_path / "s.db")
    store.insert_l1(MemoryRecord(content="Deployed with canary, worked", type="episodic",
                                 metadata={"outcome": "success"}, scene_name="deploys"))
    store.insert_l1(MemoryRecord(content="Friday deploy broke prod", type="episodic",
                                 metadata={"outcome": "failure"}, scene_name="deploys"))
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["prompt"] = json.loads(request.content)["messages"][-1]["content"]
        return httpx.Response(200, json={"choices": [{"message": {"content": "NONE"}}]})

    llm = LLMClient(cfg.model_copy(update={"llm_base_url": "http://mock/v1", "llm_api_key": "k", "llm_model": "m"}))
    llm._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    await run_skills(store, llm, cfg)
    assert "[episodic|success|deploys]" in captured["prompt"]
    assert "[episodic|failure|deploys]" in captured["prompt"]
    await llm.close()
    store.close()


# ---- 3. staleness-based auto-offload ----

async def test_stale_tool_outputs_are_offloaded(cfg):
    core = MemoryCore(cfg)
    await core.initialize()
    auto = AutoOffloader(core, "t1", threshold_chars=10_000, stale_after_messages=3)
    msgs = (
        [{"role": "tool", "content": "old tool result " * 20, "name": "grep"}]      # stale, small
        + [{"role": "user", "content": "old user message " * 20}]                    # user: never touched
        + [{"role": "assistant", "content": "ok"}] * 3
        + [{"role": "tool", "content": "fresh tool result " * 20}]                   # recent, small
    )
    out = await auto.filter_messages(msgs)
    assert out[0]["content"].startswith("[offloaded:N")          # stale -> stubbed despite being small
    assert out[1]["content"] == msgs[1]["content"]               # user content untouched
    assert out[-1]["content"] == msgs[-1]["content"]             # fresh -> untouched
    node_id = out[0]["content"].split("]")[0].split(":")[1]
    assert "old tool result" in (await core.retrieve_ref(node_id))  # drill-down intact
    # disabled by default: same list, no staleness rule
    auto_off = AutoOffloader(core, "t2", threshold_chars=10_000)
    out2 = await auto_off.filter_messages(msgs)
    assert out2[0]["content"] == msgs[0]["content"]
    await core.close()
