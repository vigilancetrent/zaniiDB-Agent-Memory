import pytest

from zanii_memory.config import Settings
from zanii_memory.core import MemoryCore


def make_cfg(tmp_path, name) -> Settings:
    return Settings(
        _env_file=None,
        data_dir=tmp_path / name,
        llm_base_url="",
        llm_model="",
        embedding_base_url="",
        embedding_model="",
        database_url="",
    )


async def test_export_import_roundtrip_and_idempotency(tmp_path):
    source = MemoryCore(make_cfg(tmp_path, "source"))
    await source.initialize()
    await source.seed(
        [
            {"content": "The user prefers PostgreSQL over MySQL", "type": "persona"},
            {"content": "The user requires the AI to write tests first", "type": "instruction", "priority": 90},
        ]
    )
    await source.capture("s1", [{"role": "user", "content": "hello memory"}])
    source.cfg.persona_path.write_text("# User Narrative Profile\ntest persona", encoding="utf-8")
    (source.cfg.scenes_dir / "scene-a.md").write_text("# Scene: A\n- fact", encoding="utf-8")

    data = await source.export_memory()
    assert len(data["l1_records"]) == 2
    assert len(data["l0_conversations"]) == 1
    assert data["persona"].startswith("# User Narrative Profile")
    assert "scene-a.md" in data["scenes"]
    await source.close()

    target = MemoryCore(make_cfg(tmp_path, "target"))
    await target.initialize()
    result = await target.import_memory(data)
    assert result == {"l1_inserted": 2, "l0_inserted": 1, "scenes_written": 1}
    assert target.cfg.persona_path.read_text(encoding="utf-8").startswith("# User Narrative Profile")

    hits = await target.search_memories("postgresql")
    assert hits and "PostgreSQL" in hits[0]["content"]

    # importing again inserts nothing (idempotent)
    result2 = await target.import_memory(data)
    assert result2 == {"l1_inserted": 0, "l0_inserted": 0, "scenes_written": 0}
    await target.close()


async def test_import_preserves_superseded_state(tmp_path):
    source = MemoryCore(make_cfg(tmp_path, "sup-src"))
    await source.initialize()
    await source.seed(
        [{"content": "The user prefers coffee"}, {"content": "The user switched to tea"}]
    )
    rows = {r["content"]: r for r in source.store.get_all_l1()}
    source.store.mark_superseded([rows["The user prefers coffee"]["id"]], rows["The user switched to tea"]["id"])
    data = await source.export_memory()
    await source.close()

    target = MemoryCore(make_cfg(tmp_path, "sup-dst"))
    await target.initialize()
    await target.import_memory(data)
    active = {r["content"] for r in target.store.get_l1_filtered(limit=10)}
    assert "The user switched to tea" in active
    assert "The user prefers coffee" not in active  # superseded state survived migration
    history = {r["content"]: r for r in target.store.get_all_l1()}
    assert history["The user prefers coffee"]["superseded_by"]
    await target.close()


async def test_import_rejects_unknown_version(tmp_path):
    core = MemoryCore(make_cfg(tmp_path, "v"))
    await core.initialize()
    with pytest.raises(ValueError, match="Unsupported export version"):
        await core.import_memory({"version": 99})
    await core.close()


async def test_import_strips_path_components_from_scene_names(tmp_path):
    core = MemoryCore(make_cfg(tmp_path, "sec"))
    await core.initialize()
    await core.import_memory(
        {"version": 1, "scenes": {"../../evil.md": "payload"}, "l1_records": [], "l0_conversations": []}
    )
    assert (core.cfg.scenes_dir / "evil.md").exists()
    assert not (core.cfg.data_dir.parent.parent / "evil.md").exists()
    await core.close()
