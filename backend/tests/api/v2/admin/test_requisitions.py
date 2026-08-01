"""BE-T1: admin requisitions router coverage.

These endpoints delegate to `requisition_service` (owned by another lane), so
we mock that service's underlying Supabase calls via respx — exercising the
router's delegation + response shaping. The sample-plan endpoint touches no DB.
"""
import httpx
import pytest

import app.api.v2.routers.admin.requisitions as req_router
from tests.helpers.supabase_mocks import rest_url
from tests.helpers.mock_data import REQ_ID, ROUND_ID, FEEDBACK_QUESTION_ID, make_requisition, make_round, NOW

V2_ROOT = "/api/v2"
ADMIN = f"{V2_ROOT}/admin"


def _round_with_questions():
    r = make_round()
    r["guidelines"] = []
    r["default_interviewer_emails"] = []
    r["feedback_questions"] = []
    return r


def _plan():
    return {
        "requisition_id": REQ_ID,
        "total_rounds": 1,
        "total_duration_minutes": 45,
        "total_duration_display": "45 mins",
        "rounds": [_round_with_questions()],
    }


def _question():
    return {
        "id": FEEDBACK_QUESTION_ID,
        "round_id": ROUND_ID,
        "question_number": 1,
        "heading": "Q",
        "description": None,
        "created_at": NOW,
        "updated_at": NOW,
    }


class _FakeReqService:
    """Stubs every requisition_service method the router calls so we exercise
    the router's delegation + response shaping without touching the DB."""

    async def create_requisition(self, org_id, data, created_by):
        return make_requisition()

    async def list_requisitions(self, org_id, include_deleted=False, page=1, page_size=25):
        return [make_requisition()], 1

    async def get_requisition(self, req_id, org_id=None):
        return make_requisition()

    async def get_requisition_with_plan(self, req_id, org_id=None):
        return {**make_requisition(), "plan": _plan()}

    async def update_requisition(self, req_id, data):
        return make_requisition()

    async def update_intake(self, req_id, data):
        return make_requisition()

    async def update_status(self, req_id, status, allowed_statuses=None):
        return make_requisition(status=status)

    async def create_intake_call_session(self, req_id):
        return {"session_token": "tok", "requisition_id": req_id}

    async def soft_delete_requisition(self, req_id):
        return {"message": "deleted", "id": req_id}

    async def restore_requisition(self, req_id):
        return {"message": "restored", "id": req_id}

    async def create_interview_plan(self, req_id, plan):
        return _plan()

    async def get_interview_plan(self, req_id):
        return _plan()

    async def update_interview_plan(self, req_id, plan):
        return _plan()

    async def delete_interview_plan(self, req_id):
        return {"message": "plan deleted"}

    async def add_round(self, req_id, data):
        return _round_with_questions()

    async def update_round(self, round_id, data):
        return make_round()

    async def delete_round(self, round_id):
        return {"message": "round deleted", "id": round_id}

    async def restore_round(self, round_id):
        return {"message": "round restored", "id": round_id}

    async def reorder_rounds(self, req_id, data):
        return {"message": "reordered"}

    async def add_question(self, round_id, data):
        return _question()

    async def update_question(self, question_id, data):
        return _question()

    async def delete_question(self, question_id):
        return {"message": "question deleted", "id": question_id}

    async def restore_question(self, question_id):
        return {"message": "question restored", "id": question_id}


@pytest.fixture
def fake_req_service(monkeypatch):
    svc = _FakeReqService()
    monkeypatch.setattr(req_router, "get_requisition_service", lambda: svc)
    return svc


def test_sample_plan(staff_client, respx_mock):
    resp = staff_client.get(f"{ADMIN}/requisitions/sample-plan")
    assert resp.status_code == 200, resp.text
    assert "sample" in resp.json()


def test_get_requisition_404(staff_client, respx_mock):
    respx_mock.get(rest_url("requisitions")).mock(
        return_value=httpx.Response(200, json=[])
    )
    resp = staff_client.get(f"{ADMIN}/requisitions/{REQ_ID}")
    assert resp.status_code == 404, resp.text


def test_get_requisition_success(staff_client, respx_mock):
    def _reqs(request):
        return httpx.Response(200, json=[make_requisition()])

    respx_mock.get(rest_url("requisitions")).mock(side_effect=_reqs)
    # _attach_org_untracked_flag may read organizations; mock defensively.
    respx_mock.get(rest_url("organizations")).mock(
        return_value=httpx.Response(200, json=[{"id": "x", "auto_join_untracked": False}])
    )
    resp = staff_client.get(f"{ADMIN}/requisitions/{REQ_ID}")
    assert resp.status_code == 200, resp.text
    assert resp.json()["id"] == REQ_ID


def test_delete_requisition_404(staff_client, respx_mock):
    respx_mock.get(rest_url("requisitions")).mock(
        return_value=httpx.Response(200, json=[])
    )
    resp = staff_client.delete(f"{ADMIN}/requisitions/{REQ_ID}")
    assert resp.status_code == 404, resp.text


def test_delete_requisition_already_deleted(staff_client, respx_mock):
    respx_mock.get(rest_url("requisitions")).mock(
        return_value=httpx.Response(
            200, json=[{"id": REQ_ID, "deleted_at": NOW}]
        )
    )
    resp = staff_client.delete(f"{ADMIN}/requisitions/{REQ_ID}")
    assert resp.status_code == 400, resp.text


def test_restore_requisition_not_deleted(staff_client, respx_mock):
    respx_mock.get(rest_url("requisitions")).mock(
        return_value=httpx.Response(
            200, json=[{"id": REQ_ID, "deleted_at": None}]
        )
    )
    resp = staff_client.post(f"{ADMIN}/requisitions/{REQ_ID}/restore")
    assert resp.status_code == 400, resp.text


# ── service-delegated happy paths (fake service) ─────────────────────────────

def test_create_requisition(staff_client, fake_req_service):
    resp = staff_client.post(
        f"{ADMIN}/requisitions/organizations/00000000-0000-0000-0000-000000000010",
        json={"role_title": "SWE", "role_location": "Remote"},
    )
    assert resp.status_code == 201, resp.text


def test_list_requisitions(staff_client, fake_req_service):
    resp = staff_client.get(
        f"{ADMIN}/requisitions/organizations/00000000-0000-0000-0000-000000000010"
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["total"] == 1


def test_list_deleted_requisitions(staff_client, fake_req_service):
    resp = staff_client.get(
        f"{ADMIN}/requisitions/organizations/00000000-0000-0000-0000-000000000010/deleted"
    )
    assert resp.status_code == 200, resp.text


def test_get_requisition_with_plan(staff_client, fake_req_service):
    resp = staff_client.get(f"{ADMIN}/requisitions/{REQ_ID}/with-plan")
    assert resp.status_code == 200, resp.text
    assert resp.json()["plan"]["total_rounds"] == 1


def test_update_requisition(staff_client, fake_req_service):
    resp = staff_client.put(
        f"{ADMIN}/requisitions/{REQ_ID}", json={"role_title": "Senior SWE"}
    )
    assert resp.status_code == 200, resp.text


def test_update_intake(staff_client, fake_req_service):
    resp = staff_client.put(
        f"{ADMIN}/requisitions/{REQ_ID}/intake",
        json={"intake_notes": "notes"},
    )
    assert resp.status_code == 200, resp.text


def test_update_requisition_status(staff_client, fake_req_service):
    resp = staff_client.put(
        f"{ADMIN}/requisitions/{REQ_ID}/status", json={"status": "planned"}
    )
    assert resp.status_code == 200, resp.text


def test_create_intake_call_session(staff_client, fake_req_service):
    resp = staff_client.post(f"{ADMIN}/requisitions/{REQ_ID}/intake-call")
    assert resp.status_code == 200, resp.text
    assert resp.json()["session_token"] == "tok"


def test_delete_and_restore_requisition(staff_client, fake_req_service):
    d = staff_client.delete(f"{ADMIN}/requisitions/{REQ_ID}")
    assert d.status_code == 200, d.text
    r = staff_client.post(f"{ADMIN}/requisitions/{REQ_ID}/restore")
    assert r.status_code == 200, r.text


def test_plan_ops(staff_client, fake_req_service):
    c = staff_client.post(
        f"{ADMIN}/requisitions/{REQ_ID}/plan",
        json={"rounds": [{"name": "Tech"}]},
    )
    assert c.status_code == 201, c.text
    g = staff_client.get(f"{ADMIN}/requisitions/{REQ_ID}/plan")
    assert g.status_code == 200, g.text
    u = staff_client.put(
        f"{ADMIN}/requisitions/{REQ_ID}/plan",
        json={"rounds": [{"name": "Tech"}]},
    )
    assert u.status_code == 200, u.text
    d = staff_client.delete(f"{ADMIN}/requisitions/{REQ_ID}/plan")
    assert d.status_code == 200, d.text


def test_round_ops(staff_client, fake_req_service):
    a = staff_client.post(
        f"{ADMIN}/requisitions/{REQ_ID}/rounds",
        json={"name": "Tech"},
    )
    assert a.status_code == 201, a.text
    u = staff_client.put(
        f"{ADMIN}/requisitions/rounds/{ROUND_ID}", json={"name": "Tech2"}
    )
    assert u.status_code == 200, u.text
    d = staff_client.delete(f"{ADMIN}/requisitions/rounds/{ROUND_ID}")
    assert d.status_code == 200, d.text
    r = staff_client.post(f"{ADMIN}/requisitions/rounds/{ROUND_ID}/restore")
    assert r.status_code == 200, r.text
    ro = staff_client.put(
        f"{ADMIN}/requisitions/{REQ_ID}/rounds/reorder",
        json={"round_orders": [{"round_id": ROUND_ID, "round_number": 1}]},
    )
    assert ro.status_code == 200, ro.text


def test_question_ops(staff_client, fake_req_service):
    a = staff_client.post(
        f"{ADMIN}/requisitions/rounds/{ROUND_ID}/questions",
        json={"heading": "Q"},
    )
    assert a.status_code == 201, a.text
    u = staff_client.put(
        f"{ADMIN}/requisitions/questions/{FEEDBACK_QUESTION_ID}",
        json={"heading": "Q2"},
    )
    assert u.status_code == 200, u.text
    d = staff_client.delete(
        f"{ADMIN}/requisitions/questions/{FEEDBACK_QUESTION_ID}"
    )
    assert d.status_code == 200, d.text
    r = staff_client.post(
        f"{ADMIN}/requisitions/questions/{FEEDBACK_QUESTION_ID}/restore"
    )
    assert r.status_code == 200, r.text
