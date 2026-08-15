import os
from pathlib import Path

os.environ["SQLITE_PATH"] = str(Path(__file__).parent / "test.db")

from fastapi.testclient import TestClient
from backend.main import app


def test_health_and_seeded_agents():
    with TestClient(app) as client:
        assert client.get("/api/health").json()["status"] == "healthy"
        assert len(client.get("/api/agents").json()) >= 6


def test_agent_lifecycle_and_validation():
    with TestClient(app) as client:
        bad = client.post("/api/agents", json={"name": "x", "description": "y"})
        assert bad.status_code == 422
        made = client.post("/api/agents", json={"name": "Test Agent", "description": "Contract test agent", "tools": ["Web Search"]})
        assert made.status_code == 201
        agent = made.json()
        toggled = client.patch(f"/api/agents/{agent['id']}/toggle")
        assert toggled.status_code == 200
        assert client.delete(f"/api/agents/{agent['id']}").status_code == 204


def test_run_stream_persists_trace():
    with TestClient(app) as client:
        created = client.post("/api/runs", json={"prompt": "Analyze my GitHub repositories", "demo": True})
        assert created.status_code == 201
        run_id = created.json()["id"]
        with client.stream("GET", f"/api/runs/{run_id}/events") as response:
            body = "".join(response.iter_text())
        assert "event: agent_event" in body
        assert "event: complete" in body
        run = client.get(f"/api/runs/{run_id}").json()
        assert run["status"] == "completed"
        assert len(run["events"]) == 7
