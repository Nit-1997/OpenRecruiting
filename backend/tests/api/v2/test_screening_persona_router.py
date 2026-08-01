"""Tests for the v2 screening persona routes (recruiter-facing).

Endpoints under test (all under /api/v2):
  POST /roles/{requisition_id}/rounds/{round_id}/screening/persona/derive
  PUT  /roles/{requisition_id}/rounds/{round_id}/screening/persona
  GET  /roles/{requisition_id}/rounds/{round_id}/screening/persona

Org-scope round loads go through respx (real Supabase path). The Cortex reduce
service and the config service's set_persona are seam-mocked so the tests assert
wiring + persistence behaviour without network or DB. Mirrors
test_screening_router.py.
"""

import httpx
import pytest

from app.api.v2.routers import screening as screening_router
from tests.helpers.mock_data import ORG_ID, REQ_ID, ROUND_ID, NOW
from tests.helpers.supabase_mocks import rest_url


V2_ROOT = "/api/v2"


def _round_row(*, org_id=ORG_ID, req_id=REQ_ID):
    return {
        "id": ROUND_ID,
        "requisition_id": req_id,
        "name": "Phone screen",
        "category": "screening",
        "round_number": 1,
        "duration_minutes": 45,
        "ai_screenable": True,
        "deleted_at": None,
        "created_at": NOW,
        "updated_at": NOW,
        "requisitions": {
            "id": req_id,
            "organization_id": org_id,
            "deleted_at": None,
            "role_title": "Senior Backend Engineer",
            "experience_min_years": 5,
            "experience_max_years": 8,
            "job_description": "Own backend services end to end.",
            "must_have_skills": ["Python"],
            "good_to_have_skills": ["Kafka"],
        },
    }


def _org_row(name="Acme Corp"):
    return {"id": ORG_ID, "name": name}


def _persona_url(suffix=""):
    return f"{V2_ROOT}/roles/{REQ_ID}/rounds/{ROUND_ID}/screening/persona{suffix}"


def _sample_snapshot():
    return {
        "dimensions": [
            {
                "key": "tone_rapport",
                "value": "Warm and direct.",
                "confidence": 0.8,
                "source": "cortex",
            },
            {
                "key": "probing_depth",
                "value": "Probe two layers.",
                "confidence": 0.0,
                "source": "generic",
            },
        ],
        "text": "Tone & rapport: Warm and direct.\n\nNON-NEGOTIABLE RULES: ...",
    }


# ============================================================================
# auth
# ============================================================================


def test_derive_requires_auth(unauthed_client):
    resp = unauthed_client.post(_persona_url("/derive"), json={})
    assert resp.status_code in (401, 403)


# ============================================================================
# POST /persona/derive — derive + attach to config
# ============================================================================


def test_derive_returns_persona_and_sets_config(
    recruiter_client, respx_mock, monkeypatch
):
    respx_mock.get(rest_url("rounds")).mock(
        return_value=httpx.Response(200, json=_round_row())
    )
    respx_mock.get(rest_url("organizations")).mock(
        return_value=httpx.Response(200, json=_org_row("Acme Corp"))
    )

    snapshot = _sample_snapshot()
    derived = {
        "persona_id": "persona-123",
        "dimensions": snapshot["dimensions"],
        "composed_text": snapshot["text"],
        "persona_snapshot": snapshot,
    }

    captured = {}

    async def _fake_derive(
        self, *, requisition_id, org_id, org_name, role_title, created_by
    ):
        captured["requisition_id"] = requisition_id
        captured["org_id"] = org_id
        captured["org_name"] = org_name
        captured["role_title"] = role_title
        captured["created_by"] = created_by
        return derived

    set_calls = []

    async def _fake_set_persona(self, round_id, persona_id, persona_snapshot):
        set_calls.append((round_id, persona_id, persona_snapshot))
        return {"round_id": round_id, "persona_id": persona_id}

    monkeypatch.setattr(
        screening_router.PersonaReduceService, "derive", _fake_derive
    )
    monkeypatch.setattr(
        screening_router.ScreeningConfigService, "set_persona", _fake_set_persona
    )

    resp = recruiter_client.post(_persona_url("/derive"), json={})
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["persona_id"] == "persona-123"
    assert body["composed_text"] == snapshot["text"]
    assert len(body["dimensions"]) == 2
    assert body["dimensions"][0]["key"] == "tone_rapport"

    # derive was called with org/role context from the requisition + org row.
    assert captured["requisition_id"] == REQ_ID
    assert captured["org_id"] == ORG_ID
    assert captured["org_name"] == "Acme Corp"
    assert captured["role_title"] == "Senior Backend Engineer"
    assert captured["created_by"] is not None

    # The persona was attached to the round config (voice agent reads this).
    assert len(set_calls) == 1
    round_id, persona_id, persona_snapshot = set_calls[0]
    assert round_id == ROUND_ID
    assert persona_id == "persona-123"
    assert persona_snapshot == snapshot


def test_derive_404_when_round_cross_org(recruiter_client, respx_mock):
    OTHER_ORG = "ffffffff-ffff-ffff-ffff-ffffffffffff"
    respx_mock.get(rest_url("rounds")).mock(
        return_value=httpx.Response(200, json=_round_row(org_id=OTHER_ORG))
    )
    resp = recruiter_client.post(_persona_url("/derive"), json={})
    assert resp.status_code in (403, 404)


# ============================================================================
# PUT /persona — recruiter edits the rubric
# ============================================================================


def test_save_persona_recomposes_and_sets(recruiter_client, respx_mock, monkeypatch):
    respx_mock.get(rest_url("rounds")).mock(
        return_value=httpx.Response(200, json=_round_row())
    )

    persisted = {}

    async def _fake_persist(
        self, *, requisition_id, org_id, role_title, created_by, dimensions, composed_text
    ):
        persisted["dimensions"] = dimensions
        persisted["composed_text"] = composed_text
        persisted["requisition_id"] = requisition_id
        return "persona-edited-1"

    set_calls = []

    async def _fake_set_persona(self, round_id, persona_id, persona_snapshot):
        set_calls.append((round_id, persona_id, persona_snapshot))
        return {"round_id": round_id, "persona_id": persona_id}

    monkeypatch.setattr(
        screening_router.PersonaReduceService, "persist_persona", _fake_persist
    )
    monkeypatch.setattr(
        screening_router.ScreeningConfigService, "set_persona", _fake_set_persona
    )

    edited_dims = [
        {
            "key": "tone_rapport",
            "value": "Be blunt and fast.",
            "confidence": 1.0,
            "source": "recruiter",
        },
        {
            "key": "eval_priorities",
            "value": "Only ownership matters.",
            "confidence": 1.0,
            "source": "recruiter",
        },
    ]

    resp = recruiter_client.put(_persona_url(), json={"dimensions": edited_dims})
    assert resp.status_code == 200, resp.text
    body = resp.json()

    # The response reflects the recruiter's edits.
    assert body["persona_id"] == "persona-edited-1"
    assert [d["key"] for d in body["dimensions"]] == [
        "tone_rapport",
        "eval_priorities",
    ]
    assert body["dimensions"][0]["value"] == "Be blunt and fast."

    # composed_text was recomposed from the edited dimensions (carries the
    # edited value + the always-appended guardrails).
    assert "Be blunt and fast." in body["composed_text"]
    assert "NON-NEGOTIABLE RULES" in body["composed_text"]

    # Persisted a new personas row with the recomposed text.
    assert persisted["composed_text"] == body["composed_text"]
    assert persisted["requisition_id"] == REQ_ID

    # Attached to the round config with a snapshot {dimensions, text}.
    assert len(set_calls) == 1
    round_id, persona_id, persona_snapshot = set_calls[0]
    assert round_id == ROUND_ID
    assert persona_id == "persona-edited-1"
    assert persona_snapshot["text"] == body["composed_text"]
    assert len(persona_snapshot["dimensions"]) == 2


# ============================================================================
# GET /persona — current attached persona
# ============================================================================


def test_get_persona_returns_current(recruiter_client, respx_mock, monkeypatch):
    respx_mock.get(rest_url("rounds")).mock(
        return_value=httpx.Response(200, json=_round_row())
    )

    snapshot = _sample_snapshot()

    async def _fake_get(self, round_id):
        return {
            "round_id": round_id,
            "persona_id": "persona-current",
            "persona_snapshot": snapshot,
            "questions": [],
        }

    monkeypatch.setattr(screening_router.ScreeningConfigService, "get", _fake_get)

    resp = recruiter_client.get(_persona_url())
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["persona_id"] == "persona-current"
    assert body["composed_text"] == snapshot["text"]
    assert len(body["dimensions"]) == 2


def test_get_persona_empty_when_no_config(recruiter_client, respx_mock, monkeypatch):
    respx_mock.get(rest_url("rounds")).mock(
        return_value=httpx.Response(200, json=_round_row())
    )

    async def _none_get(self, round_id):
        return None

    monkeypatch.setattr(screening_router.ScreeningConfigService, "get", _none_get)

    resp = recruiter_client.get(_persona_url())
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["persona_id"] is None
    assert body["dimensions"] == []
    assert body["composed_text"] == ""


def test_persona_requires_auth_get(unauthed_client):
    resp = unauthed_client.get(_persona_url())
    assert resp.status_code in (401, 403)
