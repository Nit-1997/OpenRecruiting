"""Functional tests for /api/v2/integrations/ats/* — feature gate, connect
flow (session/connections/status/disconnect), and read-only browse, with
supabase + Knit both respx-mocked."""

from tests.helpers.mock_data import ORG_ID, RECRUITER_USER_ID
from tests.helpers.supabase_mocks import mock_rpc, mock_select, mock_update

KNIT = "https://api.getknit.dev/v1.0"
BASE = "/api/v2/integrations/ats"

ACTIVE_ROW = {
    "id": "conn-1",
    "provider": "workable",
    "status": "active",
    "connected_at": "2026-06-11T00:00:00+00:00",
    "connected_by": RECRUITER_USER_ID,
    "knit_integration_id": "int-1",
}

APPS_OK = {
    "success": True,
    "data": {
        "apps": [
            {
                "id": "workable",
                "category": "ATS",
                "integrationId": "int-1",
                "isActive": True,
            }
        ]
    },
}

KNIT_JOB = {
    "info": {"id": "job-1", "title": "Frontend Engineer", "status": "OPEN"},
    "stages": [{"id": "s1", "text": "Screen"}],
}

KNIT_APPLICATION = {
    "info": {
        "id": "app-1",
        "status": "ACTIVE",
        "candidate": {"id": "cand-1", "firstName": "Emily"},
        "jobId": "job-1",
    },
    "currentStage": {"id": "s1", "text": "Screen"},
}


# ----------------------- feature gate -----------------------


def test_routes_404_when_flag_disabled(recruiter_client, monkeypatch):
    from app.config import get_settings

    monkeypatch.setenv("ATS_INTEGRATIONS_ENABLED", "false")
    get_settings.cache_clear()
    resp = recruiter_client.get(f"{BASE}/status")
    assert resp.status_code == 404


# ----------------------- session -----------------------


def test_session_returns_token(recruiter_client, respx_mock):
    mock_select(respx_mock, "organizations", [{"name": "Acme"}])
    mock_select(respx_mock, "profiles", [{"full_name": "Rae"}])
    respx_mock.post(f"{KNIT}/auth.createSession").respond(
        200, json={"success": True, "msg": {"token": "sess-tok"}}
    )
    resp = recruiter_client.post(f"{BASE}/session")
    assert resp.status_code == 200
    assert resp.json() == {"token": "sess-tok"}


# ----------------------- connections -----------------------


def test_complete_connection_happy_path(recruiter_client, respx_mock):
    respx_mock.get(f"{KNIT}/integration.details").respond(200, json=APPS_OK)
    mock_rpc(respx_mock, "ats_connect", "conn-1")
    mock_select(respx_mock, "ats_connections", [ACTIVE_ROW])
    mock_select(respx_mock, "profiles", [{"full_name": "Rae"}])
    resp = recruiter_client.post(
        f"{BASE}/connections",
        json={
            "integrationId": "int-1",
            "appId": "workable",
            "categoryId": "ATS",
            "originOrgId": ORG_ID,
            "success": True,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["connected"] is True and body["provider"] == "workable"


def test_complete_connection_rejects_forged_integration(recruiter_client, respx_mock):
    respx_mock.get(f"{KNIT}/integration.details").respond(
        200, json={"success": True, "data": {"apps": []}}
    )
    resp = recruiter_client.post(
        f"{BASE}/connections",
        json={"integrationId": "forged", "originOrgId": ORG_ID, "success": True},
    )
    assert resp.status_code == 400


def test_complete_connection_rejects_cross_org(recruiter_client, respx_mock):
    resp = recruiter_client.post(
        f"{BASE}/connections",
        json={"integrationId": "int-1", "originOrgId": "other-org", "success": True},
    )
    assert resp.status_code == 403


def test_complete_connection_rejects_unsuccessful_payload(recruiter_client, respx_mock):
    resp = recruiter_client.post(
        f"{BASE}/connections",
        json={"integrationId": "int-1", "originOrgId": ORG_ID, "success": False},
    )
    assert resp.status_code == 400


# ----------------------- status / disconnect -----------------------


def test_status_not_connected(recruiter_client, respx_mock):
    mock_select(respx_mock, "ats_connections", [])
    resp = recruiter_client.get(f"{BASE}/status")
    assert resp.status_code == 200
    assert resp.json()["connected"] is False


def test_status_connected(recruiter_client, respx_mock):
    mock_select(respx_mock, "ats_connections", [ACTIVE_ROW])
    mock_select(respx_mock, "profiles", [{"full_name": "Rae"}])
    resp = recruiter_client.get(f"{BASE}/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["connected"] is True
    assert body["provider"] == "workable"
    assert body["connected_by_name"] == "Rae"


def test_disconnect(recruiter_client, respx_mock):
    mock_select(respx_mock, "ats_connections", [ACTIVE_ROW])
    respx_mock.post(f"{KNIT}/integration.deactivate").respond(
        200, json={"success": True, "data": None}
    )
    mock_update(respx_mock, "ats_connections")
    resp = recruiter_client.delete(f"{BASE}/connection")
    assert resp.status_code == 200
    assert resp.json() == {"disconnected": True}


def test_disconnect_without_connection_404(recruiter_client, respx_mock):
    mock_select(respx_mock, "ats_connections", [])
    resp = recruiter_client.delete(f"{BASE}/connection")
    assert resp.status_code == 404


# ----------------------- browse: jobs -----------------------


def test_list_jobs_returns_canonical_page(recruiter_client, respx_mock):
    mock_select(respx_mock, "ats_connections", [ACTIVE_ROW])
    respx_mock.get(f"{KNIT}/ats.job.list").respond(
        200,
        json={"success": True, "data": {"jobs": [KNIT_JOB], "nextPageToken": "t2"}},
    )
    resp = recruiter_client.get(f"{BASE}/jobs")
    assert resp.status_code == 200
    body = resp.json()
    assert body["next_page_token"] == "t2"
    assert body["items"][0]["title"] == "Frontend Engineer"
    assert body["items"][0]["stages"][0]["name"] == "Screen"


def test_browse_without_connection_404s(recruiter_client, respx_mock):
    mock_select(respx_mock, "ats_connections", [])
    resp = recruiter_client.get(f"{BASE}/jobs")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "No ATS connected"


def test_get_job_by_id(recruiter_client, respx_mock):
    mock_select(respx_mock, "ats_connections", [ACTIVE_ROW])
    respx_mock.get(f"{KNIT}/ats.job.list").respond(
        200, json={"success": True, "data": {"jobs": [KNIT_JOB]}}
    )
    resp = recruiter_client.get(f"{BASE}/jobs/job-1")
    assert resp.status_code == 200
    assert resp.json()["id"] == "job-1"


def test_get_job_missing_404s(recruiter_client, respx_mock):
    mock_select(respx_mock, "ats_connections", [ACTIVE_ROW])
    respx_mock.get(f"{KNIT}/ats.job.list").respond(
        200, json={"success": True, "data": {"jobs": []}}
    )
    resp = recruiter_client.get(f"{BASE}/jobs/nope")
    assert resp.status_code == 404


# ----------------------- browse: candidates / applications -----------------------


def test_search_candidates_requires_a_param(recruiter_client, respx_mock):
    resp = recruiter_client.get(f"{BASE}/candidates")
    assert resp.status_code == 400


def test_search_candidates(recruiter_client, respx_mock):
    mock_select(respx_mock, "ats_connections", [ACTIVE_ROW])
    respx_mock.post(f"{KNIT}/ats.candidates.search").respond(
        200,
        json={
            "success": True,
            "data": {"candidates": [{"id": "cand-1", "firstName": "Emily"}]},
        },
    )
    resp = recruiter_client.get(f"{BASE}/candidates", params={"first_name": "Emily"})
    assert resp.status_code == 200
    assert resp.json()[0]["first_name"] == "Emily"


def test_list_applications(recruiter_client, respx_mock):
    mock_select(respx_mock, "ats_connections", [ACTIVE_ROW])
    respx_mock.get(f"{KNIT}/ats.application.list").respond(
        200,
        json={
            "success": True,
            "data": {"applications": [KNIT_APPLICATION], "nextPageToken": None},
        },
    )
    resp = recruiter_client.get(f"{BASE}/applications")
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert items[0]["id"] == "app-1"
    assert items[0]["candidate"]["first_name"] == "Emily"


def test_get_application_requires_candidate_id(recruiter_client, respx_mock):
    mock_select(respx_mock, "ats_connections", [ACTIVE_ROW])
    resp = recruiter_client.get(f"{BASE}/applications/app-1")
    assert resp.status_code == 422


def test_get_application(recruiter_client, respx_mock):
    mock_select(respx_mock, "ats_connections", [ACTIVE_ROW])
    respx_mock.get(f"{KNIT}/ats.application.get").respond(
        200, json={"success": True, "data": {"application": KNIT_APPLICATION}}
    )
    resp = recruiter_client.get(
        f"{BASE}/applications/app-1", params={"candidate_id": "cand-1"}
    )
    assert resp.status_code == 200
    assert resp.json()["id"] == "app-1"
