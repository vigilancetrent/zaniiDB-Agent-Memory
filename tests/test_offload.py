from zanii_memory.offload import Offloader


def test_offload_retrieve_roundtrip(cfg):
    off = Offloader(cfg)
    big = "ERROR trace line\n" * 500
    result = off.offload("s1", big, label="failing deploy logs")
    assert result["node_id"].startswith("N")
    assert result["chars"] == len(big)
    assert "failing deploy logs" in result["stub"]

    content = off.retrieve(result["node_id"])
    assert content is not None
    assert "ERROR trace line" in content
    assert "session_key: s1" in content  # header preserved for white-box inspection


def test_retrieve_rejects_bad_node_ids(cfg):
    off = Offloader(cfg)
    off.offload("s1", "content")
    assert off.retrieve("../../etc/passwd") is None
    assert off.retrieve("Nzzzzzzzz") is None
    assert off.retrieve("N12345678extra") is None
    assert off.retrieve("Nffffffff") is None  # valid format, unknown node


def test_canvas_builds_a_chain(cfg):
    off = Offloader(cfg)
    assert off.canvas("s1") == ""
    n1 = off.offload("s1", "step one output", label="fetch data")["node_id"]
    n2 = off.offload("s1", "step two output", label='parse "results"')["node_id"]
    canvas = off.canvas("s1")
    assert canvas.startswith("graph TD")
    assert f'{n1}["fetch data"]' in canvas
    assert f"{n1} --> {n2}" in canvas
    assert '"' + "parse 'results'" + '"' in canvas  # quotes escaped for mermaid

    # sessions are isolated
    off.offload("s2", "other session", label="other")
    assert "other" not in off.canvas("s1")
