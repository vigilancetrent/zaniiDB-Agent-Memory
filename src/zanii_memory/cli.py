"""zanii-memory CLI: serve | seed | search | inspect"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

from .config import Settings
from .core import MemoryCore


def _run_with_core(coro_factory):
    async def runner():
        core = MemoryCore()
        await core.initialize()
        try:
            return await coro_factory(core)
        finally:
            await core.close()

    return asyncio.run(runner())


def cmd_serve(args: argparse.Namespace) -> None:
    import uvicorn

    from .gateway import create_app

    cfg = Settings()
    uvicorn.run(create_app(cfg), host=args.host or cfg.gateway_host, port=args.port or cfg.gateway_port)


def cmd_mcp(args: argparse.Namespace) -> None:
    from .mcp_server import run

    run()


def cmd_seed(args: argparse.Namespace) -> None:
    data = json.loads(Path(args.file).read_text(encoding="utf-8"))
    if not isinstance(data, list):
        sys.exit("Seed file must be a JSON array of {content, type?, priority?} objects")

    async def do(core: MemoryCore):
        inserted = await core.seed(data)
        print(f"Seeded {inserted} memories ({len(data) - inserted} skipped as duplicates/empty)")

    _run_with_core(do)


def cmd_search(args: argparse.Namespace) -> None:
    async def do(core: MemoryCore):
        if args.conversations:
            hits = await core.search_conversations(args.query, limit=args.limit)
            for h in hits:
                print(f"[{h['score']:.3f}] [{h['session_key']}] [{h['role']}] {h['content'][:200]}")
        else:
            hits = await core.search_memories(args.query, limit=args.limit)
            for h in hits:
                print(f"[{h['score']:.3f}] [{h['type']}|p{h['priority']}] {h['content']}")
        if not hits:
            print("(no results)")

    _run_with_core(do)


def cmd_export(args: argparse.Namespace) -> None:
    async def do(core: MemoryCore):
        data = await core.export_memory()
        Path(args.file).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        print(
            f"Exported {len(data['l1_records'])} memories, {len(data['l0_conversations'])} messages,"
            f" {len(data['scenes'])} scenes -> {args.file}"
        )

    _run_with_core(do)


def cmd_import(args: argparse.Namespace) -> None:
    data = json.loads(Path(args.file).read_text(encoding="utf-8"))

    async def do(core: MemoryCore):
        result = await core.import_memory(data)
        print(
            f"Imported {result['l1_inserted']} memories, {result['l0_inserted']} messages,"
            f" {result['scenes_written']} scenes (existing entries skipped)"
        )

    _run_with_core(do)


def cmd_bench(args: argparse.Namespace) -> None:
    import tempfile

    from .bench import format_report, run_bench

    async def do():
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Settings(data_dir=Path(tmp) / "bench")
            print(format_report(await run_bench(cfg)))

    asyncio.run(do())


def cmd_personamem(args: argparse.Namespace) -> None:
    import tempfile

    from .personamem import format_report, run_personamem

    async def do():
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Settings(data_dir=Path(tmp) / "pm")
            report = await run_personamem(
                cfg,
                Path(tmp),
                size=args.size,
                max_contexts=args.contexts,
                max_questions=args.max_questions,
                baseline=args.baseline,
                types=set(args.types.split(",")) if args.types else None,
                novelty_threshold=args.novelty_threshold,
                include_scenes=args.scenes,
                ledger_chars=args.ledger_chars,
                chronological=args.chronological,
                evidence=args.evidence,
                reasoning=args.reasoning,
                votes=args.votes,
                answer_model=args.answer_model,
            )
            print(format_report(report))

    asyncio.run(do())


def cmd_consolidate(args: argparse.Namespace) -> None:
    async def do(core: MemoryCore):
        result = await core.consolidate()
        print(f"Removed {result['duplicates_removed']} near-duplicates, {result['decayed']} decayed memories")

    _run_with_core(do)


def cmd_skills(args: argparse.Namespace) -> None:
    async def do(core: MemoryCore):
        written = await core.generate_skills()
        print(f"Wrote {written} skill documents to {core.cfg.skills_dir}")

    _run_with_core(do)


def cmd_audit(args: argparse.Namespace) -> None:
    async def do(core: MemoryCore):
        entries = core.audit_log(args.limit)
        if not entries:
            print("(audit log empty — set ZANII_AUDIT_ENABLED=true to record operations)")
        for e in entries:
            print(f"{e['ts']} [{e['op']}] {e['detail']}")

    _run_with_core(do)


def cmd_inspect(args: argparse.Namespace) -> None:
    async def do(core: MemoryCore):
        print(json.dumps(core.stats(), indent=2))
        if core.cfg.persona_path.exists():
            print("\n--- persona.md ---\n")
            print(core.cfg.persona_path.read_text(encoding="utf-8"))

    _run_with_core(do)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(prog="zanii-memory", description="ZaniiDB Agent Memory")
    sub = parser.add_subparsers(dest="command", required=True)

    p_serve = sub.add_parser("serve", help="Run the HTTP gateway")
    p_serve.add_argument("--host", default=None)
    p_serve.add_argument("--port", type=int, default=None)
    p_serve.set_defaults(func=cmd_serve)

    p_mcp = sub.add_parser("mcp", help="Run the MCP server (stdio) for MCP-capable agents")
    p_mcp.set_defaults(func=cmd_mcp)

    p_seed = sub.add_parser("seed", help="Seed L1 memories from a JSON file")
    p_seed.add_argument("file")
    p_seed.set_defaults(func=cmd_seed)

    p_search = sub.add_parser("search", help="Search memories (or conversations with -c)")
    p_search.add_argument("query")
    p_search.add_argument("-c", "--conversations", action="store_true")
    p_search.add_argument("-n", "--limit", type=int, default=10)
    p_search.set_defaults(func=cmd_search)

    p_export = sub.add_parser("export", help="Export all memory to a portable JSON file")
    p_export.add_argument("file")
    p_export.set_defaults(func=cmd_export)

    p_import = sub.add_parser("import", help="Import a memory export (idempotent; use for backend migration)")
    p_import.add_argument("file")
    p_import.set_defaults(func=cmd_import)

    p_bench = sub.add_parser("bench", help="Run the retrieval benchmark (throwaway data dir)")
    p_bench.set_defaults(func=cmd_bench)

    p_pm = sub.add_parser("personamem", help="Run the public PersonaMem-v1 benchmark (needs LLM keys)")
    p_pm.add_argument("--size", default="32k", choices=["32k", "128k", "1M"])
    p_pm.add_argument("--contexts", type=int, default=1, help="How many shared contexts to ingest")
    p_pm.add_argument("--max-questions", type=int, default=15)
    p_pm.add_argument("--baseline", action="store_true", help="Also score a no-memory baseline")
    p_pm.add_argument("--types", default="", help="Comma-separated question_type filter (evaluation subset)")
    p_pm.add_argument("--novelty-threshold", type=float, default=None,
                      help="Enable calibrated novelty check; flag options with embedding similarity >= T")
    p_pm.add_argument("--scenes", action="store_true", help="Include scene-block notes in MCQ context")
    p_pm.add_argument("--ledger-chars", type=int, default=4000, help="Scene ledger char budget (with --scenes)")
    p_pm.add_argument("--chronological", action="store_true", help="Present recalled memories oldest-first")
    p_pm.add_argument("--evidence", action="store_true", help="Add retrieved raw-conversation evidence to answers")
    p_pm.add_argument("--reasoning", action="store_true", help="Visible brief reasoning before the answer label")
    p_pm.add_argument("--votes", type=int, default=1, help="Self-consistency: majority vote over N samples")
    p_pm.add_argument("--answer-model", default=None, help="Different model for answering only (e.g. gpt-5.6-sol)")
    p_pm.set_defaults(func=cmd_personamem)

    p_cons = sub.add_parser("consolidate", help="Merge near-duplicate memories and apply retention decay")
    p_cons.set_defaults(func=cmd_consolidate)

    p_skills = sub.add_parser("skills", help="Distill SOP/skill docs from memories (requires LLM)")
    p_skills.set_defaults(func=cmd_skills)

    p_audit = sub.add_parser("audit", help="Show the audit log")
    p_audit.add_argument("-n", "--limit", type=int, default=100)
    p_audit.set_defaults(func=cmd_audit)

    p_inspect = sub.add_parser("inspect", help="Show stats and persona")
    p_inspect.set_defaults(func=cmd_inspect)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
