"""Connect-time import: page jobs, skip CLOSED, RPC per job, tally, kick sync."""

import pytest

from app.api.v2.services import ats_import_service as svc
from app.integrations.ats.core.errors import AtsNotConnectedError
from app.services.supabase import get_supabase_admin_client
from tests.helpers.mock_data import ORG_ID, RECRUITER_USER_ID
from tests.helpers.supabase_mocks import mock_rpc, mock_select

KNIT = "https://api.getknit.dev/v1.0"

CONN_ROW = {
    "id": "33333333-3333-4333-8333-333333333333",
    "provider": "workable",
    "knit_integration_id": "int-1",
    "status": "active",
}


def knit_job(job_id, title, status):
    return {"info": {"id": job_id, "title": title, "status": status}}


@pytest.fixture
def connection_rows(respx_mock):
    mock_select(respx_mock, "ats_connections", [CONN_ROW])


async def test_import_tallies_created_and_skipped(respx_mock, connection_rows):
    respx_mock.get(f"{KNIT}/ats.job.list").respond(
        200,
        json={
            "success": True,
            "data": {
                "jobs": [
                    knit_job("j1", "Open role", "OPEN"),
                    knit_job("j2", "Closed role", "CLOSED"),
                ]
            },
        },
    )
    rpc_route = mock_rpc(
        respx_mock, "ats_import_job", {"action": "created", "requisition_id": "r1"}
    )
    sync_route = respx_mock.post(f"{KNIT}/sync.start").respond(
        200, json={"success": True, "data": {"syncJobId": "sj", "syncRunId": "sr"}}
    )
    summary = await svc.run_import(
        get_supabase_admin_client(), org_id=ORG_ID, user_id=RECRUITER_USER_ID
    )
    assert summary.created == 1 and summary.skipped_closed == 1
    assert summary.updated == 0 and summary.flagged == 0 and summary.errors == 0
    assert summary.sync_started is True
    assert rpc_route.call_count == 1
    assert sync_route.call_count == 2  # ats_jobs + ats_applications


async def test_import_include_closed(respx_mock, connection_rows):
    respx_mock.get(f"{KNIT}/ats.job.list").respond(
        200,
        json={
            "success": True,
            "data": {"jobs": [knit_job("j2", "Closed role", "CLOSED")]},
        },
    )
    mock_rpc(
        respx_mock, "ats_import_job", {"action": "created", "requisition_id": "r2"}
    )
    respx_mock.post(f"{KNIT}/sync.start").respond(
        200, json={"success": True, "data": {"syncJobId": "sj", "syncRunId": "sr"}}
    )
    summary = await svc.run_import(
        get_supabase_admin_client(),
        org_id=ORG_ID,
        user_id=RECRUITER_USER_ID,
        include_closed=True,
    )
    assert summary.created == 1 and summary.skipped_closed == 0


async def test_import_survives_sync_start_failure(respx_mock, connection_rows):
    respx_mock.get(f"{KNIT}/ats.job.list").respond(
        200,
        json={"success": True, "data": {"jobs": [knit_job("j1", "Open role", "OPEN")]}},
    )
    mock_rpc(
        respx_mock, "ats_import_job", {"action": "created", "requisition_id": "r1"}
    )
    respx_mock.post(f"{KNIT}/sync.start").respond(
        400, json={"success": False, "error": {"msg": "sync not enabled"}}
    )
    summary = await svc.run_import(
        get_supabase_admin_client(), org_id=ORG_ID, user_id=RECRUITER_USER_ID
    )
    assert summary.created == 1 and summary.sync_started is False


async def test_import_tallies_rpc_failures_as_errors(respx_mock, connection_rows):
    respx_mock.get(f"{KNIT}/ats.job.list").respond(
        200,
        json={
            "success": True,
            "data": {
                "jobs": [knit_job("j1", "A", "OPEN"), knit_job("j2", "B", "OPEN")]
            },
        },
    )
    import httpx

    # First RPC call fails (500), second succeeds.
    from tests.helpers.supabase_mocks import rpc_url

    route = respx_mock.post(rpc_url("ats_import_job"))
    route.side_effect = [
        httpx.Response(500, json={"message": "boom", "code": "XX000"}),
        httpx.Response(200, json={"action": "created", "requisition_id": "r2"}),
    ]
    respx_mock.post(f"{KNIT}/sync.start").respond(
        200, json={"success": True, "data": {"syncJobId": "sj", "syncRunId": "sr"}}
    )
    summary = await svc.run_import(
        get_supabase_admin_client(), org_id=ORG_ID, user_id=RECRUITER_USER_ID
    )
    assert summary.errors == 1 and summary.created == 1


async def test_import_without_connection_raises(respx_mock):
    mock_select(respx_mock, "ats_connections", [])
    with pytest.raises(AtsNotConnectedError):
        await svc.run_import(
            get_supabase_admin_client(), org_id=ORG_ID, user_id=RECRUITER_USER_ID
        )
