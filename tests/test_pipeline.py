from zanii_memory.pipeline.extractor import parse_extraction
from zanii_memory.pipeline.scenes import append_scene_facts, read_all_scenes, slugify
from zanii_memory.pipeline.scheduler import next_threshold
from zanii_memory.types import MemoryRecord


def test_next_threshold_warmup_doubles_and_caps():
    every_n = 5
    seq = [1]
    for _ in range(4):
        seq.append(next_threshold(seq[-1], every_n, warmup=True))
    assert seq == [1, 2, 4, 5, 5]
    assert next_threshold(1, every_n, warmup=False) == 5


def test_parse_extraction_handles_fences_and_garbage():
    fenced = """```json
[{"scene_name": "Helping a dev with Kafka", "memories": [
  {"content": "The user works on a Kafka-based pipeline", "type": "persona", "priority": 70, "metadata": {}}
]}]
```"""
    scenes = parse_extraction(fenced)
    assert len(scenes) == 1
    assert scenes[0]["scene_name"] == "Helping a dev with Kafka"
    assert scenes[0]["memories"][0]["priority"] == 70

    assert parse_extraction("no json here") == []
    assert parse_extraction("[]") == []
    # invalid type and missing content are dropped, scene kept
    scenes = parse_extraction(
        '[{"scene_name": "s", "memories": [{"content": "x", "type": "bogus"}, {"type": "persona"}]}]'
    )
    assert scenes[0]["memories"] == []


def test_parse_extraction_coerces_bad_priority():
    scenes = parse_extraction(
        '[{"scene_name": "s", "memories": [{"content": "x", "type": "persona", "priority": "high"}]}]'
    )
    assert scenes[0]["memories"][0]["priority"] == 60


def test_scene_files_append_and_read(tmp_path):
    scenes_dir = tmp_path / "scenes"
    mem = MemoryRecord(content="The user prefers concise answers", type="instruction", priority=90)
    path = append_scene_facts(scenes_dir, "Helping Zanii's admin with memory design", [mem])
    assert path.exists()
    append_scene_facts(scenes_dir, "Helping Zanii's admin with memory design", [mem])
    text = path.read_text(encoding="utf-8")
    assert text.count("The user prefers concise answers") == 2
    assert "# Scene:" in text

    combined = read_all_scenes(scenes_dir, max_chars=50)
    assert len(combined) <= 60  # budget respected (allowing separator slack)


def test_slugify():
    assert slugify("I am helping X with Y!") == "i-am-helping-x-with-y"
    assert slugify("///") == "scene"
