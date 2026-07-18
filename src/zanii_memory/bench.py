"""Retrieval benchmark harness.

Deterministic, self-contained eval of recall quality on the *current
configuration* (backend, tokenizer, keyword vs hybrid): seeds a corpus of
facts + distractors, runs queries with known expected answers, and reports
recall@1, recall@5, and MRR.

Run: `zanii-memory bench` (uses a throwaway data dir — never touches real data).

With embeddings configured, the same harness measures the hybrid pipeline
end-to-end (embedding API included), so numbers are comparable across configs.
"""
from __future__ import annotations

from typing import Any

from .config import Settings

# (fact, [queries that must retrieve it]) — queries deliberately avoid quoting
# the fact verbatim so keyword mode is actually challenged.
CASES: list[tuple[str, list[str]]] = [
    ("The user (Maya) is a senior product manager based in Berlin",
     ["where does maya work and live", "what is the user's job"]),
    ("The user requires the AI to always reply with bullet points, never long paragraphs",
     ["how should answers be formatted", "reply style bullet points"]),
    ("The user is allergic to peanuts and avoids all peanut products",
     ["food allergies to avoid", "can the user eat peanut sauce"]),
    ("The user deployed the billing-service v2 to production on 2026-07-03 using the canary pipeline",
     ["when was billing service deployed", "canary deploy of billing"]),
    ("The user prefers PostgreSQL over MySQL for all new backend projects",
     ["which database for the new backend", "postgresql or mysql preference"]),
    ("The user runs a weekly retrospective meeting every Friday at 15:00 CET",
     ["when is the retrospective meeting", "weekly friday meeting time"]),
    ("The user's company Zanii builds AI agent products for marketing agencies",
     ["what does the user's company do", "zanii business"]),
    ("The user requires commit messages to follow Conventional Commits with a scope",
     ["commit message format rules", "how to write commits"]),
    ("The user is training for the Berlin half marathon in September 2026",
     ["what sport event is the user preparing for", "marathon training plans"]),
    ("The user's staging environment lives at staging.zanii.internal behind Tailscale",
     ["how to reach the staging environment", "staging url access"]),
]

DISTRACTORS = [
    "The user once mentioned the weather in Berlin was rainy",
    "The user asked for a translation of a short email",
    "The user watched a documentary about deep sea fish",
    "The user's colleague prefers tabs over spaces",
    "The user tested a random script that printed hello world",
    "The user reads tech news on Sunday mornings",
    "The user tried a new pasta restaurant downtown",
    "The user's favorite color for slides is navy blue",
    "The user updated a dependency last month",
    "The user listens to lo-fi music while coding",
]


async def run_bench(cfg: Settings) -> dict[str, Any]:
    """Seed corpus into a fresh core built from cfg, run queries, score."""
    from .core import MemoryCore  # local import to avoid cycles

    core = MemoryCore(cfg)
    await core.initialize()
    try:
        await core.seed([{"content": fact, "type": "persona", "priority": 80} for fact, _ in CASES])
        await core.seed([{"content": d, "type": "episodic", "priority": 60} for d in DISTRACTORS])

        ranks: list[int | None] = []
        failures: list[str] = []
        for fact, queries in CASES:
            for query in queries:
                hits = await core.search_memories(query, limit=5)
                rank = next((i + 1 for i, h in enumerate(hits) if h["content"] == fact), None)
                ranks.append(rank)
                if rank is None:
                    failures.append(query)

        n = len(ranks)
        return {
            "queries": n,
            "recall_at_1": round(sum(1 for r in ranks if r == 1) / n, 3),
            "recall_at_5": round(sum(1 for r in ranks if r is not None) / n, 3),
            "mrr": round(sum(1.0 / r for r in ranks if r is not None) / n, 3),
            "failed_queries": failures,
            "mode": "hybrid" if core.embedder.enabled else "keyword",
            "backend": core.store.stats()["backend"] if core.store else "?",
        }
    finally:
        await core.close()


def format_report(result: dict[str, Any]) -> str:
    lines = [
        f"Retrieval benchmark ({result['queries']} queries, {result['mode']} mode, {result['backend']} backend)",
        f"  recall@1: {result['recall_at_1']:.1%}",
        f"  recall@5: {result['recall_at_5']:.1%}",
        f"  MRR:      {result['mrr']:.3f}",
    ]
    if result["failed_queries"]:
        lines.append("  missed: " + "; ".join(result["failed_queries"]))
    return "\n".join(lines)
