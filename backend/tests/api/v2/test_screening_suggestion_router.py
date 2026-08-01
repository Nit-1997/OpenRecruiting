"""Tests for the role-level screening-suggestion route.

  GET /api/v2/roles/{requisition_id}/screening/suggestion

Org-scope requisition load goes through respx (real Supabase path). The
suggestion service is seam-mocked so we assert wiring + auth + org-scoping
without network or graph access. Mirrors test_screening_persona_router.py.
"""

import httpx

from app.api.v2.routers import screening_suggestion as suggestion_router
from tests.helpers.mock_data import ORG_ID, REQ_ID
from tests.helpers.supabase_mocks import rest_url


V2_ROOT = "/api/v2"


def _req_row(*, org_id=ORG_ID, req_id=REQ_ID):
    return {
        "id": req_id,
        "organization_id": org_id,
        "deleted_at": None,
        "role_title": "Senior Backend Engineer",
    }


def _org_row(name="Acme Corp"):
    return {"id": ORG_ID, "name": name}


def _suggestion_url(req_id=REQ_ID):
    return f"{V2_ROOT}/roles/{req_id}/screening/suggestion"


def test_suggestion_requires_auth(unauthed_client):
    resp = unauthed_client.get(_suggestion_url())
    assert resp.status_code in (401, 403)


def test_suggestion_returns_dict(recruiter_client, respx_mock, monkeypatch):
    respx_mock.get(rest_url("requisitions")).mock(
        return_value=httpx.Response(200, json=_req_row())
    )
    respx_mock.get(rest_url("organizations")).mock(
        return_value=httpx.Response(200, json=_org_row("Acme Corp"))
    )

    captured = {}

    async def _fake_suggest(self, *, requisition_id, org_id, org_name):
        captured["requisition_id"] = requisition_id
        captured["org_id"] = org_id
        captured["org_name"] = org_name
        return {
            "should_suggest": True,
            "reason": "3 candidates were weak in System Design.",
            "target_round_id": "round-1",
        }

    monkeypatch.setattr(
        suggestion_router.ScreeningSuggestionService, "suggest", _fake_suggest
    )

    resp = recruiter_client.get(_suggestion_url())
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["should_suggest"] is True
    assert body["target_round_id"] == "round-1"
    assert "System Design" in body["reason"]

    # The service was called org-scoped with context from the requisition + org.
    assert captured["requisition_id"] == REQ_ID
    assert captured["org_id"] == ORG_ID
    assert captured["org_name"] == "Acme Corp"


def test_suggestion_404_when_req_cross_org(recruiter_client, respx_mock):
    OTHER_ORG = "ffffffff-ffff-ffff-ffff-ffffffffffff"
    respx_mock.get(rest_url("requisitions")).mock(
        return_value=httpx.Response(200, json=_req_row(org_id=OTHER_ORG))
    )
    resp = recruiter_client.get(_suggestion_url())
    assert resp.status_code in (403, 404)


def test_suggestion_404_when_req_missing(recruiter_client, respx_mock):
    respx_mock.get(rest_url("requisitions")).mock(
        return_value=httpx.Response(200, json=[])
    )
    resp = recruiter_client.get(_suggestion_url())
    assert resp.status_code in (403, 404)
