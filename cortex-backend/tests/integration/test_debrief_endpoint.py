"""Integration tests for the debrief controller — `POST /api/v1/debrief` (spec §8).

The FastAPI app is built via `src.main.create_app()` (matching `test_health.py`); the
`DebriefService` is MOCKED and injected through the module-global `set_debrief_service`
setter (the same pattern `set_event_router` uses). We never enter the app's lifespan
(no `with TestClient(...)`), so no Neo4j/Graphiti/Supabase connection is attempted —
the route resolves the service straight from the module global.

Auth source: `_verify_auth` compares the `X-Internal-Secret` header to
`get_settings().auth.internal_secret`, which is populated from the `INTERNAL_SECRET`
env var. `get_settings()` is `@lru_cache`'d, so the fixture sets the env, clears the
cache, and restores both on teardown.

Coverage:
  * 401 without the header / with a wrong secret.
  * 422 on a malformed body (missing field / empty candidate list).
  * 200 with a valid `DebriefPacket` JSON when the service is mocked.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import src.config.settings as settings_module
from src.config.settings import get_settings
from src.controller.debrief_controller import set_debrief_service
from src.main import create_app
from src.model.debrief import (
    DebriefCandidateSnapshot,
    DebriefPacket,
    DebriefPanelVote,
    DebriefSourceStats,
    PanelMember,
)
from src.service.debrief.debrief_service import DebriefService

INTERNAL_SECRET = "test-internal-secret"
ORG_ID = "org-1"
REQ_ID = "req-1"
CAND_A = "cand-a"
CAND_B = "cand-b"


def _packet() -> DebriefPacket:
    """A minimal but fully-valid `DebriefPacket` the mocked service returns."""
    return DebriefPacket(
        id="packet-1",
        requisition_id=REQ_ID,
        role_title="Staff Engineer",
        title="Staff Engineer Debrief",
        subtitle="2 candidates compared",
        generated_at="2026-06-07T00:00:00+00:00",
        generated_by="Scout debrief agent",
        status="fresh",
        confidence="high",
        verdict="hire",
        headline_recommendation="Recommend Ada Lovelace.",
        panel_members=[PanelMember(name="Alice Eng", role="Technical", initials="AE", color="#2563eb")],
        candidates=[
            DebriefCandidateSnapshot(
                candidate_id=CAND_A,
                name="Ada Lovelace",
                initials="AL",
                color="#2563eb",
                rank=1,
                verdict="hire",
                headline="Top pick.",
                aggregate_score=3.6,
                rounds_completed=2,
                rounds_total=2,
                recommendation="Move to offer.",
                panel_votes=[DebriefPanelVote(panelist="Alice Eng", panelist_role="Technical", vote="yes")],
            )
        ],
        source_stats=DebriefSourceStats(scorecards=2, transcripts=2),
    )


@pytest.fixture
def secret_env(monkeypatch):
    """Set INTERNAL_SECRET and bust the `@lru_cache`'d settings; restore on teardown."""
    monkeypatch.setenv("INTERNAL_SECRET", INTERNAL_SECRET)
    get_settings.cache_clear()
    settings_module.get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def client(secret_env):
    """A `TestClient` over `create_app()` with a mocked `DebriefService` injected.
    NOT used as a context manager, so the lifespan never runs (no real I/O)."""
    service = MagicMock(spec=DebriefService)
    service.generate = AsyncMock(return_value=_packet())
    set_debrief_service(service)

    app = create_app()
    test_client = TestClient(app)
    test_client.debrief_service = service  # expose for assertions
    yield test_client

    set_debrief_service(None)  # reset the module global between tests


def _body(candidate_ids: list[str] | None = None) -> dict:
    return {
        "org_id": ORG_ID,
        "requisition_id": REQ_ID,
        "candidate_ids": candidate_ids if candidate_ids is not None else [CAND_A, CAND_B],
    }


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
def test_missing_secret_returns_401(client):
    resp = client.post("/api/v1/debrief", json=_body())
    assert resp.status_code == 401
    client.debrief_service.generate.assert_not_awaited()


def test_wrong_secret_returns_401(client):
    resp = client.post(
        "/api/v1/debrief", json=_body(), headers={"X-Internal-Secret": "nope"}
    )
    assert resp.status_code == 401
    client.debrief_service.generate.assert_not_awaited()


# ---------------------------------------------------------------------------
# Validation (422 from Pydantic before the handler body runs)
# ---------------------------------------------------------------------------
def test_missing_field_returns_422(client):
    bad = _body()
    del bad["requisition_id"]
    resp = client.post(
        "/api/v1/debrief", json=bad, headers={"X-Internal-Secret": INTERNAL_SECRET}
    )
    assert resp.status_code == 422


def test_empty_candidate_list_returns_422(client):
    resp = client.post(
        "/api/v1/debrief",
        json=_body(candidate_ids=[]),  # min_length=1 on the request model
        headers={"X-Internal-Secret": INTERNAL_SECRET},
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------
def test_valid_request_returns_200_with_packet(client):
    resp = client.post(
        "/api/v1/debrief", json=_body(), headers={"X-Internal-Secret": INTERNAL_SECRET}
    )
    assert resp.status_code == 200
    data = resp.json()

    # The response JSON reconstructs a valid `DebriefPacket` (FE render contract).
    packet = DebriefPacket.model_validate(data)
    assert packet.id == "packet-1"
    assert packet.requisition_id == REQ_ID
    assert packet.verdict == "hire"
    assert packet.candidates[0].candidate_id == CAND_A
    assert packet.candidates[0].score_scale == 4

    # The service was called with exactly the request's fields.
    client.debrief_service.generate.assert_awaited_once_with(
        org_id=ORG_ID, requisition_id=REQ_ID, candidate_ids=[CAND_A, CAND_B]
    )


# ---------------------------------------------------------------------------
# Service failure branches (FIX 4) — status preserved vs. opaque 500
# ---------------------------------------------------------------------------
def test_service_status_bearing_exception_preserves_status(client):
    """A status-bearing exception from the service (e.g. an upstream 404) is
    re-raised verbatim — the controller preserves its status, not a blanket 500."""
    client.debrief_service.generate = AsyncMock(
        side_effect=HTTPException(status_code=404, detail="requisition not found")
    )
    resp = client.post(
        "/api/v1/debrief", json=_body(), headers={"X-Internal-Secret": INTERNAL_SECRET}
    )
    assert resp.status_code == 404


def test_service_generic_exception_returns_opaque_500(client):
    """A generic (non-status) exception → 500 with a STATIC message; the raw
    exception text must NEVER leak into the client response body."""
    secret = "tOpSeCrEt-should-not-leak"
    client.debrief_service.generate = AsyncMock(
        side_effect=RuntimeError(secret)
    )
    resp = client.post(
        "/api/v1/debrief", json=_body(), headers={"X-Internal-Secret": INTERNAL_SECRET}
    )
    assert resp.status_code == 500
    body = resp.text
    assert secret not in body
    assert "RuntimeError" not in body
    assert resp.json()["detail"] == "Debrief generation failed"
