"""BE-S4: admin users router — safe-ordered reset-invite with compensation.

`POST /admin/users/{user_id}/reset-invite` spans the Supabase Auth API (delete
auth user, send invite) AND a profiles DB write. A pure DB transaction cannot
cover the auth-user steps, so this is NOT an RPC. Instead it is SAFELY ORDERED:

  1. read the existing profile
  2. invite the NEW auth user (reversible: can be deleted)
  3. insert the NEW profile row (reversible: compensated by deleting the new
     auth user on failure)
  4. delete the OLD auth user LAST (irreversible; old profile cascades) — only
     after the new user + profile are in place

The prior code deleted the old auth user FIRST, so a later invite/insert
failure destroyed the only record of the user. The new ordering guarantees the
old account survives until the replacement is fully created.

These tests pin:
  - success: invite happens, profile inserted, old user deleted LAST
  - profile-insert failure compensates by deleting the NEW auth user and does
    NOT delete the old auth user (old account preserved)
  - 404 when the user does not exist
"""
import httpx

from tests.helpers.supabase_mocks import rest_url, auth_url
from tests.helpers.mock_data import RECRUITER_USER_ID, make_profile

V2_ROOT = "/api/v2"

OLD_ID = RECRUITER_USER_ID
NEW_ID = "00000000-0000-0000-0000-0000000000c1"


def test_reset_invite_success_deletes_old_user_last(staff_client, respx_mock):
    order = []

    respx_mock.get(rest_url("profiles")).mock(
        return_value=httpx.Response(200, json=[make_profile(user_id=OLD_ID)])
    )

    def _invite(_request):
        order.append("invite")
        return httpx.Response(200, json={"id": NEW_ID})

    def _insert_profile(_request):
        order.append("insert_profile")
        return httpx.Response(201, json=[make_profile(user_id=NEW_ID)])

    def _delete_user(_request):
        order.append("delete_user")
        return httpx.Response(204)

    respx_mock.post(auth_url("/invite")).mock(side_effect=_invite)
    respx_mock.post(rest_url("profiles")).mock(side_effect=_insert_profile)
    respx_mock.delete(
        url__regex=rf"http://test-supabase.local/auth/v1/admin/users/.*"
    ).mock(side_effect=_delete_user)

    resp = staff_client.post(f"{V2_ROOT}/admin/users/{OLD_ID}/reset-invite")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["user_id"] == NEW_ID
    # Safe ordering: invite + new-profile insert BEFORE the destructive
    # old-user delete.
    assert order == ["invite", "insert_profile", "delete_user"], order


def test_reset_invite_profile_insert_failure_compensates(staff_client, respx_mock):
    """New-profile insert fails -> delete the NEW user (compensation); the OLD
    user/profile must remain (we must NOT have deleted the old auth user)."""
    deleted_ids = []

    respx_mock.get(rest_url("profiles")).mock(
        return_value=httpx.Response(200, json=[make_profile(user_id=OLD_ID)])
    )
    respx_mock.post(auth_url("/invite")).mock(
        return_value=httpx.Response(200, json={"id": NEW_ID})
    )
    respx_mock.post(rest_url("profiles")).mock(
        return_value=httpx.Response(
            400, json={"code": "23505", "message": "duplicate key"}
        )
    )

    def _delete_user(request):
        # capture which auth user id was deleted
        deleted_ids.append(request.url.path.rsplit("/", 1)[-1])
        return httpx.Response(204)

    respx_mock.delete(
        url__regex=rf"http://test-supabase.local/auth/v1/admin/users/.*"
    ).mock(side_effect=_delete_user)

    resp = staff_client.post(f"{V2_ROOT}/admin/users/{OLD_ID}/reset-invite")

    assert resp.status_code == 500, resp.text
    # Compensation deleted the NEW user, never the OLD one.
    assert NEW_ID in deleted_ids
    assert OLD_ID not in deleted_ids


def test_reset_invite_404_when_missing(staff_client, respx_mock):
    respx_mock.get(rest_url("profiles")).mock(
        return_value=httpx.Response(200, json=[])
    )
    resp = staff_client.post(f"{V2_ROOT}/admin/users/{OLD_ID}/reset-invite")
    assert resp.status_code == 404, resp.text
