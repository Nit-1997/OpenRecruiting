"""
Tests for the role-detail v2 read endpoints.

Spec: docs/superpowers/specs/2026-05-18-roles-detail-v2-api-design.md
Mocks Supabase HTTP via respx (same pattern as v1 tests).
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
    CANDIDATE_ID,
    CANDIDATE_ROUND_ID,
    ROUND_ID,
    FEEDBACK_QUESTION_ID,
    RECRUITER_USER_ID,
    NOW,
)
from tests.helpers.supabase_mocks import rest_url, rpc_url


V2_ROOT = "/api/v2"


# ============================================
# Fixtures / helpers
# ============================================


def _no_org_client():
    no_org_user = CurrentUser(
        id=UUID(RECRUITER_USER_ID),
        email="recruiter@test.com",
        is_staff=False,
        organization_id=None,
    )
    app.dependency_overrides[get_current_user] = lambda: no_org_user
    return TestClient(app, raise_server_exceptions=False)


def _make_role_header_row(
    req_id: str = REQ_ID,
    org_id: str = ORG_ID,
    created_by_full_name: str = "Jane Recruiter",
):
    return {
        "id": req_id,
        "organization_id": org_id,
        "created_by": RECRUITER_USER_ID,
        "role_title": "Senior Backend Engineer",
        "role_location": "Remote",
        "status": "planned",
        "experience_min_years": 5,
        "experience_max_years": 8,
        "must_have_skills": ["Python", "Postgres"],
        "good_to_have_skills": ["Go"],
        "job_description": "Build great backends.",
        "intake_notes": "Notes from intake.",
        "created_at": NOW,
        "updated_at": NOW,
        "deleted_at": None,
        # Aliased embedded select key (see roles.py).
        "created_by_profile": {"full_name": created_by_full_name},
    }


# ============================================
# GET /roles/{id} — header
# ============================================


def test_get_role_header_returns_expected_shape(recruiter_client, respx_mock):
    respx_mock.get(rest_url("requisitions")).mock(
        return_value=httpx.Response(200, json=[_make_role_header_row()])
    )
    # Candidate counts query — return a mix of statuses.
    respx_mock.get(rest_url("candidates")).mock(
        return_value=httpx.Response(200, json=[
            {"status": "active"},
            {"status": "active"},
            {"status": "hired"},
            {"status": "rejected"},
            {"status": "withdrawn"},
        ])
    )
    # Rounds-total query — 3 shared, non-removed, non-deleted rounds.
    respx_mock.get(rest_url("rounds")).mock(
        return_value=httpx.Response(200, json=[
            {"id": "r1"}, {"id": "r2"}, {"id": "r3"},
        ])
    )
    # Creator-name lookup (separate query — see role_service.get_role_header).
    respx_mock.get(rest_url("profiles")).mock(
        return_value=httpx.Response(200, json=[{"full_name": "Jane Recruiter"}])
    )

    resp = recruiter_client.get(f"{V2_ROOT}/roles/{REQ_ID}")
    assert resp.status_code == 200, resp.text

    data = resp.json()
    assert data["id"] == REQ_ID
    assert data["role_title"] == "Senior Backend Engineer"
    assert data["role_location"] == "Remote"
    assert data["status"] == "planned"
    # department is not a column today — must be null.
    assert data["department"] is None
    assert data["created_by"] == RECRUITER_USER_ID
    # Confirm the joined profiles full_name comes through correctly.
    assert data["created_by_name"] == "Jane Recruiter"
    assert data["experience_min_years"] == 5
    assert data["experience_max_years"] == 8
    assert data["must_have_skills"] == ["Python", "Postgres"]
    assert data["good_to_have_skills"] == ["Go"]
    assert data["job_description"] == "Build great backends."
    assert data["intake_notes"] == "Notes from intake."
    assert isinstance(data["days_open"], int)
    # Provenance defaults when the row predates phase-2 columns.
    assert data["source"] == "native"
    assert data["ats_provider"] is None
    # Counts derived in Python.
    assert data["counts"] == {
        "candidates_total": 5,
        "candidates_active": 2,
        "candidates_hired": 1,
        "candidates_rejected": 1,
        "rounds_total": 3,
    }


def test_get_role_header_403_when_no_org(respx_mock):
    with _no_org_client() as client:
        resp = client.get(f"{V2_ROOT}/roles/{REQ_ID}")
    assert resp.status_code == 403


def test_get_role_header_404_when_org_mismatch(recruiter_client, respx_mock):
    # Requisition lookup returns empty (no row matches org_id).
    respx_mock.get(rest_url("requisitions")).mock(
        return_value=httpx.Response(200, json=[])
    )
    resp = recruiter_client.get(f"{V2_ROOT}/roles/{REQ_ID}")
    assert resp.status_code == 404


def test_list_roles_returns_paginated_shape_with_status_counts(recruiter_client, respx_mock):
    """
    GET /roles should return {items, page, page_size, total, status_counts}
    with per-item pipeline.{round_count, candidate_count}. Designed for the
    rail's three-tab parallel-prefetch pattern.
    """
    second_req_id = "11111111-1111-1111-1111-111111111111"

    def _requisitions(request):
        params = dict(request.url.params)
        # Status-counts query: no status filter, just org_id.
        if "status" not in params:
            return httpx.Response(200, json=[
                {"status": "planned"},
                {"status": "planned"},
                {"status": "intake_pending"},
                {"status": "closed"},
                {"status": "closed"},
                {"status": "closed"},
            ])
        # List slice + count (both filtered to status=planned).
        return httpx.Response(
            200,
            headers={"content-range": "0-1/2"},
            json=[
                _make_role_header_row(req_id=REQ_ID),
                _make_role_header_row(req_id=second_req_id),
            ],
        )

    respx_mock.get(rest_url("requisitions")).mock(side_effect=_requisitions)

    # Pipeline rounds + candidates batches.
    respx_mock.get(rest_url("rounds")).mock(
        return_value=httpx.Response(200, json=[
            {"id": "r1", "requisition_id": REQ_ID},
            {"id": "r2", "requisition_id": REQ_ID},
            {"id": "r3", "requisition_id": REQ_ID},
            {"id": "r4", "requisition_id": second_req_id},
        ])
    )
    respx_mock.get(rest_url("candidates")).mock(
        return_value=httpx.Response(200, json=[
            {"id": "c1", "requisition_id": REQ_ID},
            {"id": "c2", "requisition_id": REQ_ID},
            {"id": "c3", "requisition_id": REQ_ID},
            {"id": "c4", "requisition_id": REQ_ID},
            {"id": "c5", "requisition_id": REQ_ID},
            {"id": "c6", "requisition_id": REQ_ID},
            {"id": "c7", "requisition_id": REQ_ID},
            {"id": "c8", "requisition_id": REQ_ID},
            {"id": "c9", "requisition_id": REQ_ID},
            {"id": "c10", "requisition_id": REQ_ID},
            {"id": "c11", "requisition_id": REQ_ID},
            {"id": "c12", "requisition_id": REQ_ID},
            {"id": "c13", "requisition_id": second_req_id},
        ])
    )

    resp = recruiter_client.get(
        f"{V2_ROOT}/roles?status=planned&page=1&page_size=10"
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # Top-level shape per the design image.
    assert body["page"] == 1
    assert body["page_size"] == 10
    assert "items" in body and isinstance(body["items"], list)
    assert "status_counts" in body
    # Org-wide bucketed counts (independent of status filter).
    assert body["status_counts"] == {"open": 2, "pending": 1, "closed": 3}
    # Per-item pipeline.
    by_id = {item["id"]: item for item in body["items"]}
    assert by_id[REQ_ID]["pipeline"] == {"round_count": 3, "candidate_count": 12}
    assert by_id[second_req_id]["pipeline"] == {"round_count": 1, "candidate_count": 1}


def test_list_roles_no_status_filter_returns_all(recruiter_client, respx_mock):
    """Omitting status filter must include all non-soft-deleted requisitions
    and still surface status_counts."""

    def _requisitions(_request):
        return httpx.Response(
            200,
            headers={"content-range": "0-0/1"},
            json=[_make_role_header_row()],
        )

    respx_mock.get(rest_url("requisitions")).mock(side_effect=_requisitions)
    respx_mock.get(rest_url("rounds")).mock(
        return_value=httpx.Response(200, json=[])
    )
    respx_mock.get(rest_url("candidates")).mock(
        return_value=httpx.Response(200, json=[])
    )

    resp = recruiter_client.get(f"{V2_ROOT}/roles")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["page"] == 1
    # Default page_size from the route signature.
    assert body["page_size"] == 10
    assert len(body["items"]) == 1


def test_list_roles_search_applies_or_filter(recruiter_client, respx_mock):
    """A search query must reach PostgREST as an `or=(...)` filter over
    role_title + role_location, NOT raise AttributeError. Regression guard for
    the `.or_` vs `.or_filter` method-name mismatch that 500'd every search."""
    captured = {}

    def _requisitions(request):
        params = dict(request.url.params)
        # The status_counts query carries no `or`; capture the search slice.
        if "or" in params:
            captured["or"] = params["or"]
        return httpx.Response(
            200,
            headers={"content-range": "0-0/1"},
            json=[_make_role_header_row()],
        )

    respx_mock.get(rest_url("requisitions")).mock(side_effect=_requisitions)
    respx_mock.get(rest_url("rounds")).mock(
        return_value=httpx.Response(200, json=[])
    )
    respx_mock.get(rest_url("candidates")).mock(
        return_value=httpx.Response(200, json=[])
    )

    resp = recruiter_client.get(f"{V2_ROOT}/roles?q=engineer")
    assert resp.status_code == 200, resp.text
    assert captured.get("or") == (
        "(role_title.ilike.*engineer*,role_location.ilike.*engineer*)"
    )


def test_list_roles_403_when_no_org(respx_mock):
    with _no_org_client() as client:
        resp = client.get(f"{V2_ROOT}/roles")
    assert resp.status_code == 403


def test_get_role_header_looks_up_profile_full_name(recruiter_client, respx_mock):
    """
    Verify the separate profiles lookup queries for `full_name` keyed by the
    requisition's created_by id. (Embedded selects were dropped — see
    role_service.get_role_header: PostgREST silently returns no rows when
    the FK disambiguation syntax doesn't resolve to our named constraint.)
    """
    captured_profiles = {}

    respx_mock.get(rest_url("requisitions")).mock(
        return_value=httpx.Response(200, json=[_make_role_header_row()])
    )
    respx_mock.get(rest_url("candidates")).mock(
        return_value=httpx.Response(200, json=[])
    )
    respx_mock.get(rest_url("rounds")).mock(
        return_value=httpx.Response(200, json=[])
    )

    def _capture_profiles(request):
        captured_profiles["select"] = request.url.params.get("select")
        captured_profiles["id"] = request.url.params.get("id")
        return httpx.Response(
            200, json=[{"full_name": "Jane Recruiter"}]
        )

    respx_mock.get(rest_url("profiles")).mock(side_effect=_capture_profiles)

    resp = recruiter_client.get(f"{V2_ROOT}/roles/{REQ_ID}")
    assert resp.status_code == 200, resp.text
    assert captured_profiles.get("select") == "full_name"
    assert captured_profiles.get("id") == f"eq.{RECRUITER_USER_ID}"
    assert resp.json()["created_by_name"] == "Jane Recruiter"


# ============================================
# GET /roles/{id}/candidates — RPC passthrough
# ============================================


def test_get_role_candidates_calls_rpc_once_with_correct_args(recruiter_client, respx_mock):
    captured_bodies = []

    def _capture(request):
        captured_bodies.append(json.loads(request.content.decode("utf-8")))
        return httpx.Response(200, json={"candidates": [
            {
                "id": CANDIDATE_ID,
                "name": "Alice",
                "email": "alice@example.com",
                "status": "active",
                "final_verdict": None,
                "created_at": NOW,
                "candidate_rounds": [],
            }
        ]})

    rpc_route = respx_mock.post(rpc_url("get_role_pipeline")).mock(side_effect=_capture)

    resp = recruiter_client.get(f"{V2_ROOT}/roles/{REQ_ID}/candidates")
    assert resp.status_code == 200, resp.text

    # RPC called exactly once with the right parameters.
    assert rpc_route.call_count == 1
    assert len(captured_bodies) == 1
    assert captured_bodies[0] == {
        "p_req_id": REQ_ID,
        "p_org_id": ORG_ID,
    }

    data = resp.json()
    assert "candidates" in data
    assert len(data["candidates"]) == 1
    assert data["candidates"][0]["id"] == CANDIDATE_ID


def test_get_role_candidates_403_when_no_org(respx_mock):
    with _no_org_client() as client:
        resp = client.get(f"{V2_ROOT}/roles/{REQ_ID}/candidates")
    assert resp.status_code == 403


def test_get_role_candidates_empty_passthrough(recruiter_client, respx_mock):
    """RPC returns JSON null when nothing matches — we still respond 200 with candidates: []."""
    # `content=b"null"` produces a body that parses to Python None — the path
    # we want to exercise. httpx's `json=None` produces an empty body, which
    # is a different (error) case.
    respx_mock.post(rpc_url("get_role_pipeline")).mock(
        return_value=httpx.Response(
            200,
            content=b"null",
            headers={"content-type": "application/json"},
        )
    )
    resp = recruiter_client.get(f"{V2_ROOT}/roles/{REQ_ID}/candidates")
    assert resp.status_code == 200
    assert resp.json() == {"candidates": []}


# ============================================
# GET /roles/{id}/plan — PostgREST embedded
# ============================================


def test_get_role_plan_filters_shared_active_rounds_only(recruiter_client, respx_mock):
    """
    Verify the rounds query filters by:
      requisition_id = X
      AND for_candidate_id IS NULL
      AND removed_from_plan_at IS NULL
      AND deleted_at IS NULL
    """
    captured = {}

    def _capture(request):
        captured["params"] = dict(request.url.params)
        return httpx.Response(200, json=[
            {
                "id": ROUND_ID,
                "round_number": 1,
                "name": "Technical Screen",
                "category": "coding",
                "duration_minutes": 45,
                "description": "Coding round.",
                "skills": ["Python"],
                "guidelines": [],
                "feedback_questions": [
                    {
                        "id": FEEDBACK_QUESTION_ID,
                        "question_number": 1,
                        "heading": "Problem Solving",
                        "description": "Eval problem solving.",
                        "deleted_at": None,
                    },
                    {
                        # Deleted question — must be filtered out.
                        "id": "00000000-0000-0000-0000-0000000000ff",
                        "question_number": 2,
                        "heading": "Should be filtered",
                        "description": None,
                        "deleted_at": NOW,
                    },
                ],
            }
        ])

    # Requisition existence check.
    respx_mock.get(rest_url("requisitions")).mock(
        return_value=httpx.Response(200, json=[{"id": REQ_ID}])
    )
    respx_mock.get(rest_url("rounds")).mock(side_effect=_capture)

    resp = recruiter_client.get(f"{V2_ROOT}/roles/{REQ_ID}/plan")
    assert resp.status_code == 200, resp.text

    params = captured["params"]
    assert params.get("requisition_id") == f"eq.{REQ_ID}"
    assert params.get("for_candidate_id") == "is.null"
    assert params.get("removed_from_plan_at") == "is.null"
    assert params.get("deleted_at") == "is.null"

    data = resp.json()
    assert "rounds" in data
    assert len(data["rounds"]) == 1
    rnd = data["rounds"][0]
    assert rnd["id"] == ROUND_ID
    # Deleted feedback question must NOT be present.
    assert len(rnd["feedback_questions"]) == 1
    assert rnd["feedback_questions"][0]["id"] == FEEDBACK_QUESTION_ID
    assert rnd["feedback_questions"][0]["heading"] == "Problem Solving"


def test_get_role_plan_404_when_org_mismatch(recruiter_client, respx_mock):
    respx_mock.get(rest_url("requisitions")).mock(
        return_value=httpx.Response(200, json=[])
    )
    resp = recruiter_client.get(f"{V2_ROOT}/roles/{REQ_ID}/plan")
    assert resp.status_code == 404


def test_get_role_plan_403_when_no_org(respx_mock):
    with _no_org_client() as client:
        resp = client.get(f"{V2_ROOT}/roles/{REQ_ID}/plan")
    assert resp.status_code == 403


# ============================================
# GET /roles/{id}/candidates/{cid}/packet — RPC passthrough
# ============================================


def test_get_candidate_packet_calls_rpc_once_with_correct_args(recruiter_client, respx_mock):
    captured_bodies = []

    def _capture(request):
        captured_bodies.append(json.loads(request.content.decode("utf-8")))
        return httpx.Response(200, json={
            "candidate": {"id": CANDIDATE_ID, "name": "Alice"},
            "rounds": [],
        })

    rpc_route = respx_mock.post(rpc_url("get_candidate_packet")).mock(side_effect=_capture)

    resp = recruiter_client.get(
        f"{V2_ROOT}/roles/{REQ_ID}/candidates/{CANDIDATE_ID}/packet"
    )
    assert resp.status_code == 200, resp.text
    assert rpc_route.call_count == 1
    assert captured_bodies[0] == {
        "p_candidate_id": CANDIDATE_ID,
        "p_org_id": ORG_ID,
    }
    body = resp.json()
    assert body["candidate"]["id"] == CANDIDATE_ID
    assert body["rounds"] == []


def test_get_candidate_packet_404_when_rpc_returns_null_candidate(recruiter_client, respx_mock):
    # RPC returns shape with candidate=null when the candidate is missing or
    # belongs to a different org. We turn that into 404.
    respx_mock.post(rpc_url("get_candidate_packet")).mock(
        return_value=httpx.Response(200, json={"candidate": None, "rounds": None})
    )
    resp = recruiter_client.get(
        f"{V2_ROOT}/roles/{REQ_ID}/candidates/{CANDIDATE_ID}/packet"
    )
    assert resp.status_code == 404


def test_get_candidate_packet_403_when_no_org(respx_mock):
    with _no_org_client() as client:
        resp = client.get(
            f"{V2_ROOT}/roles/{REQ_ID}/candidates/{CANDIDATE_ID}/packet"
        )
    assert resp.status_code == 403


# ============================================
# GET /candidate-rounds/{cr_id}/recording-url — Recall.ai live
# Spec §7 row 5. Returns { url, expires_at } from a fresh pre-signed URL.
# ============================================


def _make_cr_join_row(org_id: str = ORG_ID):
    """Shape the candidate_rounds + embedded rounds/candidates/requisitions
    join that _load_cr_with_round_for_org expects."""
    return {
        "id": CANDIDATE_ROUND_ID,
        "candidate_id": CANDIDATE_ID,
        "round_id": ROUND_ID,
        "status": "completed",
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
                "organization_id": org_id,
                "status": "planned",
                "deleted_at": None,
            },
        },
    }


class _FakeRecallService:
    """Stand-in for app.services.recall_service.RecallService.

    The endpoint uses get_recording_urls() and close(). Configure the return
    value (or exception) per-test via the factory below.
    """

    def __init__(self, *, return_value=None, raise_exc: Exception | None = None):
        self._return_value = return_value
        self._raise_exc = raise_exc
        self.closed = False

    async def get_recording_urls(self, bot_id: str):
        if self._raise_exc is not None:
            raise self._raise_exc
        return self._return_value

    async def close(self):
        self.closed = True


def _patch_recall_service(monkeypatch, *, return_value=None, raise_exc=None):
    fake = _FakeRecallService(return_value=return_value, raise_exc=raise_exc)
    monkeypatch.setattr(
        "app.services.recall_service.get_recall_service",
        lambda: fake,
    )
    return fake


def test_get_recording_url_403_when_no_org(respx_mock):
    with _no_org_client() as client:
        resp = client.get(
            f"{V2_ROOT}/candidate-rounds/{CANDIDATE_ROUND_ID}/recording-url"
        )
    assert resp.status_code == 403


def test_get_recording_url_404_when_cross_org(recruiter_client, respx_mock):
    """CR in a different org must 404 — never leak existence."""
    other_org_id = "00000000-0000-0000-0000-000000000099"
    respx_mock.get(rest_url("candidate_rounds")).mock(
        return_value=httpx.Response(200, json=[_make_cr_join_row(org_id=other_org_id)])
    )
    resp = recruiter_client.get(
        f"{V2_ROOT}/candidate-rounds/{CANDIDATE_ROUND_ID}/recording-url"
    )
    assert resp.status_code == 404


def test_get_recording_url_404_when_no_bot(recruiter_client, respx_mock):
    """No recall_bots row → 404."""
    respx_mock.get(rest_url("candidate_rounds")).mock(
        return_value=httpx.Response(200, json=[_make_cr_join_row()])
    )
    respx_mock.get(rest_url("recall_bots")).mock(
        return_value=httpx.Response(200, json=[])
    )
    resp = recruiter_client.get(
        f"{V2_ROOT}/candidate-rounds/{CANDIDATE_ROUND_ID}/recording-url"
    )
    assert resp.status_code == 404
    body = resp.json()
    assert "No recording" in body["detail"]


def test_get_recording_url_409_when_bot_not_ready(recruiter_client, respx_mock):
    """Bot exists but status isn't in the ready set → 409 with status echoed."""
    respx_mock.get(rest_url("candidate_rounds")).mock(
        return_value=httpx.Response(200, json=[_make_cr_join_row()])
    )
    respx_mock.get(rest_url("recall_bots")).mock(
        return_value=httpx.Response(200, json=[{
            "id": "00000000-0000-0000-0000-0000000000aa",
            "recall_bot_id": "recall-bot-ext-123",
            "status": "in_call_recording",  # not yet "done"
            "recording_url": None,
        }])
    )
    resp = recruiter_client.get(
        f"{V2_ROOT}/candidate-rounds/{CANDIDATE_ROUND_ID}/recording-url"
    )
    assert resp.status_code == 409
    body = resp.json()
    # detail is a structured dict — message + bot_status
    detail = body["detail"]
    assert detail["message"] == "Recording not ready yet"
    assert detail["bot_status"] == "in_call_recording"


def test_get_recording_url_409_when_done_but_no_cached_url(
    recruiter_client, respx_mock, monkeypatch
):
    """Bot status='done' with no cached recording_url and Recall returns no
    video_url → 409. This is the first-fetch path (migration 86 cache empty);
    the endpoint calls Recall to populate the cache, but Recall says the
    rendering isn't actually finished yet, so surface as 'not ready'."""
    respx_mock.get(rest_url("candidate_rounds")).mock(
        return_value=httpx.Response(200, json=[_make_cr_join_row()])
    )
    respx_mock.get(rest_url("recall_bots")).mock(
        return_value=httpx.Response(200, json=[{
            "id": "00000000-0000-0000-0000-0000000000aa",
            "recall_bot_id": "recall-bot-ext-123",
            "status": "done",
            "recording_url": None,
            "recording_url_expires_at": None,
        }])
    )
    # Recall confirms the bot exists but has not produced a video_url yet
    # (rendering still in progress on their side).
    _patch_recall_service(monkeypatch, return_value={
        "video_url": None,
        "video_duration": None,
        "transcript_url": None,
        "participants": [],
        "participants_download_url": None,
        "speaker_timeline_url": None,
    })
    resp = recruiter_client.get(
        f"{V2_ROOT}/candidate-rounds/{CANDIDATE_ROUND_ID}/recording-url"
    )
    assert resp.status_code == 409
    body = resp.json()
    assert body["detail"]["message"] == "Recording not ready yet"


def test_get_recording_url_200_returns_url_and_expires_at(
    recruiter_client, respx_mock, monkeypatch
):
    """Bot is ready and Recall returns a video_url → 200 with fresh URL + expires_at."""
    respx_mock.get(rest_url("candidate_rounds")).mock(
        return_value=httpx.Response(200, json=[_make_cr_join_row()])
    )
    respx_mock.get(rest_url("recall_bots")).mock(
        return_value=httpx.Response(200, json=[{
            "id": "00000000-0000-0000-0000-0000000000aa",
            "recall_bot_id": "recall-bot-ext-123",
            "status": "done",
            "recording_url": "https://stale-cached-url.example.com/old.mp4",
        }])
    )
    fresh_url = "https://recall-presigned.example.com/abc123.mp4?sig=xxx"
    fake = _patch_recall_service(
        monkeypatch,
        return_value={
            "video_url": fresh_url,
            "video_duration": 1800,
            "transcript_url": None,
            "participants": [],
            "participants_download_url": None,
            "speaker_timeline_url": None,
        },
    )

    resp = recruiter_client.get(
        f"{V2_ROOT}/candidate-rounds/{CANDIDATE_ROUND_ID}/recording-url"
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # Returned URL is the fresh one from Recall, NOT the stale cached one.
    assert body["url"] == fresh_url
    assert "expires_at" in body
    # Parseable ISO 8601 timestamp.
    from datetime import datetime as _dt
    _ = _dt.fromisoformat(body["expires_at"])
    # close() must have been called (no leaked httpx client).
    assert fake.closed is True


def test_get_recording_url_409_when_recall_returns_no_video_url(
    recruiter_client, respx_mock, monkeypatch
):
    """Recall returns a response but with no video_url → 409 (don't fall back to stale)."""
    respx_mock.get(rest_url("candidate_rounds")).mock(
        return_value=httpx.Response(200, json=[_make_cr_join_row()])
    )
    respx_mock.get(rest_url("recall_bots")).mock(
        return_value=httpx.Response(200, json=[{
            "id": "00000000-0000-0000-0000-0000000000aa",
            "recall_bot_id": "recall-bot-ext-123",
            "status": "done",
            "recording_url": "https://stale.example.com/old.mp4",
        }])
    )
    _patch_recall_service(monkeypatch, return_value=None)

    resp = recruiter_client.get(
        f"{V2_ROOT}/candidate-rounds/{CANDIDATE_ROUND_ID}/recording-url"
    )
    assert resp.status_code == 409


def test_get_recording_url_502_when_recall_raises(
    recruiter_client, respx_mock, monkeypatch
):
    """Recall service errors → 502."""
    from app.services.recall_service import RecallServiceError

    respx_mock.get(rest_url("candidate_rounds")).mock(
        return_value=httpx.Response(200, json=[_make_cr_join_row()])
    )
    respx_mock.get(rest_url("recall_bots")).mock(
        return_value=httpx.Response(200, json=[{
            "id": "00000000-0000-0000-0000-0000000000aa",
            "recall_bot_id": "recall-bot-ext-123",
            "status": "done",
            "recording_url": "https://stale.example.com/old.mp4",
        }])
    )
    _patch_recall_service(
        monkeypatch,
        raise_exc=RecallServiceError("Failed to get bot: 503", status_code=503),
    )

    resp = recruiter_client.get(
        f"{V2_ROOT}/candidate-rounds/{CANDIDATE_ROUND_ID}/recording-url"
    )
    assert resp.status_code == 502
    assert "Recall" in resp.json()["detail"]


def test_get_recording_url_502_when_recall_raises_unexpected(
    recruiter_client, respx_mock, monkeypatch
):
    """Any unexpected exception from Recall path also produces a clean 502."""
    respx_mock.get(rest_url("candidate_rounds")).mock(
        return_value=httpx.Response(200, json=[_make_cr_join_row()])
    )
    respx_mock.get(rest_url("recall_bots")).mock(
        return_value=httpx.Response(200, json=[{
            "id": "00000000-0000-0000-0000-0000000000aa",
            "recall_bot_id": "recall-bot-ext-123",
            "status": "done",
            "recording_url": "https://stale.example.com/old.mp4",
        }])
    )
    _patch_recall_service(monkeypatch, raise_exc=RuntimeError("network blip"))

    resp = recruiter_client.get(
        f"{V2_ROOT}/candidate-rounds/{CANDIDATE_ROUND_ID}/recording-url"
    )
    assert resp.status_code == 502


def test_get_recording_url_cache_hit_skips_recall(
    recruiter_client, respx_mock, monkeypatch
):
    """Migration 86 cache: when recording_url_expires_at is in the future,
    the endpoint serves the cached URL without touching Recall."""
    from datetime import datetime as _dt, timedelta as _td, timezone as _tz

    cached_url = "https://cached.example.com/abc123.mp4"
    expires_at = (_dt.now(_tz.utc) + _td(minutes=30)).isoformat()

    respx_mock.get(rest_url("candidate_rounds")).mock(
        return_value=httpx.Response(200, json=[_make_cr_join_row()])
    )
    respx_mock.get(rest_url("recall_bots")).mock(
        return_value=httpx.Response(200, json=[{
            "id": "00000000-0000-0000-0000-0000000000aa",
            "recall_bot_id": "recall-bot-ext-123",
            "status": "done",
            "recording_url": cached_url,
            "recording_url_expires_at": expires_at,
        }])
    )

    # Patch Recall to raise — if the endpoint hits Recall, the test fails.
    _patch_recall_service(monkeypatch, raise_exc=RuntimeError("should not be called"))

    resp = recruiter_client.get(
        f"{V2_ROOT}/candidate-rounds/{CANDIDATE_ROUND_ID}/recording-url"
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["url"] == cached_url
    assert body["expires_at"] == expires_at


def test_get_recording_url_cache_stale_remints(
    recruiter_client, respx_mock, monkeypatch
):
    """When recording_url_expires_at is in the past, the endpoint refreshes
    from Recall and writes the new URL + new expires_at back to the cache."""
    from datetime import datetime as _dt, timedelta as _td, timezone as _tz

    stale_url = "https://stale.example.com/old.mp4"
    past_expires = (_dt.now(_tz.utc) - _td(minutes=5)).isoformat()
    fresh_url = "https://fresh.example.com/new.mp4?sig=xyz"

    respx_mock.get(rest_url("candidate_rounds")).mock(
        return_value=httpx.Response(200, json=[_make_cr_join_row()])
    )
    respx_mock.get(rest_url("recall_bots")).mock(
        return_value=httpx.Response(200, json=[{
            "id": "00000000-0000-0000-0000-0000000000aa",
            "recall_bot_id": "recall-bot-ext-123",
            "status": "done",
            "recording_url": stale_url,
            "recording_url_expires_at": past_expires,
        }])
    )
    # Cache write-back PATCH on recall_bots — mock it; if it isn't called the
    # endpoint still succeeds (write failures are non-fatal by design).
    respx_mock.patch(rest_url("recall_bots")).mock(
        return_value=httpx.Response(200, json=[{}])
    )
    _patch_recall_service(monkeypatch, return_value={
        "video_url": fresh_url,
        "video_duration": 1800,
        "transcript_url": None,
        "participants": [],
        "participants_download_url": None,
        "speaker_timeline_url": None,
    })

    resp = recruiter_client.get(
        f"{V2_ROOT}/candidate-rounds/{CANDIDATE_ROUND_ID}/recording-url"
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["url"] == fresh_url
    # New expires_at must be at least the cache TTL ahead.
    parsed = _dt.fromisoformat(body["expires_at"])
    assert parsed > _dt.now(_tz.utc)


# ============================================
# GET /candidate-rounds/{cr_id}/transcript — PostgREST
# ============================================


def test_get_transcript_404_when_no_row(recruiter_client, respx_mock):
    # candidate_round lookup succeeds and belongs to the user's org.
    respx_mock.get(rest_url("candidate_rounds")).mock(
        return_value=httpx.Response(200, json=[{
            "id": CANDIDATE_ROUND_ID,
            "candidates": {
                "requisition_id": REQ_ID,
                "requisitions": {"organization_id": ORG_ID},
            },
        }])
    )
    # transcripts row doesn't exist.
    respx_mock.get(rest_url("transcripts")).mock(
        return_value=httpx.Response(200, json=[])
    )
    resp = recruiter_client.get(
        f"{V2_ROOT}/candidate-rounds/{CANDIDATE_ROUND_ID}/transcript"
    )
    assert resp.status_code == 404


def test_get_transcript_200_when_row_exists(recruiter_client, respx_mock):
    respx_mock.get(rest_url("candidate_rounds")).mock(
        return_value=httpx.Response(200, json=[{
            "id": CANDIDATE_ROUND_ID,
            "candidates": {
                "requisition_id": REQ_ID,
                "requisitions": {"organization_id": ORG_ID},
            },
        }])
    )
    segments = [
        {"speaker": "Alice", "text": "Hello", "ts_start": 0.0, "ts_end": 1.0},
        {"speaker": "Bob", "text": "Hi", "ts_start": 1.0, "ts_end": 2.0},
    ]
    respx_mock.get(rest_url("transcripts")).mock(
        return_value=httpx.Response(200, json=[{
            "segments": segments,
            "duration_seconds": 2,
            "word_count": 2,
        }])
    )
    # Service additionally reads recall_bots for feedback_start_seconds.
    # Empty result → segment toggle hidden in the FE (feedback_start_seconds
    # remains None).
    respx_mock.get(rest_url("recall_bots")).mock(
        return_value=httpx.Response(200, json=[])
    )
    resp = recruiter_client.get(
        f"{V2_ROOT}/candidate-rounds/{CANDIDATE_ROUND_ID}/transcript"
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["segments"] == segments
    assert body["duration_seconds"] == 2
    assert body["word_count"] == 2
    assert body["feedback_start_seconds"] is None


def test_get_transcript_404_when_cr_belongs_to_other_org(recruiter_client, respx_mock):
    """A CR in a different org must not leak — must 404, not 200/403."""
    other_org_id = "00000000-0000-0000-0000-000000000099"
    respx_mock.get(rest_url("candidate_rounds")).mock(
        return_value=httpx.Response(200, json=[{
            "id": CANDIDATE_ROUND_ID,
            "candidates": {
                "requisition_id": REQ_ID,
                "requisitions": {"organization_id": other_org_id},
            },
        }])
    )
    resp = recruiter_client.get(
        f"{V2_ROOT}/candidate-rounds/{CANDIDATE_ROUND_ID}/transcript"
    )
    assert resp.status_code == 404


def test_get_transcript_403_when_no_org(respx_mock):
    with _no_org_client() as client:
        resp = client.get(
            f"{V2_ROOT}/candidate-rounds/{CANDIDATE_ROUND_ID}/transcript"
        )
    assert resp.status_code == 403


def test_get_role_header_surfaces_ats_provenance(recruiter_client, respx_mock):
    """ATS-imported requisitions expose source='ats_sync' + the provider."""
    row = _make_role_header_row()
    row["source"] = "ats_sync"
    row["ats_provider"] = "workable"
    respx_mock.get(rest_url("requisitions")).mock(
        return_value=httpx.Response(200, json=[row])
    )
    respx_mock.get(rest_url("rounds")).mock(
        return_value=httpx.Response(200, json=[])
    )
    respx_mock.get(rest_url("candidates")).mock(
        return_value=httpx.Response(200, json=[])
    )
    respx_mock.get(rest_url("profiles")).mock(
        return_value=httpx.Response(200, json=[{"full_name": "Jane Recruiter"}])
    )
    resp = recruiter_client.get(f"{V2_ROOT}/roles/{REQ_ID}")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["source"] == "ats_sync"
    assert data["ats_provider"] == "workable"


def test_pending_tab_is_plain_intake_pending(recruiter_client, respx_mock):
    """ATS imports land directly at intake_pending (migration 127), so the
    Pending tab is a bare status filter. Drafts (intake Hub working copies)
    never surface in the list nor count toward any tab badge."""
    captured_params = []

    def _requisitions(request):
        params = dict(request.url.params)
        captured_params.append(params)
        if "status" not in params:
            # Org-wide status_counts query.
            return httpx.Response(200, json=[
                {"status": "draft"},
                {"status": "intake_pending"},
                {"status": "intake_pending"},
                {"status": "planned"},
            ])
        row = _make_role_header_row()
        row["status"] = "intake_pending"
        row["source"] = "ats_sync"
        row["ats_provider"] = "workable"
        return httpx.Response(
            200, headers={"content-range": "0-0/1"}, json=[row]
        )

    respx_mock.get(rest_url("requisitions")).mock(side_effect=_requisitions)
    respx_mock.get(rest_url("rounds")).mock(
        return_value=httpx.Response(200, json=[])
    )
    respx_mock.get(rest_url("candidates")).mock(
        return_value=httpx.Response(200, json=[])
    )

    resp = recruiter_client.get(f"{V2_ROOT}/roles?status=intake_pending")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # Both intake_pending rows count; the draft is invisible everywhere.
    assert body["status_counts"]["pending"] == 2
    assert body["items"][0]["status"] == "intake_pending"
    assert body["items"][0]["ats_provider"] == "workable"
    # The list/count queries used a bare status eq, not an or-group bucket.
    status_queries = [p for p in captured_params if "status" in p]
    assert status_queries
    for p in status_queries:
        assert p["status"] == "eq.intake_pending"
