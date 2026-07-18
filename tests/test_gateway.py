from fastapi.testclient import TestClient

from zanii_memory.gateway import create_app


def test_health_capture_seed_search_roundtrip(cfg):
    with TestClient(create_app(cfg)) as client:
        health = client.get("/health").json()
        assert health["status"] == "ok"
        assert health["l1_memories"] == 0

        resp = client.post(
            "/capture",
            json={
                "session_key": "s1",
                "messages": [
                    {"role": "user", "content": "I always want responses in French"},
                    {"role": "assistant", "content": "Bien sûr!"},
                    {"role": "tool", "content": "ignored"},
                    {"role": "user", "content": "   "},
                ],
            },
        )
        assert resp.json() == {"recorded": 2}

        resp = client.post("/search/conversations", json={"query": "french responses"})
        results = resp.json()["results"]
        assert results and results[0]["session_key"] == "s1"

        resp = client.post(
            "/seed",
            json={"memories": [{"content": "The user requires the AI to reply in French", "type": "instruction"}]},
        )
        assert resp.json() == {"inserted": 1}

        resp = client.post("/search/memories", json={"query": "french", "type": "instruction"})
        assert resp.json()["results"][0]["type"] == "instruction"

        recall = client.post("/recall", json={"query": "reply language french", "session_key": "s1"}).json()
        assert recall["strategy"] == "keyword"  # no embeddings configured
        assert recall["memory_count"] >= 1
        assert "French" in recall["prepend_context"]

        # no LLM configured -> session end is a safe no-op
        assert client.post("/session/end", json={"session_key": "s1"}).status_code == 200


def test_offload_canvas_and_export_routes(cfg):
    with TestClient(create_app(cfg)) as client:
        result = client.post(
            "/offload",
            json={"session_key": "task-1", "content": "very long tool output " * 200, "label": "build logs"},
        ).json()
        node_id = result["node_id"]
        assert "build logs" in result["stub"]

        resp = client.get(f"/offload/{node_id}")
        assert resp.status_code == 200
        assert "very long tool output" in resp.json()["content"]
        assert client.get("/offload/Nffffffff").status_code == 404

        canvas = client.get("/canvas/task-1").json()["mermaid"]
        assert canvas.startswith("graph TD") and node_id in canvas

        client.post("/seed", json={"memories": [{"content": "portable fact", "type": "persona"}]})
        export = client.post("/export").json()
        assert export["version"] == 1
        assert any(r["content"] == "portable fact" for r in export["l1_records"])

        assert client.post("/import", json=export).json()["l1_inserted"] == 0  # already present
        assert client.post("/import", json={"version": 99}).status_code == 400


def test_validation_errors(cfg):
    with TestClient(create_app(cfg)) as client:
        assert client.post("/recall", json={"query": ""}).status_code == 422
        assert client.post("/capture", json={"messages": []}).status_code == 422


def test_bearer_auth_enforced(cfg):
    cfg = cfg.model_copy(update={"gateway_api_key": "secret-token"})
    with TestClient(create_app(cfg)) as client:
        assert client.get("/health").status_code == 200  # health stays open
        assert client.post("/recall", json={"query": "q", "session_key": "s"}).status_code == 401
        assert (
            client.post(
                "/recall",
                json={"query": "q", "session_key": "s"},
                headers={"Authorization": "Bearer wrong"},
            ).status_code
            == 401
        )
        assert (
            client.post(
                "/recall",
                json={"query": "q", "session_key": "s"},
                headers={"Authorization": "Bearer secret-token"},
            ).status_code
            == 200
        )
