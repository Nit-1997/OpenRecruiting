import os
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    os.environ["INTERNAL_SECRET"] = "test-secret-123"
    os.environ.setdefault("NEO4J_URI", "bolt://localhost:7687")
    os.environ.setdefault("NEO4J_USER", "neo4j")
    os.environ.setdefault("NEO4J_PASSWORD", "cortex_dev_2026")

    from src.main import app
    return TestClient(app, raise_server_exceptions=False)


def test_missing_auth_returns_401(client):
    resp = client.post("/api/v1/ingest", json={
        "event_type": "feedback_completed",
        "org_id": "org-001",
        "source_ref": {"candidate_round_id": "cr-001"},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })
    assert resp.status_code == 401


def test_wrong_auth_returns_401(client):
    resp = client.post("/api/v1/ingest", json={
        "event_type": "feedback_completed",
        "org_id": "org-001",
        "source_ref": {"candidate_round_id": "cr-001"},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }, headers={"X-Internal-Secret": "wrong-secret"})
    assert resp.status_code == 401


def test_unknown_event_type_returns_422(client):
    resp = client.post("/api/v1/ingest", json={
        "event_type": "unknown_event",
        "org_id": "org-001",
        "source_ref": {},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }, headers={"X-Internal-Secret": "test-secret-123"})
    assert resp.status_code == 422
