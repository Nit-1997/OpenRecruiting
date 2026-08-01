"""Tests for the v2 persona library router (recruiter-facing, org-scoped).

Endpoints under test (all under /api/v2):
  GET    /personas               → list the org's personas (optional ?templates=true)
  POST   /personas               → create a persona (composes composed_text)
  PUT    /personas/{id}          → update (recompose if dimensions change)
  DELETE /personas/{id}          → hard delete, org-scoped
  POST   /roles/{req}/rounds/{round}/screening/persona/select → attach an existing persona

The library service is seam-mocked so the tests assert wiring + composition
behaviour without DB. The `set_persona` attach is mocked the same way the existing
persona-router tests do. Mirrors test_screening_persona_router.py.
"""

import httpx
import pytest

from app.api.v2.routers import personas as personas_router
from app.api.v2.routers import screening as screening_router
from tests.helpers.mock_data import ORG_ID, REQ_ID, ROUND_ID, NOW
from tests.helpers.supabase_mocks import rest_url


V2_ROOT = "/api/v2"
PERSONA_LIB_ID = "11111111-1111-1111-1111-111111111111"


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


def _persona_row(*, persona_id=PERSONA_LIB_ID, is_template=True, requisition_id=None):
    return {
        "id": persona_id,
        "organization_id": ORG_ID,
        "requisition_id": requisition_id,
        "name": "Blunt senior screener",
        "dimensions": [
            {
                "key": "tone_rapport",
                "value": "Warm and direct.",
                "confidence": 0.8,
                "source": "cortex",
            }
        ],
        "composed_text": "Tone & rapport: Warm and direct.\n\nNON-NEGOTIABLE RULES: ...",
        "is_template": is_template,
        "derived_at": NOW,
    }


# ============================================================================
# auth
# ============================================================================


def test_list_requires_auth(unauthed_client):
    resp = unauthed_client.get(f"{V2_ROOT}/personas")
    assert resp.status_code in (401, 403)


def test_create_requires_auth(unauthed_client):
    resp = unauthed_client.post(f"{V2_ROOT}/personas", json={"name": "x", "dimensions": []})
    assert resp.status_code in (401, 403)


# ============================================================================
# GET /personas — list (org-scoped)
# ============================================================================


def test_list_returns_org_personas(recruiter_client, monkeypatch):
    captured = {}

    async def _fake_list(self, *, org_id, templates_only):
        captured["org_id"] = org_id
        captured["templates_only"] = templates_only
        return [_persona_row()]

    monkeypatch.setattr(personas_router.PersonaLibraryService, "list", _fake_list)

    resp = recruiter_client.get(f"{V2_ROOT}/personas")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body) == 1
    assert body[0]["id"] == PERSONA_LIB_ID
    assert body[0]["name"] == "Blunt senior screener"
    assert body[0]["is_template"] is True
    assert captured["org_id"] == ORG_ID
    assert captured["templates_only"] is False


def test_list_filters_templates(recruiter_client, monkeypatch):
    captured = {}

    async def _fake_list(self, *, org_id, templates_only):
        captured["templates_only"] = templates_only
        return []

    monkeypatch.setattr(personas_router.PersonaLibraryService, "list", _fake_list)

    resp = recruiter_client.get(f"{V2_ROOT}/personas?templates=true")
    assert resp.status_code == 200, resp.text
    assert captured["templates_only"] is True


# ============================================================================
# POST /personas — create (composes composed_text)
# ============================================================================


def test_create_composes_and_persists(recruiter_client, monkeypatch):
    persisted = {}

    async def _fake_create(
        self, *, org_id, name, dimensions, composed_text, is_template, created_by
    ):
        persisted["org_id"] = org_id
        persisted["name"] = name
        persisted["dimensions"] = dimensions
        persisted["composed_text"] = composed_text
        persisted["is_template"] = is_template
        return _persona_row(is_template=is_template)

    monkeypatch.setattr(personas_router.PersonaLibraryService, "create", _fake_create)

    body = {
        "name": "Blunt senior screener",
        "is_template": True,
        "dimensions": [
            {
                "key": "tone_rapport",
                "value": "Be blunt and fast.",
                "confidence": 1.0,
                "source": "recruiter",
            }
        ],
    }
    resp = recruiter_client.post(f"{V2_ROOT}/personas", json=body)
    assert resp.status_code in (200, 201), resp.text
    out = resp.json()
    assert out["id"] == PERSONA_LIB_ID
    assert out["is_template"] is True

    # org scoping + composition: composed_text carries the edited value AND the
    # always-appended guardrails (proves compose_persona ran).
    assert persisted["org_id"] == ORG_ID
    assert persisted["is_template"] is True
    assert "Be blunt and fast." in persisted["composed_text"]
    assert "NON-NEGOTIABLE RULES" in persisted["composed_text"]


def test_create_defaults_is_template_false(recruiter_client, monkeypatch):
    persisted = {}

    async def _fake_create(
        self, *, org_id, name, dimensions, composed_text, is_template, created_by
    ):
        persisted["is_template"] = is_template
        return _persona_row(is_template=is_template)

    monkeypatch.setattr(personas_router.PersonaLibraryService, "create", _fake_create)

    resp = recruiter_client.post(
        f"{V2_ROOT}/personas",
        json={"name": "x", "dimensions": []},
    )
    assert resp.status_code in (200, 201), resp.text
    assert persisted["is_template"] is False


# ============================================================================
# PUT /personas/{id} — update (recomposes on dimension change), org-scoped
# ============================================================================


def test_update_recomposes_on_dimension_change(recruiter_client, monkeypatch):
    updated = {}

    async def _fake_update(self, persona_id, *, org_id, name, dimensions, composed_text, is_template):
        updated["persona_id"] = persona_id
        updated["org_id"] = org_id
        updated["composed_text"] = composed_text
        updated["name"] = name
        updated["is_template"] = is_template
        return _persona_row(persona_id=persona_id)

    monkeypatch.setattr(personas_router.PersonaLibraryService, "update", _fake_update)

    body = {
        "name": "Renamed",
        "dimensions": [
            {
                "key": "eval_priorities",
                "value": "Only ownership matters.",
                "confidence": 1.0,
                "source": "recruiter",
            }
        ],
    }
    resp = recruiter_client.put(f"{V2_ROOT}/personas/{PERSONA_LIB_ID}", json=body)
    assert resp.status_code == 200, resp.text

    assert updated["persona_id"] == PERSONA_LIB_ID
    assert updated["org_id"] == ORG_ID
    assert updated["name"] == "Renamed"
    # Recomposed from the edited dimensions.
    assert "Only ownership matters." in updated["composed_text"]
    assert "NON-NEGOTIABLE RULES" in updated["composed_text"]


def test_update_404_when_not_in_org(recruiter_client, monkeypatch):
    from app.api.v2.core.exceptions import NotFoundError

    async def _fake_update(self, persona_id, **kwargs):
        raise NotFoundError("Persona not found")

    monkeypatch.setattr(personas_router.PersonaLibraryService, "update", _fake_update)

    resp = recruiter_client.put(
        f"{V2_ROOT}/personas/{PERSONA_LIB_ID}",
        json={"name": "x"},
    )
    assert resp.status_code == 404


# ============================================================================
# DELETE /personas/{id} — hard delete, org-scoped
# ============================================================================


def test_delete_org_scoped(recruiter_client, monkeypatch):
    captured = {}

    async def _fake_delete(self, persona_id, *, org_id):
        captured["persona_id"] = persona_id
        captured["org_id"] = org_id

    monkeypatch.setattr(personas_router.PersonaLibraryService, "delete", _fake_delete)

    resp = recruiter_client.delete(f"{V2_ROOT}/personas/{PERSONA_LIB_ID}")
    assert resp.status_code in (200, 204), resp.text
    assert captured["persona_id"] == PERSONA_LIB_ID
    assert captured["org_id"] == ORG_ID


def test_delete_404_cross_org(recruiter_client, monkeypatch):
    from app.api.v2.core.exceptions import NotFoundError

    async def _fake_delete(self, persona_id, *, org_id):
        raise NotFoundError("Persona not found")

    monkeypatch.setattr(personas_router.PersonaLibraryService, "delete", _fake_delete)

    resp = recruiter_client.delete(f"{V2_ROOT}/personas/{PERSONA_LIB_ID}")
    assert resp.status_code == 404


# ============================================================================
# POST /roles/{req}/rounds/{round}/screening/persona/select — attach existing
# ============================================================================


def _select_url():
    return f"{V2_ROOT}/roles/{REQ_ID}/rounds/{ROUND_ID}/screening/persona/select"


def test_select_attaches_existing_persona(recruiter_client, respx_mock, monkeypatch):
    respx_mock.get(rest_url("rounds")).mock(
        return_value=httpx.Response(200, json=_round_row())
    )

    loaded = _persona_row()

    captured = {}

    async def _fake_get(self, persona_id, *, org_id):
        captured["persona_id"] = persona_id
        captured["org_id"] = org_id
        return loaded

    set_calls = []

    async def _fake_set_persona(self, round_id, persona_id, persona_snapshot):
        set_calls.append((round_id, persona_id, persona_snapshot))
        return {"round_id": round_id, "persona_id": persona_id}

    monkeypatch.setattr(screening_router.PersonaLibraryService, "get", _fake_get)
    monkeypatch.setattr(
        screening_router.ScreeningConfigService, "set_persona", _fake_set_persona
    )

    resp = recruiter_client.post(_select_url(), json={"persona_id": PERSONA_LIB_ID})
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["persona_id"] == PERSONA_LIB_ID
    assert body["composed_text"] == loaded["composed_text"]
    assert len(body["dimensions"]) == 1

    # Loaded org-scoped, then attached to the round config via set_persona with a
    # snapshot built from the persona's dimensions + composed_text.
    assert captured["persona_id"] == PERSONA_LIB_ID
    assert captured["org_id"] == ORG_ID
    assert len(set_calls) == 1
    round_id, persona_id, snapshot = set_calls[0]
    assert round_id == ROUND_ID
    assert persona_id == PERSONA_LIB_ID
    assert snapshot["text"] == loaded["composed_text"]
    assert snapshot["dimensions"] == loaded["dimensions"]


def test_select_404_when_persona_cross_org(recruiter_client, respx_mock, monkeypatch):
    from app.api.v2.core.exceptions import NotFoundError

    respx_mock.get(rest_url("rounds")).mock(
        return_value=httpx.Response(200, json=_round_row())
    )

    async def _fake_get(self, persona_id, *, org_id):
        raise NotFoundError("Persona not found")

    monkeypatch.setattr(screening_router.PersonaLibraryService, "get", _fake_get)

    resp = recruiter_client.post(_select_url(), json={"persona_id": PERSONA_LIB_ID})
    assert resp.status_code == 404


def test_select_requires_auth(unauthed_client):
    resp = unauthed_client.post(_select_url(), json={"persona_id": PERSONA_LIB_ID})
    assert resp.status_code in (401, 403)
