"""BE-T1: admin feedback-jobs and intake-jobs router coverage.

Both routers delegate to job services (boto3 Lambda + Supabase) owned by
another lane. We monkeypatch the service factories that the routers import to
isolate the router's own logic (status mapping, 404s, error-code -> HTTP),
and mock the small DB reads they do directly via respx.
"""
import httpx
import pytest

import app.api.v2.routers.admin.feedback_jobs as fj_router
import app.api.v2.routers.admin.intake_jobs as ij_router
from app.services.feedback_job_service import FeedbackJobServiceError
from app.services.intake_job_service import IntakeJobServiceError
from tests.helpers.supabase_mocks import rest_url
from tests.helpers.mock_data import CANDIDATE_ROUND_ID, REQ_ID

V2_ROOT = "/api/v2"
ADMIN = f"{V2_ROOT}/admin"


class _FakeFeedbackService:
    def __init__(self, *, trigger=None, status_result=None, prereq=None, raises=None):
        self._trigger = trigger
        self._status = status_result
        self._prereq = prereq
        self._raises = raises

    async def trigger_feedback_processing(self, cr_id, skip_prereq_check=False):
        if self._raises:
            raise self._raises
        return self._trigger

    async def get_processing_status(self, cr_id):
        return self._status

    async def can_process_feedback(self, cr_id):
        return self._prereq


class _FakeIntakeService:
    def __init__(self, *, trigger=None, status_result=None, raises=None):
        self._trigger = trigger
        self._status = status_result
        self._raises = raises

    async def trigger_intake_processing(self, req_id):
        if self._raises:
            raise self._raises
        return self._trigger

    async def get_processing_status(self, req_id):
        return self._status


# ── feedback jobs ────────────────────────────────────────────────────────────

def test_create_feedback_job_success(staff_client, respx_mock, monkeypatch):
    monkeypatch.setattr(
        fj_router, "get_feedback_job_service",
        lambda: _FakeFeedbackService(trigger={"status": "submitted"}),
    )
    resp = staff_client.post(
        f"{ADMIN}/feedback-jobs",
        json={"candidate_round_id": CANDIDATE_ROUND_ID},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "submitted"


def test_create_feedback_job_resource_not_found_503(staff_client, respx_mock, monkeypatch):
    err = FeedbackJobServiceError("missing", error_code="ResourceNotFoundException")
    monkeypatch.setattr(
        fj_router, "get_feedback_job_service",
        lambda: _FakeFeedbackService(raises=err),
    )
    resp = staff_client.post(
        f"{ADMIN}/feedback-jobs",
        json={"candidate_round_id": CANDIDATE_ROUND_ID},
    )
    assert resp.status_code == 503, resp.text


def test_get_feedback_status_404(staff_client, respx_mock, monkeypatch):
    monkeypatch.setattr(
        fj_router, "get_feedback_job_service",
        lambda: _FakeFeedbackService(status_result={"found": False, "candidate_round_id": CANDIDATE_ROUND_ID}),
    )
    resp = staff_client.get(f"{ADMIN}/feedback-jobs/{CANDIDATE_ROUND_ID}/status")
    assert resp.status_code == 404, resp.text


def test_get_feedback_status_found(staff_client, respx_mock, monkeypatch):
    monkeypatch.setattr(
        fj_router, "get_feedback_job_service",
        lambda: _FakeFeedbackService(
            status_result={
                "found": True,
                "candidate_round_id": CANDIDATE_ROUND_ID,
                "processing_status": "completed",
            }
        ),
    )
    resp = staff_client.get(f"{ADMIN}/feedback-jobs/{CANDIDATE_ROUND_ID}/status")
    assert resp.status_code == 200, resp.text
    assert resp.json()["processing_status"] == "completed"


def test_check_feedback_prereqs(staff_client, respx_mock, monkeypatch):
    monkeypatch.setattr(
        fj_router, "get_feedback_job_service",
        lambda: _FakeFeedbackService(prereq=(True, "ready")),
    )
    resp = staff_client.get(f"{ADMIN}/feedback-jobs/{CANDIDATE_ROUND_ID}/prereq-check")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["can_process"] is True
    assert body["reason"] == "ready"


# ── intake jobs ──────────────────────────────────────────────────────────────

def test_create_intake_job_req_not_found_404(staff_client, respx_mock, monkeypatch):
    respx_mock.get(rest_url("requisitions")).mock(
        return_value=httpx.Response(200, json=[])
    )
    monkeypatch.setattr(
        ij_router, "get_intake_job_service",
        lambda: _FakeIntakeService(trigger={"status": "submitted"}),
    )
    resp = staff_client.post(
        f"{ADMIN}/intake-jobs",
        json={"requisition_id": REQ_ID, "intake_transcript": "a long enough transcript"},
    )
    assert resp.status_code == 404, resp.text


def test_create_intake_job_rejected(staff_client, respx_mock, monkeypatch):
    respx_mock.get(rest_url("requisitions")).mock(
        return_value=httpx.Response(200, json=[{"id": REQ_ID}])
    )
    respx_mock.patch(rest_url("requisitions")).mock(
        return_value=httpx.Response(200, json=[])
    )
    monkeypatch.setattr(
        ij_router, "get_intake_job_service",
        lambda: _FakeIntakeService(trigger={"status": "rejected", "reason": "too short"}),
    )
    resp = staff_client.post(
        f"{ADMIN}/intake-jobs",
        json={"requisition_id": REQ_ID, "intake_transcript": "a long enough transcript"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "rejected"


def test_create_intake_job_service_unavailable_503(staff_client, respx_mock, monkeypatch):
    respx_mock.get(rest_url("requisitions")).mock(
        return_value=httpx.Response(200, json=[{"id": REQ_ID}])
    )
    respx_mock.patch(rest_url("requisitions")).mock(
        return_value=httpx.Response(200, json=[])
    )
    err = IntakeJobServiceError("missing", error_code="ResourceNotFoundException")
    monkeypatch.setattr(
        ij_router, "get_intake_job_service",
        lambda: _FakeIntakeService(raises=err),
    )
    resp = staff_client.post(
        f"{ADMIN}/intake-jobs",
        json={"requisition_id": REQ_ID, "intake_transcript": "a long enough transcript"},
    )
    assert resp.status_code == 503, resp.text


def test_get_intake_status_404(staff_client, respx_mock, monkeypatch):
    monkeypatch.setattr(
        ij_router, "get_intake_job_service",
        lambda: _FakeIntakeService(status_result={"found": False, "requisition_id": REQ_ID}),
    )
    resp = staff_client.get(f"{ADMIN}/intake-jobs/{REQ_ID}/status")
    assert resp.status_code == 404, resp.text


def test_get_intake_status_found(staff_client, respx_mock, monkeypatch):
    monkeypatch.setattr(
        ij_router, "get_intake_job_service",
        lambda: _FakeIntakeService(
            status_result={
                "found": True,
                "requisition_id": REQ_ID,
                "intake_processing_status": "completed",
            }
        ),
    )
    resp = staff_client.get(f"{ADMIN}/intake-jobs/{REQ_ID}/status")
    assert resp.status_code == 200, resp.text
    assert resp.json()["intake_processing_status"] == "completed"
