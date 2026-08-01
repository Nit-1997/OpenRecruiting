"""Phase-2 functional tests: import-on-connect, /import, /sync-status,
per-requisition sync routes, and the webhook→ledger→drainer pipeline."""

import json

from tests.helpers.mock_data import ORG_ID, RECRUITER_USER_ID
from tests.helpers.supabase_mocks import mock_rpc, mock_select, mock_update, rest_url

KNIT = "https://api.getknit.dev/v1.0"
BASE = "/api/v2/integrations/ats"

ACTIVE_ROW = {
    "id": "33333333-3333-4333-8333-333333333333",
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


def mock_jobs(respx_mock, jobs):
    return respx_mock.get(f"{KNIT}/ats.job.list").respond(
        200, json={"success": True, "data": {"jobs": jobs}}
    )


def mock_sync_start(respx_mock):
    return respx_mock.post(f"{KNIT}/sync.start").respond(
        200, json={"success": True, "data": {"syncJobId": "sj", "syncRunId": "sr"}}
    )


# ----------------------- connect now imports -----------------------


def test_complete_connection_returns_import_summary(recruiter_client, respx_mock):
    respx_mock.get(f"{KNIT}/integration.details").respond(200, json=APPS_OK)
    mock_rpc(respx_mock, "ats_connect", "conn-1")
    mock_select(respx_mock, "ats_connections", [ACTIVE_ROW])
    mock_select(respx_mock, "profiles", [{"full_name": "Rae"}])
    mock_jobs(respx_mock, [{"info": {"id": "j1", "title": "SWE", "status": "OPEN"}}])
    mock_rpc(
        respx_mock, "ats_import_job", {"action": "created", "requisition_id": "r1"}
    )
    mock_sync_start(respx_mock)
    resp = recruiter_client.post(
        f"{BASE}/connections",
        json={"integrationId": "int-1", "originOrgId": ORG_ID, "success": True},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["connected"] is True
    assert body["import_summary"]["created"] == 1
    assert body["import_summary"]["sync_started"] is True


def test_complete_connection_survives_import_failure(recruiter_client, respx_mock):
    respx_mock.get(f"{KNIT}/integration.details").respond(200, json=APPS_OK)
    mock_rpc(respx_mock, "ats_connect", "conn-1")
    mock_select(respx_mock, "ats_connections", [ACTIVE_ROW])
    mock_select(respx_mock, "profiles", [{"full_name": "Rae"}])
    respx_mock.get(f"{KNIT}/ats.job.list").respond(
        400, json={"success": False, "error": {"msg": "boom"}}
    )
    resp = recruiter_client.post(
        f"{BASE}/connections",
        json={"integrationId": "int-1", "originOrgId": ORG_ID, "success": True},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["connected"] is True
    assert body["import_summary"] is None


# ----------------------- POST /import -----------------------


def test_import_endpoint(recruiter_client, respx_mock):
    mock_select(respx_mock, "ats_connections", [ACTIVE_ROW])
    mock_jobs(
        respx_mock,
        [
            {"info": {"id": "j1", "title": "SWE", "status": "OPEN"}},
            {"info": {"id": "j2", "title": "Old", "status": "CLOSED"}},
        ],
    )
    mock_rpc(
        respx_mock, "ats_import_job", {"action": "created", "requisition_id": "r1"}
    )
    mock_sync_start(respx_mock)
    resp = recruiter_client.post(f"{BASE}/import")
    assert resp.status_code == 200
    body = resp.json()
    assert body["created"] == 1 and body["skipped_closed"] == 1


def test_import_endpoint_include_closed(recruiter_client, respx_mock):
    mock_select(respx_mock, "ats_connections", [ACTIVE_ROW])
    mock_jobs(respx_mock, [{"info": {"id": "j2", "title": "Old", "status": "CLOSED"}}])
    mock_rpc(
        respx_mock, "ats_import_job", {"action": "created", "requisition_id": "r2"}
    )
    mock_sync_start(respx_mock)
    resp = recruiter_client.post(f"{BASE}/import", params={"include_closed": "true"})
    assert resp.status_code == 200
    assert resp.json()["created"] == 1


# ----------------------- GET /sync-status -----------------------


# ----------------------- per-requisition sync -----------------------

REQ_ID = "44444444-4444-4444-8444-444444444444"

LINK_ROW = {
    "provider": "workable",
    "ats_status": "OPEN",
    "ats_dirty": True,
    "ats_deleted": False,
    "ats_dirty_payload": {"role_title": "SWE II", "ats_job_id": "j1"},
}


def test_requisition_sync_linked(recruiter_client, respx_mock):
    mock_select(respx_mock, "ats_entity_links", [LINK_ROW])
    resp = recruiter_client.get(f"{BASE}/requisitions/{REQ_ID}/sync")
    assert resp.status_code == 200
    body = resp.json()
    assert body["linked"] is True and body["provider"] == "workable"
    assert body["ats_dirty"] is True
    assert body["pending_changes"] == {"role_title": "SWE II"}


def test_requisition_sync_unlinked(recruiter_client, respx_mock):
    mock_select(respx_mock, "ats_entity_links", [])
    resp = recruiter_client.get(f"{BASE}/requisitions/{REQ_ID}/sync")
    assert resp.status_code == 200
    assert resp.json() == {
        "linked": False,
        "provider": None,
        "ats_status": None,
        "ats_dirty": False,
        "ats_deleted": False,
        "pending_changes": None,
    }


def test_apply_update(recruiter_client, respx_mock):
    rpc = mock_rpc(
        respx_mock, "ats_apply_dirty_update", {"action": "applied", "id": REQ_ID}
    )
    resp = recruiter_client.post(f"{BASE}/requisitions/{REQ_ID}/apply-update")
    assert resp.status_code == 200
    assert resp.json() == {"applied": True}
    assert rpc.call_count == 1


def test_apply_update_noop(recruiter_client, respx_mock):
    mock_rpc(respx_mock, "ats_apply_dirty_update", {"action": "noop"})
    resp = recruiter_client.post(f"{BASE}/requisitions/{REQ_ID}/apply-update")
    assert resp.status_code == 200
    assert resp.json() == {"applied": False}


def test_dismiss_update(recruiter_client, respx_mock):
    update_route = mock_update(respx_mock, "ats_entity_links")
    resp = recruiter_client.post(f"{BASE}/requisitions/{REQ_ID}/dismiss-update")
    assert resp.status_code == 200
    assert resp.json() == {"dismissed": True}
    sent = json.loads(update_route.calls[0].request.content)
    assert sent["ats_dirty"] is False


# ----------------------- webhook → ledger → drainer pipeline -----------------------


def test_signed_event_through_ledger_and_drainer(unauthed_client, respx_mock):
    """A signed initial_sync-shaped event lands in the ledger via the real
    webhook route; one drain pass applies it through adapters → RPC."""
    import asyncio
    import base64
    import hashlib
    import hmac as hmac_lib

    captured_rows = []

    def capture_insert(request):
        import httpx

        captured_rows.append(json.loads(request.content))
        return httpx.Response(201, json=[{"event_id": "evt-pipe-1"}])

    respx_mock.post(rest_url("ats_webhook_events")).mock(side_effect=capture_insert)
    mock_update(respx_mock, "ats_webhook_events")

    envelope = {
        "eventId": "evt-pipe-1",
        "eventType": "record.new",
        "syncDataType": "ats_jobs",
        "eventData": {"info": {"id": "j9", "title": "Pipeline Role", "status": "OPEN"}},
        "syncType": "initial_sync",
        "syncJobId": "sj",
        "syncRunId": "sr",
        "triggeredAt": "1765500000000",
        "recordId": "j9",
    }
    raw = json.dumps(envelope).encode()
    digest = hmac_lib.new(b"test-knit-key", raw, hashlib.sha256).digest()
    signature = base64.urlsafe_b64encode(digest).decode().rstrip("=")

    resp = unauthed_client.post(
        "/api/v2/webhooks/knit",
        content=raw,
        headers={
            "Content-Type": "application/json",
            "X-Knit-Signature": signature,
            "X-Knit-Integration-Id": "int-1",
        },
    )
    assert resp.status_code == 200
    assert captured_rows[0]["integration_id"] == "int-1"

    # Drain the captured ledger row through the real handler chain.
    from app.services.ats_sync.drainer import drain_once
    from app.services.supabase import get_supabase_admin_client

    ledger_row = {
        "event_id": captured_rows[0]["event_id"],
        "event_type": captured_rows[0]["event_type"],
        "integration_id": captured_rows[0]["integration_id"],
        "payload": captured_rows[0]["payload"],
        "retry_count": 0,
    }
    respx_mock.get(rest_url("ats_webhook_events")).respond(200, json=[ledger_row])
    mock_select(
        respx_mock,
        "ats_connections",
        [
            {
                "id": "33333333-3333-4333-8333-333333333333",
                "organization_id": ORG_ID,
                "provider": "workable",
                "status": "active",
            }
        ],
    )
    import_rpc = mock_rpc(
        respx_mock, "ats_import_job", {"action": "created", "requisition_id": "r9"}
    )

    handled = asyncio.get_event_loop().run_until_complete(
        drain_once(get_supabase_admin_client())
    )
    assert handled == 1
    assert import_rpc.call_count == 1
    sent = json.loads(import_rpc.calls[0].request.content)
    assert sent["p_ats_job_id"] == "j9"
    assert sent["p_fields"]["role_title"] == "Pipeline Role"


def test_sync_status(recruiter_client, respx_mock):
    # count_async issues GET with Prefer: count=exact; respond with Content-Range.
    respx_mock.get(rest_url("ats_webhook_events")).mock(
        side_effect=[
            __import__("httpx").Response(
                200, json=[], headers={"Content-Range": "0-0/3"}
            ),
            __import__("httpx").Response(
                200, json=[], headers={"Content-Range": "0-0/1"}
            ),
            __import__("httpx").Response(
                200, json=[{"received_at": "2026-06-12T01:00:00+00:00"}]
            ),
        ]
    )
    resp = recruiter_client.get(f"{BASE}/sync-status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["pending_events"] == 3
    assert body["failed_events"] == 1
    assert body["last_event_at"] == "2026-06-12T01:00:00+00:00"
