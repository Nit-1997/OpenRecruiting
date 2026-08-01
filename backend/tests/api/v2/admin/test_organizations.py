"""BE-S4: admin organizations router — atomic archive/restore via RPC.

The archive/restore cascade (soft-delete the org's profiles AND the org, or the
inverse) is now a single transactional SECURITY DEFINER RPC
(`admin_archive_organization` / `admin_restore_organization`, migration 105).
The router calls the RPC, then bans/unbans the affected auth users AFTER the DB
transaction commits — safely ordered so a ban failure can never leave users
de-activated under a still-active org.

These tests pin:
  - staff gate (covered broadly in test_staff_gate; one explicit case here)
  - success path drives the RPC and returns the archived/restored envelope
  - partial-failure: when the RPC raises (the transaction rolled back) the
    router maps it to an HTTP error and performs NO ban/profile-cache writes
"""
import httpx

from tests.helpers.supabase_mocks import rest_url, rpc_url, auth_url
from tests.helpers.mock_data import ORG_ID, RECRUITER_USER_ID, make_org

V2_ROOT = "/api/v2"


def _pg_error(code: str, message: str, status_code: int = 400):
    return httpx.Response(
        status_code,
        json={"code": code, "message": message, "details": None, "hint": None},
    )


# ── archive ──────────────────────────────────────────────────────────────────

def test_archive_organization_success_calls_rpc(staff_client, respx_mock):
    captured = {}

    def _archive_rpc(request):
        captured["payload"] = request.content
        return httpx.Response(
            200,
            json={"organization_id": ORG_ID, "user_ids": [RECRUITER_USER_ID]},
        )

    # The pre-read of the org (existence + not-already-archived) still happens
    # in the router before the RPC.
    respx_mock.get(rest_url("organizations")).mock(
        return_value=httpx.Response(200, json=[make_org(deleted_at=None)])
    )
    rpc_route = respx_mock.post(rpc_url("admin_archive_organization")).mock(
        side_effect=_archive_rpc
    )
    ban_route = respx_mock.put(
        url__regex=rf"http://test-supabase.local/auth/v1/admin/users/.*"
    ).mock(return_value=httpx.Response(200, json={}))

    resp = staff_client.delete(f"{V2_ROOT}/admin/organizations/{ORG_ID}")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["organization_id"] == ORG_ID
    assert "archived" in body["message"].lower()
    assert rpc_route.called
    # The affected user must be banned AFTER the RPC commits.
    assert ban_route.called


def test_archive_organization_partial_failure_no_ban(staff_client, respx_mock):
    """RPC raises (tx rolled back) -> HTTP error and NO ban is attempted."""
    respx_mock.get(rest_url("organizations")).mock(
        return_value=httpx.Response(200, json=[make_org(deleted_at=None)])
    )
    respx_mock.post(rpc_url("admin_archive_organization")).mock(
        return_value=_pg_error("P0001", "ALREADY_ARCHIVED", status_code=400)
    )
    ban_route = respx_mock.put(
        url__regex=rf"http://test-supabase.local/auth/v1/admin/users/.*"
    ).mock(return_value=httpx.Response(200, json={}))

    resp = staff_client.delete(f"{V2_ROOT}/admin/organizations/{ORG_ID}")

    assert resp.status_code == 409, resp.text
    # No partial write: the auth-ban side effect must not have fired.
    assert not ban_route.called


def test_archive_organization_404_when_missing(staff_client, respx_mock):
    respx_mock.get(rest_url("organizations")).mock(
        return_value=httpx.Response(200, json=[])
    )
    resp = staff_client.delete(f"{V2_ROOT}/admin/organizations/{ORG_ID}")
    assert resp.status_code == 404, resp.text


# ── restore ──────────────────────────────────────────────────────────────────

def test_restore_organization_success_calls_rpc(staff_client, respx_mock):
    respx_mock.get(rest_url("organizations")).mock(
        return_value=httpx.Response(
            200, json=[make_org(deleted_at="2025-01-01T00:00:00+00:00")]
        )
    )
    rpc_route = respx_mock.post(rpc_url("admin_restore_organization")).mock(
        return_value=httpx.Response(
            200, json={"organization_id": ORG_ID, "user_ids": [RECRUITER_USER_ID]}
        )
    )
    unban_route = respx_mock.put(
        url__regex=rf"http://test-supabase.local/auth/v1/admin/users/.*"
    ).mock(return_value=httpx.Response(200, json={}))

    resp = staff_client.post(f"{V2_ROOT}/admin/organizations/{ORG_ID}/restore")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "restored" in body["message"].lower()
    assert rpc_route.called
    assert unban_route.called


def test_restore_organization_partial_failure_no_unban(staff_client, respx_mock):
    respx_mock.get(rest_url("organizations")).mock(
        return_value=httpx.Response(
            200, json=[make_org(deleted_at="2025-01-01T00:00:00+00:00")]
        )
    )
    respx_mock.post(rpc_url("admin_restore_organization")).mock(
        return_value=_pg_error("P0002", "Organization not found", status_code=400)
    )
    unban_route = respx_mock.put(
        url__regex=rf"http://test-supabase.local/auth/v1/admin/users/.*"
    ).mock(return_value=httpx.Response(200, json={}))

    resp = staff_client.post(f"{V2_ROOT}/admin/organizations/{ORG_ID}/restore")

    assert resp.status_code == 404, resp.text
    assert not unban_route.called


def test_restore_organization_400_when_not_archived(staff_client, respx_mock):
    respx_mock.get(rest_url("organizations")).mock(
        return_value=httpx.Response(200, json=[make_org(deleted_at=None)])
    )
    resp = staff_client.post(f"{V2_ROOT}/admin/organizations/{ORG_ID}/restore")
    assert resp.status_code == 400, resp.text
