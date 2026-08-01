"""
Tests for the v2 plan router — shared rounds + feedback_questions CRUD.

Endpoints under test:
  GET    /roles/{role_id}/plan
  POST   /roles/{role_id}/plan/rounds
  PUT    /plan/rounds/{round_id}
  DELETE /plan/rounds/{round_id}
  POST   /roles/{role_id}/plan/rounds/reorder   (If-Match required)
  POST   /plan/rounds/{round_id}/questions
  PUT    /plan/questions/{question_id}
  DELETE /plan/questions/{question_id}

Mocks Supabase HTTP via respx. No direct DB. Mirrors test_journey_mutations.py.
"""

import json
import httpx
from uuid import UUID

from fastapi.testclient import TestClient

from app.main import app
from app.dependencies import get_current_user, CurrentUser
from tests.helpers.mock_data import (
    ORG_ID,
    REQ_ID,
    ROUND_ID,
    RECRUITER_USER_ID,
    FEEDBACK_QUESTION_ID,
    NOW,
)
from tests.helpers.supabase_mocks import rest_url, rpc_url


V2_ROOT = "/api/v2"
OTHER_ROUND_ID = "00000000-0000-0000-0000-0000000000a1"


def _make_round_row(*, round_id=ROUND_ID, name="Phone screen", number=1):
    return {
        "id": round_id,
        "requisition_id": REQ_ID,
        "name": name,
        "category": "screening",
        "round_number": number,
        "duration_minutes": 45,
        "description": None,
        "skills": [],
        "guidelines": [],
        "ai_screenable": True,
        "ai_screenable_reason": "Voice-runnable Q&A.",
        "for_candidate_id": None,
        "removed_from_plan_at": None,
        "deleted_at": None,
        "created_at": NOW,
        "updated_at": NOW,
        "feedback_questions": [],
    }


def _make_req_row(org_id=ORG_ID):
    return {"id": REQ_ID, "organization_id": org_id, "deleted_at": None}


def _no_org_client():
    no_org_user = CurrentUser(
        id=UUID(RECRUITER_USER_ID),
        email="r@t.com",
        is_staff=False,
        organization_id=None,
    )
    app.dependency_overrides[get_current_user] = lambda: no_org_user
    return TestClient(app, raise_server_exceptions=False)


# ============================================================================
# GET /roles/{role_id}/plan
# ============================================================================


def test_get_plan_200_returns_rounds_in_order(recruiter_client, respx_mock):
    respx_mock.get(rest_url("requisitions")).mock(
        return_value=httpx.Response(200, json=_make_req_row())
    )
    respx_mock.get(rest_url("rounds")).mock(
        return_value=httpx.Response(
            200,
            json=[
                _make_round_row(name="Phone screen", number=1),
                _make_round_row(round_id=OTHER_ROUND_ID, name="Onsite", number=2),
            ],
        )
    )
    resp = recruiter_client.get(f"{V2_ROOT}/roles/{REQ_ID}/plan")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "rounds" in body
    assert [r["round_number"] for r in body["rounds"]] == [1, 2]
    assert [r["name"] for r in body["rounds"]] == ["Phone screen", "Onsite"]
    # Screening Agent Phase 1, Task 3: screenable fields surface in the read API.
    assert body["rounds"][0]["ai_screenable"] is True
    assert body["rounds"][0]["ai_screenable_reason"] == "Voice-runnable Q&A."


def test_get_plan_derives_screenable_for_conversational_category(
    recruiter_client, respx_mock
):
    # No stored flag, but a conversational category → derived True so the
    # auto-nudge works even before the intake Lambda has tagged the round.
    culture_row = _make_round_row(name="Culture fit", number=1)
    culture_row["category"] = "culture"
    culture_row["ai_screenable"] = False
    culture_row["ai_screenable_reason"] = None
    design_row = _make_round_row(round_id=OTHER_ROUND_ID, name="System design", number=2)
    design_row["category"] = "design"
    design_row["ai_screenable"] = False
    design_row["ai_screenable_reason"] = None

    respx_mock.get(rest_url("requisitions")).mock(
        return_value=httpx.Response(200, json=_make_req_row())
    )
    respx_mock.get(rest_url("rounds")).mock(
        return_value=httpx.Response(200, json=[culture_row, design_row])
    )
    resp = recruiter_client.get(f"{V2_ROOT}/roles/{REQ_ID}/plan")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # Conversational round → derived eligible; non-conversational stays false.
    assert body["rounds"][0]["ai_screenable"] is True
    assert body["rounds"][1]["ai_screenable"] is False


def test_get_plan_404_when_role_belongs_to_another_org(recruiter_client, respx_mock):
    # Supabase .single() with no match yields a 406/null — match real behavior.
    respx_mock.get(rest_url("requisitions")).mock(
        return_value=httpx.Response(
            406,
            json={"code": "PGRST116", "message": "no rows"},
        )
    )
    resp = recruiter_client.get(f"{V2_ROOT}/roles/{REQ_ID}/plan")
    assert resp.status_code == 404


def test_get_plan_403_when_user_has_no_org():
    client = _no_org_client()
    try:
        resp = client.get(f"{V2_ROOT}/roles/{REQ_ID}/plan")
        assert resp.status_code == 403
    finally:
        app.dependency_overrides.clear()


# ============================================================================
# POST /roles/{role_id}/plan/rounds
# ============================================================================


def test_add_round_201_forwards_payload_to_rpc(recruiter_client, respx_mock):
    captured = {}

    def _capture(request):
        captured["rpc"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(200, json={"round": _make_round_row(name="Final")})

    respx_mock.post(rpc_url("add_shared_round")).mock(side_effect=_capture)

    resp = recruiter_client.post(
        f"{V2_ROOT}/roles/{REQ_ID}/plan/rounds",
        json={
            "name": "Final",
            "category": "behavioral",
            "duration_minutes": 60,
            "description": "Culture + leadership signal.",
            "skills": ["leadership", "communication"],
            "feedback_questions": [
                {"heading": "Drive", "description": "How do they handle blockers?"}
            ],
        },
    )
    assert resp.status_code == 201, resp.text
    rpc = captured["rpc"]
    assert rpc["p_req_id"] == REQ_ID
    assert rpc["p_org_id"] == ORG_ID
    assert rpc["p_name"] == "Final"
    assert rpc["p_duration_minutes"] == 60
    assert rpc["p_skills"] == ["leadership", "communication"]
    assert rpc["p_feedback_questions"][0]["heading"] == "Drive"


def test_add_round_uses_default_45_minute_duration(recruiter_client, respx_mock):
    captured = {}

    def _capture(request):
        captured["rpc"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(200, json={"round": _make_round_row()})

    respx_mock.post(rpc_url("add_shared_round")).mock(side_effect=_capture)

    resp = recruiter_client.post(
        f"{V2_ROOT}/roles/{REQ_ID}/plan/rounds",
        json={"name": "Quick chat"},
    )
    assert resp.status_code == 201, resp.text
    assert captured["rpc"]["p_duration_minutes"] == 45


def test_add_round_422_when_name_missing(recruiter_client):
    resp = recruiter_client.post(
        f"{V2_ROOT}/roles/{REQ_ID}/plan/rounds",
        json={"duration_minutes": 30},
    )
    assert resp.status_code == 422


# ============================================================================
# PUT /plan/rounds/{round_id}
# ============================================================================


def test_update_round_200_patches_fields(recruiter_client, respx_mock):
    """Update goes through a direct supabase.table update (not RPC). Verify
    org-scope load happens first, then PATCH fires with the patched fields."""
    # Load the round → returns a row that belongs to ORG_ID.
    respx_mock.get(rest_url("rounds")).mock(
        return_value=httpx.Response(
            200,
            json={
                **_make_round_row(),
                "requisitions": _make_req_row(),
            },
        )
    )

    captured = {}

    def _capture_patch(request):
        captured["patch"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(200, json=[_make_round_row(name="Updated name")])

    respx_mock.patch(rest_url("rounds")).mock(side_effect=_capture_patch)

    resp = recruiter_client.put(
        f"{V2_ROOT}/plan/rounds/{ROUND_ID}",
        json={"name": "Updated name", "duration_minutes": 60},
    )
    assert resp.status_code == 200, resp.text
    assert captured["patch"]["name"] == "Updated name"
    assert captured["patch"]["duration_minutes"] == 60


def test_update_round_404_when_round_cross_org(recruiter_client, respx_mock):
    other_org = _make_round_row()
    other_org["requisitions"] = {
        "id": REQ_ID,
        "organization_id": "ffffffff-ffff-ffff-ffff-ffffffffffff",
        "deleted_at": None,
    }
    respx_mock.get(rest_url("rounds")).mock(
        return_value=httpx.Response(200, json=other_org)
    )
    resp = recruiter_client.put(
        f"{V2_ROOT}/plan/rounds/{ROUND_ID}",
        json={"name": "X"},
    )
    assert resp.status_code in (403, 404)


# ============================================================================
# DELETE /plan/rounds/{round_id}
# ============================================================================


def test_delete_round_200(recruiter_client, respx_mock):
    respx_mock.post(rpc_url("delete_shared_round")).mock(
        return_value=httpx.Response(200, json={"deleted": True})
    )
    resp = recruiter_client.delete(f"{V2_ROOT}/plan/rounds/{ROUND_ID}")
    assert resp.status_code == 200, resp.text


# ============================================================================
# POST /roles/{role_id}/plan/rounds/reorder  (If-Match required)
# ============================================================================


def test_reorder_rounds_428_without_if_match(recruiter_client):
    """Spec §8.x: reorder requires an If-Match header for optimistic
    concurrency. Without it the server returns 428 Precondition Required."""
    resp = recruiter_client.post(
        f"{V2_ROOT}/roles/{REQ_ID}/plan/rounds/reorder",
        json=[{"round_id": ROUND_ID, "round_number": 1}],
    )
    assert resp.status_code == 428


def test_reorder_rounds_422_for_invalid_body(recruiter_client):
    resp = recruiter_client.post(
        f"{V2_ROOT}/roles/{REQ_ID}/plan/rounds/reorder",
        json=[{"round_id": "not-a-uuid", "round_number": 1}],
        headers={"If-Match": "2026-05-20T01:00:00+00:00"},
    )
    assert resp.status_code == 422


# ============================================================================
# POST /plan/rounds/{round_id}/questions
# ============================================================================


def test_add_question_201_appends_to_round(recruiter_client, respx_mock):
    """Add path: org-scope round, then INSERT into feedback_questions."""
    # Round org-scope load.
    respx_mock.get(rest_url("rounds")).mock(
        return_value=httpx.Response(
            200,
            json={**_make_round_row(), "requisitions": _make_req_row()},
        )
    )
    # Existing questions count (the service typically reads max(number) — we
    # return one to assert ordering doesn't crash).
    respx_mock.get(rest_url("feedback_questions")).mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "id": FEEDBACK_QUESTION_ID,
                    "round_id": ROUND_ID,
                    "heading": "Existing",
                    "description": None,
                    "question_number": 1,
                    "deleted_at": None,
                }
            ],
        )
    )
    respx_mock.post(rest_url("feedback_questions")).mock(
        return_value=httpx.Response(
            201,
            json=[
                {
                    "id": "00000000-0000-0000-0000-0000000000c1",
                    "round_id": ROUND_ID,
                    "heading": "Drive",
                    "description": "How do they handle blockers?",
                    "question_number": 2,
                    "deleted_at": None,
                }
            ],
        )
    )

    resp = recruiter_client.post(
        f"{V2_ROOT}/plan/rounds/{ROUND_ID}/questions",
        json={"heading": "Drive", "description": "How do they handle blockers?"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["heading"] == "Drive"


def test_add_question_422_when_heading_missing(recruiter_client):
    resp = recruiter_client.post(
        f"{V2_ROOT}/plan/rounds/{ROUND_ID}/questions",
        json={"description": "no heading"},
    )
    assert resp.status_code == 422


# ============================================================================
# PUT /plan/questions/{question_id}
# ============================================================================


def test_update_question_200_patches_fields(recruiter_client, respx_mock):
    # Question load with org-scope join.
    respx_mock.get(rest_url("feedback_questions")).mock(
        return_value=httpx.Response(
            200,
            json={
                "id": FEEDBACK_QUESTION_ID,
                "round_id": ROUND_ID,
                "heading": "Old",
                "description": None,
                "question_number": 1,
                "deleted_at": None,
                "rounds": {
                    **_make_round_row(),
                    "requisitions": _make_req_row(),
                },
            },
        )
    )

    def _capture_patch(request):
        return httpx.Response(
            200,
            json=[{
                "id": FEEDBACK_QUESTION_ID,
                "round_id": ROUND_ID,
                "heading": "New heading",
                "description": "fresh",
                "question_number": 1,
            }],
        )

    respx_mock.patch(rest_url("feedback_questions")).mock(side_effect=_capture_patch)

    resp = recruiter_client.put(
        f"{V2_ROOT}/plan/questions/{FEEDBACK_QUESTION_ID}",
        json={"heading": "New heading", "description": "fresh"},
    )
    assert resp.status_code == 200, resp.text


# ============================================================================
# DELETE /plan/questions/{question_id}
# ============================================================================


def test_delete_question_200(recruiter_client, respx_mock):
    respx_mock.get(rest_url("feedback_questions")).mock(
        return_value=httpx.Response(
            200,
            json={
                "id": FEEDBACK_QUESTION_ID,
                "round_id": ROUND_ID,
                "heading": "Q",
                "description": None,
                "question_number": 1,
                "deleted_at": None,
                "rounds": {**_make_round_row(), "requisitions": _make_req_row()},
            },
        )
    )
    respx_mock.patch(rest_url("feedback_questions")).mock(
        return_value=httpx.Response(200, json=[{"id": FEEDBACK_QUESTION_ID}])
    )
    resp = recruiter_client.delete(
        f"{V2_ROOT}/plan/questions/{FEEDBACK_QUESTION_ID}"
    )
    assert resp.status_code == 200, resp.text
