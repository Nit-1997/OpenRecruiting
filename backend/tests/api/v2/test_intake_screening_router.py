"""Tests for the intake-scoped screening config routes (pre-publish).

Endpoints under test (all under /api/v2):
  POST /intake/sessions/{session_id}/screening/generate
  POST /intake/sessions/{session_id}/screening/persona/derive

These configure the screening agent on a plan round DURING intake, before the
round exists in the DB. They are RETURN-ONLY (the FE stores the result in the
intake plan artifact); nothing is persisted to round_screening_configs here.

Org scoping goes through the session → requisition → org join (404 cross-org).
The LLM generator + persona reduce service are seam-mocked so the tests assert
wiring without network/DB.
"""

import httpx

from app.api.v2.routers import intake_screening as intake_screening_router
from app.api.v2.schemas.screening import ScreeningQuestion
from tests.helpers.mock_data import ORG_ID, REQ_ID, NOW
from tests.helpers.supabase_mocks import rest_url

V2_ROOT = "/api/v2"
OTHER_ORG_ID = "ffffffff-ffff-ffff-ffff-ffffffffffff"
SESSION_ID = "00000000-0000-0000-0000-0000000000c0"


def _session_row(*, org_id=ORG_ID, req_id=REQ_ID):
    """An intake_sessions row joined to its requisition (org-scope shape)."""
    return {
        "id": SESSION_ID,
        "requisition_id": req_id,
        "status": "active",
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
            "must_have_skills": ["Python", "distributed systems"],
            "good_to_have_skills": ["Kafka"],
        },
    }


def _url(suffix=""):
    return f"{V2_ROOT}/intake/sessions/{SESSION_ID}/screening{suffix}"


# ============================================================================
# auth
# ============================================================================


def test_generate_requires_auth(unauthed_client):
    resp = unauthed_client.post(_url("/generate"), json={"round_name": "x", "category": "screening"})
    assert resp.status_code in (401, 403)


def test_persona_derive_requires_auth(unauthed_client):
    resp = unauthed_client.post(_url("/persona/derive"), json={})
    assert resp.status_code in (401, 403)


# ============================================================================
# POST /generate — draft questions only, NOT persisted
# ============================================================================


def test_generate_returns_draft_questions(recruiter_client, respx_mock, monkeypatch):
    respx_mock.get(rest_url("intake_sessions")).mock(
        return_value=httpx.Response(200, json=_session_row())
    )

    generated = [
        ScreeningQuestion(
            order_index=0,
            title="Toughest incident",
            prompt="Walk me through the hardest production incident you owned.",
            probe="What was the root cause?",
            signal="EXECUTION",
            dimension="ownership",
            duration_minutes=6,
        )
    ]

    captured = {}

    async def _fake_generate(self, *, role_context, must_haves, cortex_gaps, preferences):
        captured["role_context"] = role_context
        captured["must_haves"] = must_haves
        captured["cortex_gaps"] = cortex_gaps
        captured["preferences"] = preferences
        return generated

    monkeypatch.setattr(
        intake_screening_router.ScreeningQuestionGenerator, "generate", _fake_generate
    )

    resp = recruiter_client.post(
        _url("/generate"),
        json={
            "round_name": "Recruiter Screen",
            "category": "screening",
            "skills": ["communication"],
            "preferences": "lean on incident response",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    # Returns the draft questions (not a saved config; no round_id required).
    assert len(body["questions"]) == 1
    assert body["questions"][0]["title"] == "Toughest incident"
    assert body["questions"][0]["signal"] == "EXECUTION"

    # role_context + must_haves sourced from the SESSION's requisition.
    assert "Senior Backend Engineer" in captured["role_context"]
    assert captured["must_haves"] == ["Python", "distributed systems"]
    # Phase 1: cortex gaps are an empty placeholder.
    assert captured["cortex_gaps"] == []
    assert captured["preferences"] == "lean on incident response"


def test_generate_404_when_session_cross_org(recruiter_client, respx_mock):
    respx_mock.get(rest_url("intake_sessions")).mock(
        return_value=httpx.Response(200, json=_session_row(org_id=OTHER_ORG_ID))
    )
    resp = recruiter_client.post(
        _url("/generate"), json={"round_name": "x", "category": "screening"}
    )
    assert resp.status_code in (403, 404)


def test_generate_404_when_session_missing(recruiter_client, respx_mock):
    respx_mock.get(rest_url("intake_sessions")).mock(
        return_value=httpx.Response(200, json=[])
    )
    resp = recruiter_client.post(
        _url("/generate"), json={"round_name": "x", "category": "screening"}
    )
    assert resp.status_code == 404


# ============================================================================
# POST /persona/derive — returns persona for the artifact, cold-start safe
# ============================================================================


def test_persona_derive_returns_persona(recruiter_client, respx_mock, monkeypatch):
    respx_mock.get(rest_url("intake_sessions")).mock(
        return_value=httpx.Response(200, json=_session_row())
    )
    # org-name lookup for the cortex reader
    respx_mock.get(rest_url("organizations")).mock(
        return_value=httpx.Response(200, json={"name": "Acme"})
    )

    captured = {}

    async def _fake_derive(self, *, requisition_id, org_id, org_name, role_title, created_by):
        captured["requisition_id"] = requisition_id
        captured["org_id"] = org_id
        captured["org_name"] = org_name
        captured["role_title"] = role_title
        return {
            "persona_id": "persona-1",
            "dimensions": [
                {"key": "tone_rapport", "value": "Warm", "confidence": 0.0, "source": "generic"}
            ],
            "composed_text": "Be warm and curious.",
            "persona_snapshot": {
                "dimensions": [
                    {"key": "tone_rapport", "value": "Warm", "confidence": 0.0, "source": "generic"}
                ],
                "text": "Be warm and curious.",
            },
        }

    set_persona_called = {"n": 0}

    async def _guard_set_persona(self, *args, **kwargs):
        set_persona_called["n"] += 1
        return {}

    monkeypatch.setattr(
        intake_screening_router.PersonaReduceService, "derive", _fake_derive
    )
    # No round config exists at intake time — set_persona must NOT be called.
    monkeypatch.setattr(
        intake_screening_router.ScreeningConfigService, "set_persona", _guard_set_persona
    )

    resp = recruiter_client.post(_url("/persona/derive"), json={})
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["persona_id"] == "persona-1"
    assert body["composed_text"] == "Be warm and curious."
    assert body["dimensions"][0]["key"] == "tone_rapport"
    # The FE stores the full snapshot in the artifact.
    assert body["persona_snapshot"]["text"] == "Be warm and curious."

    # Sourced from the session's requisition + org.
    assert captured["requisition_id"] == REQ_ID
    assert captured["org_id"] == ORG_ID
    assert captured["org_name"] == "Acme"
    assert captured["role_title"] == "Senior Backend Engineer"

    # No round config yet → never attach a persona to a (nonexistent) round.
    assert set_persona_called["n"] == 0


def test_persona_derive_404_when_session_cross_org(recruiter_client, respx_mock):
    respx_mock.get(rest_url("intake_sessions")).mock(
        return_value=httpx.Response(200, json=_session_row(org_id=OTHER_ORG_ID))
    )
    resp = recruiter_client.post(_url("/persona/derive"), json={})
    assert resp.status_code in (403, 404)
