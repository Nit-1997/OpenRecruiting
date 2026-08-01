"""
Tests for the v2 feedback router (PR 4b §8.2 — feedback endpoints).

Endpoints under test:
  POST /candidate-rounds/{cr_id}/feedback           → human submit
  POST /candidate-rounds/{cr_id}/request-feedback   → notification (email/slack)
  POST /candidate-rounds/{cr_id}/reprocess          → Lambda re-run

Mocks Supabase via respx; mocks the FeedbackNotificationService and
FeedbackJobService via monkeypatch so no Slack / Lambda / Recall calls
fire. Naming pattern matches test_journey_mutations.py.
"""

import json
import httpx
import pytest
from uuid import UUID

from fastapi.testclient import TestClient

from app.main import app
from app.dependencies import get_current_user, CurrentUser
from tests.helpers.mock_data import (
    ORG_ID,
    REQ_ID,
    ROUND_ID,
    CANDIDATE_ID,
    CANDIDATE_ROUND_ID,
    FEEDBACK_QUESTION_ID,
    RECRUITER_USER_ID,
    NOW,
)
from tests.helpers.supabase_mocks import rest_url, rpc_url


V2_ROOT = "/api/v2"


def _make_cr_with_round(*, status_val="completed", processing_status="none"):
    """Shape the candidate_rounds + embedded rounds/candidates/requisitions
    join that _load_cr_with_round_for_org expects. Defaults to a
    completed round so reprocess tests don't need to override it."""
    return {
        "id": CANDIDATE_ROUND_ID,
        "candidate_id": CANDIDATE_ID,
        "round_id": ROUND_ID,
        "status": status_val,
        "processing_status": processing_status,
        "scheduled_at": NOW if status_val != "pending" else None,
        "completed_at": NOW if status_val == "completed" else None,
        "meeting_url": None,
        "interviewer_email": None,
        "rating": None,
        "summary": None,
        "scorecard_status": "pending",
        "created_at": NOW,
        "updated_at": NOW,
        "rounds": {
            "id": ROUND_ID,
            "assessment_template_id": None,
            "name": "Phone screen",
            "round_number": 1,
            "deleted_at": None,
        },
        "candidates": {
            "id": CANDIDATE_ID,
            "name": "Alice Example",
            "email": "alice@example.com",
            "requisition_id": REQ_ID,
            "deleted_at": None,
            "requisitions": {
                "id": REQ_ID,
                "organization_id": ORG_ID,
                "status": "planned",
                "deleted_at": None,
            },
        },
    }


def _valid_submit_body():
    return {
        "entries": [
            {
                "feedback_question_id": FEEDBACK_QUESTION_ID,
                "feedback_text": "Strong communication.",
                "evidence_status": "verified",
                "evidence": ["Said 'X'", "Demonstrated Y"],
            }
        ],
        "rating": "strong_yes",
        "summary": "Recommend advancing.",
    }


def _no_org_client():
    no_org_user = CurrentUser(
        id=UUID(RECRUITER_USER_ID),
        email="recruiter@test.com",
        is_staff=False,
        organization_id=None,
    )
    app.dependency_overrides[get_current_user] = lambda: no_org_user
    return TestClient(app, raise_server_exceptions=False)


# ============================================================================
# POST /candidate-rounds/{cr_id}/feedback — submit_feedback
# ============================================================================


def test_submit_feedback_200_writes_entries_and_rating(recruiter_client, respx_mock):
    captured = {}

    def _capture(request):
        captured["rpc_body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(
            200,
            json={
                "candidate_round": _make_cr_with_round(status_val="completed"),
                "entries": [
                    {
                        "id": "00000000-0000-0000-0000-000000000070",
                        "feedback_question_id": FEEDBACK_QUESTION_ID,
                        "feedback_text": "Strong communication.",
                        "evidence_status": "verified",
                        "evidence": ["Said 'X'", "Demonstrated Y"],
                    }
                ],
            },
        )

    respx_mock.post(rpc_url("submit_human_feedback")).mock(side_effect=_capture)

    resp = recruiter_client.post(
        f"{V2_ROOT}/candidate-rounds/{CANDIDATE_ROUND_ID}/feedback",
        json=_valid_submit_body(),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["candidate_round"]["status"] == "completed"
    assert len(body["entries"]) == 1
    assert body["entries"][0]["evidence_status"] == "verified"

    rpc = captured["rpc_body"]
    assert rpc["p_cr_id"] == CANDIDATE_ROUND_ID
    assert rpc["p_org_id"] == ORG_ID
    assert rpc["p_rating"] == "strong_yes"
    assert rpc["p_summary"] == "Recommend advancing."
    assert rpc["p_entries"][0]["feedback_question_id"] == FEEDBACK_QUESTION_ID
    assert rpc["p_entries"][0]["evidence"] == ["Said 'X'", "Demonstrated Y"]


def test_submit_feedback_drops_scorecard_field_silently(recruiter_client, respx_mock):
    """`scorecard` is accepted but not persisted — spec §8.2 forward-compat."""
    captured = {}

    def _capture(request):
        captured["rpc_body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(
            200,
            json={
                "candidate_round": _make_cr_with_round(status_val="completed"),
                "entries": [],
            },
        )

    respx_mock.post(rpc_url("submit_human_feedback")).mock(side_effect=_capture)

    body = _valid_submit_body()
    body["scorecard"] = {"hire_recommendation": "yes", "extra": "data"}
    resp = recruiter_client.post(
        f"{V2_ROOT}/candidate-rounds/{CANDIDATE_ROUND_ID}/feedback",
        json=body,
    )
    assert resp.status_code == 200, resp.text
    assert "p_scorecard" not in captured["rpc_body"]


def test_submit_feedback_422_invalid_rating(recruiter_client):
    body = _valid_submit_body()
    body["rating"] = "definitely_yes"
    resp = recruiter_client.post(
        f"{V2_ROOT}/candidate-rounds/{CANDIDATE_ROUND_ID}/feedback",
        json=body,
    )
    assert resp.status_code == 422
    assert "rating" in resp.text


def test_submit_feedback_422_invalid_evidence_status(recruiter_client):
    body = _valid_submit_body()
    body["entries"][0]["evidence_status"] = "maybe"
    resp = recruiter_client.post(
        f"{V2_ROOT}/candidate-rounds/{CANDIDATE_ROUND_ID}/feedback",
        json=body,
    )
    assert resp.status_code == 422


def test_submit_feedback_422_when_entries_missing(recruiter_client):
    resp = recruiter_client.post(
        f"{V2_ROOT}/candidate-rounds/{CANDIDATE_ROUND_ID}/feedback",
        json={"rating": "yes", "summary": "ok"},
    )
    assert resp.status_code == 422


def test_submit_feedback_403_when_user_has_no_org():
    client = _no_org_client()
    try:
        resp = client.post(
            f"{V2_ROOT}/candidate-rounds/{CANDIDATE_ROUND_ID}/feedback",
            json=_valid_submit_body(),
        )
        assert resp.status_code == 403
    finally:
        app.dependency_overrides.clear()


def test_submit_feedback_surfaces_rpc_error_as_upstream(recruiter_client, respx_mock):
    """A 5xx from Postgres bubbles up as a 502 Bad Gateway (upstream service
    error). The FE v2-client already masks raw detail for the user (commit
    3cc0902), but the BE still includes "RPC error: 42P01 boom" in the
    response body — confirmed by this test. That's a separate hardening
    item; pinning behaviour here so we notice when it changes."""
    respx_mock.post(rpc_url("submit_human_feedback")).mock(
        return_value=httpx.Response(
            500,
            json={"code": "42P01", "message": "boom"},
        )
    )
    resp = recruiter_client.post(
        f"{V2_ROOT}/candidate-rounds/{CANDIDATE_ROUND_ID}/feedback",
        json=_valid_submit_body(),
    )
    assert resp.status_code == 502
    # KNOWN: raw Postgres code leaks in the BE response body. The FE
    # v2-client substitutes a friendly string before showing the user
    # (commit 3cc0902). When the BE is hardened to drop the raw code, flip
    # this to `not in`.
    assert "42P01" in resp.text


# ============================================================================
# POST /candidate-rounds/{cr_id}/request-feedback — notification
# ============================================================================


def test_request_feedback_email_200(recruiter_client, respx_mock, monkeypatch):
    respx_mock.get(rest_url("candidate_rounds")).mock(
        return_value=httpx.Response(200, json=[_make_cr_with_round(status_val="scheduled")])
    )
    respx_mock.patch(rest_url("candidate_rounds")).mock(
        return_value=httpx.Response(200, json=[_make_cr_with_round()])
    )

    captured = {}

    class _FakeSvc:
        async def _get_candidate_round_context(self, cr_id):
            captured["cr_id"] = cr_id
            return {"candidate": {"name": "Alice"}, "round": {"name": "Phone screen"}}

        async def send_capture_request_to_interviewer(self, interviewer, ctx, cr_id):
            captured["interviewer"] = interviewer
            captured["context"] = ctx
            return {"sent": True, "message_id": "msg_abc123"}

    monkeypatch.setattr(
        "app.services.feedback_notification_service.get_feedback_notification_service",
        lambda: _FakeSvc(),
    )

    resp = recruiter_client.post(
        f"{V2_ROOT}/candidate-rounds/{CANDIDATE_ROUND_ID}/request-feedback",
        json={"interviewer_email": "jordan@example.com", "channel": "email"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body == {"sent": True, "request_id": "msg_abc123", "channel": "email"}
    # Interviewer name defaulted from email local-part when not provided.
    assert captured["interviewer"] == ("jordan@example.com", "jordan")


def test_request_feedback_uses_explicit_interviewer_name_when_provided(
    recruiter_client, respx_mock, monkeypatch
):
    respx_mock.get(rest_url("candidate_rounds")).mock(
        return_value=httpx.Response(200, json=[_make_cr_with_round(status_val="scheduled")])
    )
    respx_mock.patch(rest_url("candidate_rounds")).mock(
        return_value=httpx.Response(200, json=[_make_cr_with_round()])
    )

    captured = {}

    class _FakeSvc:
        async def _get_candidate_round_context(self, cr_id):
            return {"candidate": {"name": "Alice"}}

        async def send_capture_request_to_interviewer(self, interviewer, ctx, cr_id):
            captured["interviewer"] = interviewer
            return {"sent": True, "message_id": "msg_xyz"}

    monkeypatch.setattr(
        "app.services.feedback_notification_service.get_feedback_notification_service",
        lambda: _FakeSvc(),
    )

    resp = recruiter_client.post(
        f"{V2_ROOT}/candidate-rounds/{CANDIDATE_ROUND_ID}/request-feedback",
        json={
            "interviewer_email": "jordan@example.com",
            "interviewer_name": "Jordan Lee",
            "channel": "email",
        },
    )
    assert resp.status_code == 200, resp.text
    assert captured["interviewer"] == ("jordan@example.com", "Jordan Lee")


def test_request_feedback_slack_returns_501(recruiter_client, respx_mock):
    """The Slack channel for request-feedback isn't wired yet — must 501,
    not silently succeed."""
    respx_mock.get(rest_url("candidate_rounds")).mock(
        return_value=httpx.Response(200, json=[_make_cr_with_round(status_val="scheduled")])
    )
    respx_mock.patch(rest_url("candidate_rounds")).mock(
        return_value=httpx.Response(200, json=[_make_cr_with_round()])
    )

    resp = recruiter_client.post(
        f"{V2_ROOT}/candidate-rounds/{CANDIDATE_ROUND_ID}/request-feedback",
        json={"interviewer_email": "j@example.com", "channel": "slack"},
    )
    assert resp.status_code == 501


def test_request_feedback_422_invalid_email(recruiter_client):
    resp = recruiter_client.post(
        f"{V2_ROOT}/candidate-rounds/{CANDIDATE_ROUND_ID}/request-feedback",
        json={"interviewer_email": "not-an-email", "channel": "email"},
    )
    assert resp.status_code == 422


def test_request_feedback_422_invalid_channel(recruiter_client):
    resp = recruiter_client.post(
        f"{V2_ROOT}/candidate-rounds/{CANDIDATE_ROUND_ID}/request-feedback",
        json={"interviewer_email": "j@example.com", "channel": "carrier_pigeon"},
    )
    assert resp.status_code == 422


def test_request_feedback_404_when_cr_cross_org(recruiter_client, respx_mock):
    """A CR belonging to another org must not leak through this endpoint."""
    other_org_cr = _make_cr_with_round(status_val="scheduled")
    other_org_cr["candidates"]["requisitions"]["organization_id"] = (
        "ffffffff-ffff-ffff-ffff-ffffffffffff"
    )
    respx_mock.get(rest_url("candidate_rounds")).mock(
        return_value=httpx.Response(200, json=[other_org_cr])
    )

    resp = recruiter_client.post(
        f"{V2_ROOT}/candidate-rounds/{CANDIDATE_ROUND_ID}/request-feedback",
        json={"interviewer_email": "j@example.com", "channel": "email"},
    )
    assert resp.status_code in (403, 404)


def test_request_feedback_500_when_notification_service_throws(
    recruiter_client, respx_mock, monkeypatch
):
    respx_mock.get(rest_url("candidate_rounds")).mock(
        return_value=httpx.Response(200, json=[_make_cr_with_round(status_val="scheduled")])
    )
    respx_mock.patch(rest_url("candidate_rounds")).mock(
        return_value=httpx.Response(200, json=[_make_cr_with_round()])
    )

    class _BrokenSvc:
        async def _get_candidate_round_context(self, cr_id):
            return {"candidate": {"name": "Alice"}}

        async def send_capture_request_to_interviewer(self, *_a, **_kw):
            raise RuntimeError("smtp exploded")

    monkeypatch.setattr(
        "app.services.feedback_notification_service.get_feedback_notification_service",
        lambda: _BrokenSvc(),
    )

    resp = recruiter_client.post(
        f"{V2_ROOT}/candidate-rounds/{CANDIDATE_ROUND_ID}/request-feedback",
        json={"interviewer_email": "j@example.com", "channel": "email"},
    )
    assert resp.status_code == 500


def test_request_feedback_persists_interviewer_email_update(
    recruiter_client, respx_mock, monkeypatch
):
    """The recruiter's freshly-picked interviewer_email must be UPDATEd onto
    the candidate_round row before the notification fires."""
    captured = {}

    respx_mock.get(rest_url("candidate_rounds")).mock(
        return_value=httpx.Response(200, json=[_make_cr_with_round(status_val="scheduled")])
    )

    def _capture_patch(request):
        captured["patch_body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(200, json=[_make_cr_with_round()])

    respx_mock.patch(rest_url("candidate_rounds")).mock(side_effect=_capture_patch)

    class _FakeSvc:
        async def _get_candidate_round_context(self, cr_id):
            # Service-level falsy check rejects `{}` — return a marker dict.
            return {"candidate": {"name": "Alice"}}

        async def send_capture_request_to_interviewer(self, *_a, **_kw):
            return {"sent": True, "message_id": "msg_1"}

    monkeypatch.setattr(
        "app.services.feedback_notification_service.get_feedback_notification_service",
        lambda: _FakeSvc(),
    )

    resp = recruiter_client.post(
        f"{V2_ROOT}/candidate-rounds/{CANDIDATE_ROUND_ID}/request-feedback",
        json={"interviewer_email": "jordan@example.com", "channel": "email"},
    )
    assert resp.status_code == 200, resp.text
    assert captured["patch_body"]["interviewer_email"] == "jordan@example.com"


# ============================================================================
# POST /candidate-rounds/{cr_id}/reprocess — Lambda re-run
# ============================================================================


def test_reprocess_200_triggers_lambda(recruiter_client, respx_mock, monkeypatch):
    respx_mock.get(rest_url("candidate_rounds")).mock(
        return_value=httpx.Response(
            200, json=[_make_cr_with_round(status_val="completed")]
        )
    )

    captured = {}

    class _FakeJobSvc:
        async def trigger_feedback_processing(self, cr_id, skip_prereq_check=False):
            captured["cr_id"] = cr_id
            captured["skip_prereq_check"] = skip_prereq_check

    monkeypatch.setattr(
        "app.services.feedback_job_service.get_feedback_job_service",
        lambda: _FakeJobSvc(),
    )

    resp = recruiter_client.post(
        f"{V2_ROOT}/candidate-rounds/{CANDIDATE_ROUND_ID}/reprocess",
        json={"force": False},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["candidate_round_id"] == CANDIDATE_ROUND_ID
    assert body["processing_status"] == "processing"
    assert "triggered_at" in body

    assert captured["cr_id"] == CANDIDATE_ROUND_ID
    assert captured["skip_prereq_check"] is False


def test_reprocess_400_when_round_not_completed(recruiter_client, respx_mock):
    """Reprocess requires status=completed — pending CR must 400."""
    respx_mock.get(rest_url("candidate_rounds")).mock(
        return_value=httpx.Response(
            200, json=[_make_cr_with_round(status_val="pending")]
        )
    )

    resp = recruiter_client.post(
        f"{V2_ROOT}/candidate-rounds/{CANDIDATE_ROUND_ID}/reprocess",
        json={"force": False},
    )
    assert resp.status_code == 400
    assert "completed" in resp.text.lower()


def test_reprocess_409_when_already_processing_and_not_forced(
    recruiter_client, respx_mock
):
    respx_mock.get(rest_url("candidate_rounds")).mock(
        return_value=httpx.Response(
            200,
            json=[
                _make_cr_with_round(
                    status_val="completed", processing_status="processing"
                )
            ],
        )
    )

    resp = recruiter_client.post(
        f"{V2_ROOT}/candidate-rounds/{CANDIDATE_ROUND_ID}/reprocess",
        json={"force": False},
    )
    assert resp.status_code == 409
    assert "ALREADY_PROCESSING" in resp.text or "already" in resp.text.lower()


def test_reprocess_force_true_passes_skip_prereq_check(
    recruiter_client, respx_mock, monkeypatch
):
    """force=true must propagate to the Lambda's skip_prereq_check — the
    Lambda's writes are idempotent on cr_id so this is safe (CLAUDE.md
    'Lambda Code — Mandatory Rules' May 2026 incident)."""
    respx_mock.get(rest_url("candidate_rounds")).mock(
        return_value=httpx.Response(
            200,
            json=[
                _make_cr_with_round(
                    status_val="completed", processing_status="processing"
                )
            ],
        )
    )

    captured = {}

    class _FakeJobSvc:
        async def trigger_feedback_processing(self, cr_id, skip_prereq_check=False):
            captured["skip_prereq_check"] = skip_prereq_check

    monkeypatch.setattr(
        "app.services.feedback_job_service.get_feedback_job_service",
        lambda: _FakeJobSvc(),
    )

    resp = recruiter_client.post(
        f"{V2_ROOT}/candidate-rounds/{CANDIDATE_ROUND_ID}/reprocess",
        json={"force": True},
    )
    assert resp.status_code == 200, resp.text
    assert captured["skip_prereq_check"] is True


def test_reprocess_500_when_lambda_trigger_throws(
    recruiter_client, respx_mock, monkeypatch
):
    respx_mock.get(rest_url("candidate_rounds")).mock(
        return_value=httpx.Response(
            200, json=[_make_cr_with_round(status_val="completed")]
        )
    )

    class _BrokenJobSvc:
        async def trigger_feedback_processing(self, *_a, **_kw):
            raise RuntimeError("lambda quota")

    monkeypatch.setattr(
        "app.services.feedback_job_service.get_feedback_job_service",
        lambda: _BrokenJobSvc(),
    )

    resp = recruiter_client.post(
        f"{V2_ROOT}/candidate-rounds/{CANDIDATE_ROUND_ID}/reprocess",
        json={"force": False},
    )
    assert resp.status_code == 500


def test_reprocess_403_when_user_has_no_org():
    client = _no_org_client()
    try:
        resp = client.post(
            f"{V2_ROOT}/candidate-rounds/{CANDIDATE_ROUND_ID}/reprocess",
            json={"force": False},
        )
        assert resp.status_code == 403
    finally:
        app.dependency_overrides.clear()


def test_reprocess_404_when_cr_cross_org(recruiter_client, respx_mock):
    other_org_cr = _make_cr_with_round(status_val="completed")
    other_org_cr["candidates"]["requisitions"]["organization_id"] = (
        "ffffffff-ffff-ffff-ffff-ffffffffffff"
    )
    respx_mock.get(rest_url("candidate_rounds")).mock(
        return_value=httpx.Response(200, json=[other_org_cr])
    )

    resp = recruiter_client.post(
        f"{V2_ROOT}/candidate-rounds/{CANDIDATE_ROUND_ID}/reprocess",
        json={"force": False},
    )
    assert resp.status_code in (403, 404)
