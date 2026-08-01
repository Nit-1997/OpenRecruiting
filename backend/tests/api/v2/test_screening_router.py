"""Tests for the v2 screening config router (recruiter-facing).

Endpoints under test (all under /api/v2):
  POST /roles/{requisition_id}/rounds/{round_id}/screening/generate
  GET  /roles/{requisition_id}/rounds/{round_id}/screening
  PUT  /roles/{requisition_id}/rounds/{round_id}/screening
  POST /roles/{requisition_id}/rounds/{round_id}/screening/attach
  POST /roles/{requisition_id}/rounds/{round_id}/screening/detach

Org-scope round loads go through respx (real Supabase path). The LLM generator
and the config service are seam-mocked so the tests assert wiring + persistence
behaviour without network or DB. Mirrors test_plan_router.py + the screening
service test seam style.
"""

import httpx
import pytest

from app.api.v2.routers import screening as screening_router
from app.api.v2.schemas.screening import ScreeningQuestion
from tests.helpers.mock_data import (
    CANDIDATE_ID,
    CANDIDATE_ROUND_ID,
    ORG_ID,
    REQ_ID,
    ROUND_ID,
    NOW,
)
from tests.helpers.supabase_mocks import rest_url


V2_ROOT = "/api/v2"
OTHER_ORG_ID = "ffffffff-ffff-ffff-ffff-ffffffffffff"


def _round_row(*, org_id=ORG_ID, req_id=REQ_ID):
    """A round row joined to its requisition (org-scope shape)."""
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
            "must_have_skills": ["Python", "distributed systems"],
            "good_to_have_skills": ["Kafka"],
        },
    }


def _gen_url(suffix=""):
    return f"{V2_ROOT}/roles/{REQ_ID}/rounds/{ROUND_ID}/screening{suffix}"


# ============================================================================
# auth
# ============================================================================


def test_generate_requires_auth(unauthed_client):
    resp = unauthed_client.post(_gen_url("/generate"), json={})
    assert resp.status_code in (401, 403)


# ============================================================================
# POST /generate — draft, not persisted
# ============================================================================


def test_generate_returns_draft(recruiter_client, respx_mock, monkeypatch):
    respx_mock.get(rest_url("rounds")).mock(
        return_value=httpx.Response(200, json=_round_row())
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

    upsert_called = {"n": 0}

    async def _fail_upsert(self, *args, **kwargs):
        upsert_called["n"] += 1
        return {}

    monkeypatch.setattr(
        screening_router.ScreeningQuestionGenerator, "generate", _fake_generate
    )
    monkeypatch.setattr(
        screening_router.ScreeningConfigService, "upsert", _fail_upsert
    )

    resp = recruiter_client.post(
        _gen_url("/generate"), json={"preferences": "lean on incident response"}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    # Draft config carries the round_id + the generated questions.
    assert body["round_id"] == ROUND_ID
    assert len(body["questions"]) == 1
    assert body["questions"][0]["title"] == "Toughest incident"
    assert body["questions"][0]["signal"] == "EXECUTION"

    # NOT persisted.
    assert upsert_called["n"] == 0

    # role_context + must_haves were sourced from the requisition.
    assert "Senior Backend Engineer" in captured["role_context"]
    assert captured["must_haves"] == ["Python", "distributed systems"]
    # Phase 1: cortex gaps are an empty placeholder.
    assert captured["cortex_gaps"] == []
    assert captured["preferences"] == "lean on incident response"


def test_generate_404_when_round_cross_org(recruiter_client, respx_mock):
    respx_mock.get(rest_url("rounds")).mock(
        return_value=httpx.Response(200, json=_round_row(org_id=OTHER_ORG_ID))
    )
    resp = recruiter_client.post(_gen_url("/generate"), json={})
    assert resp.status_code in (403, 404)


# ============================================================================
# GET / — read config
# ============================================================================


def test_get_returns_config(recruiter_client, respx_mock, monkeypatch):
    respx_mock.get(rest_url("rounds")).mock(
        return_value=httpx.Response(200, json=_round_row())
    )

    async def _fake_get(self, round_id):
        return {
            "round_id": round_id,
            "enabled": True,
            "voice": "aura-luna-en",
            "questions": [{"title": "Q1", "prompt": "P1"}],
        }

    monkeypatch.setattr(screening_router.ScreeningConfigService, "get", _fake_get)

    resp = recruiter_client.get(_gen_url())
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["round_id"] == ROUND_ID
    assert body["enabled"] is True
    assert body["questions"][0]["title"] == "Q1"


# ============================================================================
# PUT / — save persists
# ============================================================================


def test_save_persists(recruiter_client, respx_mock, monkeypatch):
    respx_mock.get(rest_url("rounds")).mock(
        return_value=httpx.Response(200, json=_round_row())
    )

    captured = {}

    async def _fake_upsert(self, cfg, *, requisition_id, created_by):
        captured["cfg_round_id"] = cfg.round_id
        captured["requisition_id"] = requisition_id
        captured["created_by"] = created_by
        captured["n_questions"] = len(cfg.questions)
        return {"config_id": "cfg-1"}

    async def _fake_get(self, round_id):
        return {"round_id": round_id, "enabled": False, "questions": []}

    monkeypatch.setattr(
        screening_router.ScreeningConfigService, "upsert", _fake_upsert
    )
    monkeypatch.setattr(screening_router.ScreeningConfigService, "get", _fake_get)

    resp = recruiter_client.put(
        _gen_url(),
        json={
            "round_id": ROUND_ID,
            "enabled": False,
            "questions": [{"title": "Q1", "prompt": "P1"}],
        },
    )
    assert resp.status_code == 200, resp.text

    assert captured["cfg_round_id"] == ROUND_ID
    assert captured["requisition_id"] == REQ_ID
    # created_by is the authenticated recruiter.
    assert captured["created_by"] is not None
    assert captured["n_questions"] == 1


# ============================================================================
# attach / detach — flip enabled
# ============================================================================


def test_attach_detach(recruiter_client, respx_mock, monkeypatch):
    respx_mock.get(rest_url("rounds")).mock(
        return_value=httpx.Response(200, json=_round_row())
    )

    calls = []
    # The DB-stored config tracks `enabled`; get() reflects the current value
    # plus the persisted questions, mirroring the real service.
    stored = {"enabled": False}

    async def _fake_set_enabled(self, round_id, enabled):
        calls.append((round_id, enabled))
        stored["enabled"] = enabled
        return {"round_id": round_id, "enabled": enabled}

    async def _fake_get(self, round_id):
        return {
            "round_id": round_id,
            "enabled": stored["enabled"],
            "voice": "aura-luna-en",
            "validity_days": 7,
            "questions": [{"title": "Q1", "prompt": "P1"}],
        }

    monkeypatch.setattr(
        screening_router.ScreeningConfigService, "set_enabled", _fake_set_enabled
    )
    monkeypatch.setattr(screening_router.ScreeningConfigService, "get", _fake_get)

    resp = recruiter_client.post(_gen_url("/attach"))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # Attach returns the FULL config (not just {round_id, enabled}) so the panel
    # keeps its questions/voice/validity after toggling.
    assert body["round_id"] == ROUND_ID
    assert body["enabled"] is True
    assert body["voice"] == "aura-luna-en"
    assert body["validity_days"] == 7
    assert body["questions"][0]["title"] == "Q1"

    resp = recruiter_client.post(_gen_url("/detach"))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["enabled"] is False
    # Detach also returns the full config with questions intact.
    assert body["questions"][0]["title"] == "Q1"

    assert calls == [(ROUND_ID, True), (ROUND_ID, False)]


def test_attach_preserves_existing_questions(recruiter_client, respx_mock, monkeypatch):
    """Regression: attach must NOT drop the recruiter's saved questions/config.

    Before the fix the route returned set_enabled's thin {round_id, enabled};
    the panel's setConfig(result) then wiped questions until reload. The route
    now returns the full saved config from get()."""
    respx_mock.get(rest_url("rounds")).mock(
        return_value=httpx.Response(200, json=_round_row())
    )

    existing_questions = [
        {"title": "Toughest incident", "prompt": "P1", "order_index": 0},
        {"title": "Pricing instinct", "prompt": "P2", "order_index": 1},
    ]

    async def _fake_set_enabled(self, round_id, enabled):
        return {"round_id": round_id, "enabled": enabled}

    async def _fake_get(self, round_id):
        return {
            "round_id": round_id,
            "enabled": True,
            "voice": "aura-luna-en",
            "follow_up_style": "adaptive_probes",
            "est_duration_minutes": 18,
            "validity_days": 14,
            "deploy_scope": "all_resume_passed",
            "questions": existing_questions,
        }

    monkeypatch.setattr(
        screening_router.ScreeningConfigService, "set_enabled", _fake_set_enabled
    )
    monkeypatch.setattr(screening_router.ScreeningConfigService, "get", _fake_get)

    resp = recruiter_client.post(_gen_url("/attach"))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["enabled"] is True
    # The two saved questions survive the attach toggle.
    assert len(body["questions"]) == 2
    assert [q["title"] for q in body["questions"]] == [
        "Toughest incident",
        "Pricing instinct",
    ]
    # Other config fields are preserved too.
    assert body["validity_days"] == 14
    assert body["deploy_scope"] == "all_resume_passed"


def test_attach_404_when_no_config(recruiter_client, respx_mock, monkeypatch):
    """Hardening: attach on a round with no saved config must NOT return null.

    set_enabled updates 0 rows when no round_screening_configs row exists, and
    get() then returns None. Returning that null breaks the client
    (configFromWire(null) → "Cannot read properties of null (reading 'round_id')").
    The route now raises a clear 404 ("save it first")."""
    respx_mock.get(rest_url("rounds")).mock(
        return_value=httpx.Response(200, json=_round_row())
    )

    async def _fake_set_enabled(self, round_id, enabled):
        return {"round_id": round_id, "enabled": enabled}

    async def _fake_get(self, round_id):
        return None

    monkeypatch.setattr(
        screening_router.ScreeningConfigService, "set_enabled", _fake_set_enabled
    )
    monkeypatch.setattr(screening_router.ScreeningConfigService, "get", _fake_get)

    resp = recruiter_client.post(_gen_url("/attach"))
    assert resp.status_code == 404, resp.text
    # No null body, no raw exception text.
    body = resp.json()
    assert body is not None
    detail = body.get("detail", "")
    assert "save" in detail.lower()


def test_detach_404_when_no_config(recruiter_client, respx_mock, monkeypatch):
    respx_mock.get(rest_url("rounds")).mock(
        return_value=httpx.Response(200, json=_round_row())
    )

    async def _fake_set_enabled(self, round_id, enabled):
        return {"round_id": round_id, "enabled": enabled}

    async def _fake_get(self, round_id):
        return None

    monkeypatch.setattr(
        screening_router.ScreeningConfigService, "set_enabled", _fake_set_enabled
    )
    monkeypatch.setattr(screening_router.ScreeningConfigService, "get", _fake_get)

    resp = recruiter_client.post(_gen_url("/detach"))
    assert resp.status_code == 404, resp.text


# ============================================================================
# POST /invite — candidate screening invites
# ============================================================================


class _FakeInviteService:
    def __init__(self):
        self.sent: list[dict] = []

    async def send_invite_email_for_token(self, **kwargs):
        self.sent.append(kwargs)


def _wire_invite(monkeypatch, *, config, rpc_calls):
    async def _fake_get(self, round_id):
        return config

    async def _fake_call_rpc(supabase, name, params):
        rpc_calls.append((name, params))
        return {"token": params["p"]["token"]}

    fake_svc = _FakeInviteService()

    monkeypatch.setattr(screening_router.ScreeningConfigService, "get", _fake_get)
    monkeypatch.setattr(screening_router, "call_rpc", _fake_call_rpc)
    monkeypatch.setattr(
        screening_router, "get_screening_invite_service", lambda: fake_svc
    )
    return fake_svc


def test_invite_explicit_emails(recruiter_client, respx_mock, monkeypatch):
    respx_mock.get(rest_url("rounds")).mock(
        return_value=httpx.Response(200, json=_round_row())
    )
    rpc_calls = []
    fake_svc = _wire_invite(
        monkeypatch,
        config={"round_id": ROUND_ID, "validity_days": 14, "questions": []},
        rpc_calls=rpc_calls,
    )

    resp = recruiter_client.post(
        _gen_url("/invite"),
        json={"emails": ["A@Example.com", "a@example.com", "b@example.com"]},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # De-duped (case-insensitive) → 2 invites.
    assert body["invited"] == 2
    assert body["validity_days"] == 14
    assert body["email_failures"] == []

    # One RPC + one email per unique candidate, with the screening RPC name.
    assert len(rpc_calls) == 2
    assert all(name == "screening_create_invite" for name, _ in rpc_calls)
    assert {c["email"] for c in fake_svc.sent} == {"a@example.com", "b@example.com"}
    # role_title flows from the requisition.
    assert all(c["role_title"] == "Senior Backend Engineer" for c in fake_svc.sent)


def test_invite_scope_all_resume_passed(recruiter_client, respx_mock, monkeypatch):
    respx_mock.get(rest_url("rounds")).mock(
        return_value=httpx.Response(200, json=_round_row())
    )
    # scope path queries candidates by requisition + active status.
    respx_mock.get(rest_url("candidates")).mock(
        return_value=httpx.Response(
            200, json=[{"email": "c1@example.com"}, {"email": "c2@example.com"}]
        )
    )
    rpc_calls = []
    _wire_invite(
        monkeypatch,
        config={"round_id": ROUND_ID, "validity_days": 7, "questions": []},
        rpc_calls=rpc_calls,
    )

    resp = recruiter_client.post(
        _gen_url("/invite"), json={"scope": "all_resume_passed"}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["invited"] == 2
    assert len(rpc_calls) == 2


def test_reinvite_supersedes_with_fresh_token(recruiter_client, respx_mock, monkeypatch):
    """Re-invite idempotency: inviting the SAME candidate_round twice re-runs the
    screening_create_invite RPC each time with a FRESH, distinct token.

    The RPC (migration 115) deletes any prior active invite for the round before
    inserting the new one — so the second call supersedes the first. The DB-level
    delete-then-insert can't be unit-tested here, but the route's contract that
    drives it can: each /invite call must exercise the RPC path with a new token
    (never reuse the prior one, never short-circuit on the existing invite)."""
    # Round-load REST mock is satisfied per request; mock both invite calls.
    respx_mock.get(rest_url("rounds")).mock(
        return_value=httpx.Response(200, json=_round_row())
    )
    rpc_calls = []
    _wire_invite(
        monkeypatch,
        config={"round_id": ROUND_ID, "validity_days": 7, "questions": []},
        rpc_calls=rpc_calls,
    )

    first = recruiter_client.post(
        _gen_url("/invite"), json={"emails": ["dupe@example.com"]}
    )
    second = recruiter_client.post(
        _gen_url("/invite"), json={"emails": ["dupe@example.com"]}
    )

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.json()["invited"] == 1
    assert second.json()["invited"] == 1

    # The RPC was invoked once per invite call (re-invite is NOT short-circuited).
    assert len(rpc_calls) == 2
    assert all(name == "screening_create_invite" for name, _ in rpc_calls)
    assert all(params["p"]["email"] == "dupe@example.com" for _, params in rpc_calls)

    # Each call minted a FRESH token (the supersession driver) — the second token
    # is distinct from the first, so the RPC's delete-then-insert replaces it.
    first_token = rpc_calls[0][1]["p"]["token"]
    second_token = rpc_calls[1][1]["p"]["token"]
    assert first_token and second_token
    assert first_token != second_token


def test_invite_400_when_no_config(recruiter_client, respx_mock, monkeypatch):
    respx_mock.get(rest_url("rounds")).mock(
        return_value=httpx.Response(200, json=_round_row())
    )

    async def _none_get(self, round_id):
        return None

    monkeypatch.setattr(screening_router.ScreeningConfigService, "get", _none_get)

    resp = recruiter_client.post(
        _gen_url("/invite"), json={"emails": ["x@y.com"]}
    )
    assert resp.status_code in (400, 422)


def test_invite_400_when_no_emails(recruiter_client, respx_mock, monkeypatch):
    respx_mock.get(rest_url("rounds")).mock(
        return_value=httpx.Response(200, json=_round_row())
    )
    _wire_invite(
        monkeypatch,
        config={"round_id": ROUND_ID, "validity_days": 7, "questions": []},
        rpc_calls=[],
    )

    resp = recruiter_client.post(_gen_url("/invite"), json={})
    assert resp.status_code in (400, 422)


def test_invite_requires_auth(unauthed_client):
    resp = unauthed_client.post(_gen_url("/invite"), json={"emails": ["x@y.com"]})
    assert resp.status_code in (401, 403)


# ============================================================================
# POST /screening/candidate-rounds/{id}/invite — per-candidate-round invite
# ("scheduling" a OpenRecruiting-hosted round = send the candidate the screening link)
# ============================================================================


def _cr_url(cr_id=CANDIDATE_ROUND_ID):
    return f"{V2_ROOT}/screening/candidate-rounds/{cr_id}/invite"


def _candidate_round_row(*, org_id=ORG_ID, email="pipeline@example.com"):
    """A candidate_round joined candidate → requisition (org-scope shape)."""
    return {
        "id": CANDIDATE_ROUND_ID,
        "round_id": ROUND_ID,
        "candidates": {
            "id": CANDIDATE_ID,
            "email": email,
            "name": "Pipeline Candidate",
            "requisition_id": REQ_ID,
            "deleted_at": None,
            "requisitions": {
                "id": REQ_ID,
                "organization_id": org_id,
                "deleted_at": None,
                "role_title": "Senior Backend Engineer",
            },
        },
    }


class _FakeExistingInviteService:
    def __init__(self):
        self.calls: list[dict] = []

    async def invite_existing_candidate_round(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "token": "tok-cr-1",
            "expires_at": "2030-01-01T00:00:00+00:00",
            "verify_url": "http://localhost:3000/screening/tok-cr-1/verify",
        }


def test_invite_candidate_round_success(recruiter_client, respx_mock, monkeypatch):
    respx_mock.get(rest_url("candidate_rounds")).mock(
        return_value=httpx.Response(200, json=_candidate_round_row())
    )

    async def _enabled_config(self, round_id):
        return {"round_id": round_id, "enabled": True, "validity_days": 12, "questions": []}

    fake_svc = _FakeExistingInviteService()
    monkeypatch.setattr(screening_router.ScreeningConfigService, "get", _enabled_config)
    monkeypatch.setattr(
        screening_router, "get_screening_invite_service", lambda: fake_svc
    )

    resp = recruiter_client.post(_cr_url())
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["token"] == "tok-cr-1"
    assert body["verify_url"].endswith("/screening/tok-cr-1/verify")
    assert body["validity_days"] == 12

    # Service was called with the candidate's email + the round's validity window.
    assert len(fake_svc.calls) == 1
    call = fake_svc.calls[0]
    assert call["candidate_round_id"] == CANDIDATE_ROUND_ID
    assert call["email"] == "pipeline@example.com"
    assert call["validity_days"] == 12
    assert call["role_title"] == "Senior Backend Engineer"


def test_invite_candidate_round_404_cross_org(recruiter_client, respx_mock, monkeypatch):
    respx_mock.get(rest_url("candidate_rounds")).mock(
        return_value=httpx.Response(200, json=_candidate_round_row(org_id=OTHER_ORG_ID))
    )

    async def _enabled_config(self, round_id):
        return {"round_id": round_id, "enabled": True, "validity_days": 7, "questions": []}

    monkeypatch.setattr(screening_router.ScreeningConfigService, "get", _enabled_config)
    monkeypatch.setattr(
        screening_router, "get_screening_invite_service", lambda: _FakeExistingInviteService()
    )

    resp = recruiter_client.post(_cr_url())
    assert resp.status_code in (403, 404)


def test_invite_candidate_round_404_when_missing(recruiter_client, respx_mock):
    respx_mock.get(rest_url("candidate_rounds")).mock(
        return_value=httpx.Response(200, json=[])
    )
    resp = recruiter_client.post(_cr_url())
    assert resp.status_code == 404


def test_invite_candidate_round_409_when_not_platform_hosted(
    recruiter_client, respx_mock, monkeypatch
):
    respx_mock.get(rest_url("candidate_rounds")).mock(
        return_value=httpx.Response(200, json=_candidate_round_row())
    )

    async def _disabled_config(self, round_id):
        # Config exists but screening is not enabled → not a OpenRecruiting round.
        return {"round_id": round_id, "enabled": False, "validity_days": 7, "questions": []}

    called = {"n": 0}

    class _GuardService:
        async def invite_existing_candidate_round(self, **kwargs):
            called["n"] += 1
            return {}

    monkeypatch.setattr(screening_router.ScreeningConfigService, "get", _disabled_config)
    monkeypatch.setattr(
        screening_router, "get_screening_invite_service", lambda: _GuardService()
    )

    resp = recruiter_client.post(_cr_url())
    assert resp.status_code in (400, 409)
    # Must NOT send an invite for a non-OpenRecruiting round.
    assert called["n"] == 0


def test_invite_candidate_round_409_when_no_config(
    recruiter_client, respx_mock, monkeypatch
):
    respx_mock.get(rest_url("candidate_rounds")).mock(
        return_value=httpx.Response(200, json=_candidate_round_row())
    )

    async def _none_config(self, round_id):
        return None

    monkeypatch.setattr(screening_router.ScreeningConfigService, "get", _none_config)
    resp = recruiter_client.post(_cr_url())
    assert resp.status_code in (400, 409)


def test_invite_candidate_round_requires_auth(unauthed_client):
    resp = unauthed_client.post(_cr_url())
    assert resp.status_code in (401, 403)
