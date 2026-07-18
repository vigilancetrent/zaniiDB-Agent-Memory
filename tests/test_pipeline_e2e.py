"""Full LLM-pipeline end-to-end test against an OpenAI-compatible test double.

No network, no API keys: an httpx.MockTransport plays the role of the LLM and
embeddings endpoints, so every production code path runs for real — request
construction, extraction parsing, priority filtering, semantic dedup with live
sqlite-vec vectors, scene files, persona generation, skill distillation, and
hybrid recall.
"""
import hashlib
import json
import math
import re

import httpx
import pytest

from zanii_memory.config import Settings
from zanii_memory.core import MemoryCore

DIMS = 8

FACT_PERSONA = "The user (Rin) leads the platform team at Zanii"
FACT_PERSONA_DUP = "The User (Rin) leads the platform team at Zanii!"  # same after normalization
FACT_EPISODIC = "The user (Rin) migrated the search cluster to Postgres on 2026-07-15"
FACT_INSTRUCTION = "The user requires the AI to summarize deploys in three bullet points"

EXTRACTION_JSON = json.dumps(
    [
        {
            "scene_name": "I am helping Rin run Zanii's platform",
            "memories": [
                {"content": FACT_PERSONA, "type": "persona", "priority": 85, "metadata": {}},
                {"content": FACT_PERSONA_DUP, "type": "persona", "priority": 80, "metadata": {}},
                {"content": FACT_EPISODIC, "type": "episodic", "priority": 75, "metadata": {}},
                {"content": FACT_INSTRUCTION, "type": "instruction", "priority": 90, "metadata": {}},
                {"content": "The user said hello", "type": "episodic", "priority": 20, "metadata": {}},
            ],
        }
    ]
)

PERSONA_MD = """# User Narrative Profile

> **Archetype**: Rin, the pragmatic platform lead who automates everything.

## Chapter 1: Context & Current State
Rin leads Zanii's platform team and recently migrated search to Postgres."""

SKILLS_MD = """## SKILL: Summarize deploys
**When to use**: after any deployment
**Procedure**:
1. State what shipped
2. Three bullet points only
**Constraints**: the user's standing formatting rule"""


FACT_MOVED = "The user (Rin) moved to the mobile team at Zanii"
MOVED_JSON = json.dumps(
    [
        {
            "scene_name": "I am helping Rin run Zanii's platform",
            "memories": [{"content": FACT_MOVED, "type": "persona", "priority": 85, "metadata": {}}],
        }
    ]
)

_BASE_A = [1.0] + [0.0] * (DIMS - 1)
# cosine(A, B) = 0.7 -> distance 0.3: above dedup (0.12), inside supersede window (0.45)
_BASE_B = [0.7, 0.7141] + [0.0] * (DIMS - 2)


def fake_embedding(text: str) -> list[float]:
    """Deterministic unit vector; identical after normalization -> identical vector.
    The platform-team and mobile-team facts are pinned at cosine 0.7 so the
    contradiction pair lands between the dedup and supersede thresholds."""
    normalized = re.sub(r"[^\w\s]", "", text.lower()).strip()
    if "platform team" in normalized:
        return list(_BASE_A)
    if "mobile team" in normalized:
        return list(_BASE_B)
    digest = hashlib.sha256(normalized.encode()).digest()
    vec = [digest[i] - 128.0 for i in range(DIMS)]
    norm = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [x / norm for x in vec]


@pytest.fixture
def mock_env(tmp_path):
    requests: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        requests.append({"url": str(request.url), "body": body})
        if request.url.path.endswith("/embeddings"):
            data = [
                {"index": i, "embedding": fake_embedding(t)} for i, t in enumerate(body["input"])
            ]
            return httpx.Response(200, json={"data": data})
        system = body["messages"][0]["content"]
        user = body["messages"][-1]["content"]
        if "scene segmentation" in system.lower():
            content = MOVED_JSON if "mobile team" in user else EXTRACTION_JSON
        elif "SUPERSEDES" in system:
            # echo real runtime ids back: supersede every EXISTING candidate
            new_ids = re.findall(r"NEW ([0-9a-f]{32})", user)
            old_ids = re.findall(r"EXISTING ([0-9a-f]{32})", user)
            content = json.dumps([{"new_id": new_ids[0], "supersedes": old_ids}]) if new_ids else "[]"
        elif "Persona Architect" in system:
            content = PERSONA_MD
        elif "SKILL documents" in system:
            content = SKILLS_MD
        elif "scene file" in system:
            content = "# Scene: I am helping Rin run Zanii's platform\n\n## Current state\n- condensed"
        else:  # pragma: no cover
            content = "UNEXPECTED PROMPT"
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    cfg = Settings(
        _env_file=None,
        data_dir=tmp_path / "e2e",
        llm_base_url="http://mock/v1",
        llm_api_key="test-key",
        llm_model="mock-model",
        embedding_base_url="http://mock/v1",
        embedding_model="mock-embed",
        embedding_dimensions=DIMS,
        pipeline_every_n_turns=1,
        pipeline_persona_every_n=1,
        gateway_api_key="",
        cors_origins="",
    )
    return cfg, handler, requests


async def test_full_llm_pipeline_end_to_end(mock_env):
    cfg, handler, requests = mock_env
    core = MemoryCore(cfg)
    await core.initialize()
    assert core.store.vec_enabled, "sqlite-vec must be active for this test"
    transport = httpx.MockTransport(handler)
    core.llm._client = httpx.AsyncClient(transport=transport)
    core.embedder._client = httpx.AsyncClient(transport=transport)

    await core.capture(
        "e2e",
        [
            {"role": "user", "content": "I lead the platform team at Zanii, remember that"},
            {"role": "assistant", "content": "Noted!"},
        ],
    )
    await core.end_session("e2e")  # deterministic flush of the extraction task

    # extraction prompt actually carried the captured conversation
    extraction_calls = [r for r in requests if "scene segmentation" in str(r["body"]).lower()]
    assert extraction_calls and "platform team at Zanii" in json.dumps(extraction_calls[0]["body"])

    # L1: dup deduped semantically, low-priority filtered -> 3 of 5 inserted
    assert core.store.count_l1() == 3
    contents = {r["content"] for r in core.store.get_all_l1()}
    assert contents == {FACT_PERSONA, FACT_EPISODIC, FACT_INSTRUCTION}

    # L2 scene file written with the surviving facts
    scene_files = list(cfg.scenes_dir.glob("*.md"))
    assert scene_files and FACT_PERSONA in scene_files[0].read_text(encoding="utf-8")

    # L3 persona written from the mock
    assert cfg.persona_path.read_text(encoding="utf-8").startswith("# User Narrative Profile")

    # Skills distilled after persona
    skill_files = list(cfg.skills_dir.glob("*.md"))
    assert skill_files and "Summarize deploys" in skill_files[0].read_text(encoding="utf-8")

    # Vectors are live: exact semantic match ranks first with ~zero distance
    query_vec = await core.embedder.embed_one(FACT_PERSONA.lower())
    hits = core.store.vector_search_l1(query_vec, limit=3)
    assert hits[0]["content"] == FACT_PERSONA and hits[0]["distance"] < 1e-6

    # Hybrid recall end-to-end: memories + persona injected
    recall = await core.recall("who runs the platform team?", "e2e")
    assert recall.strategy == "hybrid"
    assert FACT_PERSONA in recall.prepend_context
    assert "User Narrative Profile" in recall.append_system_context

    # --- conflict resolution: a contradicting fact supersedes the old one ---
    await core.capture("e2e", [{"role": "user", "content": "Update: I moved to the mobile team"}])
    await core.end_session("e2e")

    active = {r["content"] for r in core.store.get_l1_filtered(limit=50)}
    assert FACT_MOVED in active
    assert FACT_PERSONA not in active  # superseded, no longer served
    history = {r["content"]: r for r in core.store.get_all_l1()}
    assert history[FACT_PERSONA]["superseded_by"] == history[FACT_MOVED]["id"]

    recall2 = await core.recall("which team does Rin lead?", "e2e")
    assert FACT_PERSONA not in recall2.prepend_context
    assert FACT_MOVED in recall2.prepend_context

    await core.close()


async def test_pipeline_survives_llm_failure(mock_env):
    """A failing LLM must never lose captured turns — watermark stays put."""
    cfg, _, _ = mock_env
    core = MemoryCore(cfg)
    await core.initialize()

    def failing(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/embeddings"):
            return httpx.Response(200, json={"data": [{"index": 0, "embedding": fake_embedding("x")}]})
        return httpx.Response(500, text="upstream down")

    transport = httpx.MockTransport(failing)
    core.llm._client = httpx.AsyncClient(transport=transport)
    core.embedder._client = httpx.AsyncClient(transport=transport)

    await core.capture("f1", [{"role": "user", "content": "important fact to keep"}])
    await core.end_session("f1")  # extraction fails inside, logged not raised

    assert core.store.count_l1() == 0
    # rows remain un-extracted (watermark unchanged) for the next attempt
    assert core.store.get_pipeline_state("f1")["watermark"] == 0
    assert len(core.store.get_l0_after("f1", 0)) == 1
    await core.close()
