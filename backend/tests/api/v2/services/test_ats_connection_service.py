"""ats_connection_service: session creation, server-side verification on
complete (never trust FE integrationDetails), status, best-effort disconnect."""

from uuid import UUID

import pytest

from app.api.v2.core.dependencies import CurrentUserWithOrg
from app.api.v2.core.exceptions import ForbiddenError, NotFoundError, ValidationError
from app.api.v2.services import ats_connection_service as svc
from app.dependencies import CurrentUser
from app.services.supabase import get_supabase_admin_client
from tests.helpers.mock_data import ORG_ID, RECRUITER_EMAIL, RECRUITER_USER_ID
from tests.helpers.supabase_mocks import mock_rpc, mock_select, mock_update

KNIT = "https://api.getknit.dev/v1.0"

APPS_OK = {
    "success": True,
    "data": {
        "apps": [
            {
                "id": "workable",
                "category": "ATS",
                "integrationId": "int-1",
                "isActive": True,
                "deactivatedAt": None,
            }
        ]
    },
}

ACTIVE_ROW = {
    "id": "conn-1",
    "provider": "workable",
    "status": "active",
    "connected_at": "2026-06-11T00:00:00+00:00",
    "connected_by": RECRUITER_USER_ID,
    "knit_integration_id": "int-1",
}


def make_current() -> CurrentUserWithOrg:
    return CurrentUserWithOrg(
        user=CurrentUser(
            id=UUID(RECRUITER_USER_ID),
            email=RECRUITER_EMAIL,
            is_staff=False,
            organization_id=UUID(ORG_ID),
        ),
        organization_id=UUID(ORG_ID),
    )


async def test_create_auth_session_pulls_org_and_profile(respx_mock):
    mock_select(respx_mock, "organizations", [{"name": "Acme"}])
    mock_select(respx_mock, "profiles", [{"full_name": "Rae R"}])
    import json

    route = respx_mock.post(f"{KNIT}/auth.createSession").respond(
        200, json={"success": True, "msg": {"token": "tok"}}
    )
    token = await svc.create_auth_session(get_supabase_admin_client(), make_current())
    assert token == "tok"
    sent = json.loads(route.calls[0].request.content)
    assert sent["originOrgId"] == ORG_ID
    assert sent["originOrgName"] == "Acme"
    assert sent["originUserName"] == "Rae R"


async def test_create_auth_session_falls_back_to_email_name(respx_mock):
    mock_select(respx_mock, "organizations", [])
    mock_select(respx_mock, "profiles", [])
    import json

    route = respx_mock.post(f"{KNIT}/auth.createSession").respond(
        200, json={"success": True, "msg": {"token": "tok"}}
    )
    await svc.create_auth_session(get_supabase_admin_client(), make_current())
    sent = json.loads(route.calls[0].request.content)
    assert sent["originOrgName"] == ORG_ID
    assert sent["originUserName"] == RECRUITER_EMAIL


async def test_complete_rejects_cross_org(respx_mock):
    with pytest.raises(ForbiddenError):
        await svc.complete_connection(
            get_supabase_admin_client(),
            make_current(),
            integration_id="int-1",
            origin_org_id="some-other-org",
            app_id="workable",
        )


async def test_complete_rejects_unknown_integration(respx_mock):
    respx_mock.get(f"{KNIT}/integration.details").respond(
        200, json={"success": True, "data": {"apps": []}}
    )
    with pytest.raises(ValidationError):
        await svc.complete_connection(
            get_supabase_admin_client(),
            make_current(),
            integration_id="int-1",
            origin_org_id=ORG_ID,
            app_id="workable",
        )


async def test_complete_rejects_inactive_integration(respx_mock):
    inactive = {
        "success": True,
        "data": {
            "apps": [
                {
                    "id": "workable",
                    "category": "ATS",
                    "integrationId": "int-1",
                    "isActive": False,
                }
            ]
        },
    }
    respx_mock.get(f"{KNIT}/integration.details").respond(200, json=inactive)
    with pytest.raises(ValidationError):
        await svc.complete_connection(
            get_supabase_admin_client(),
            make_current(),
            integration_id="int-1",
            origin_org_id=ORG_ID,
            app_id="workable",
        )


async def test_complete_rejects_non_ats_category(respx_mock):
    crm = {
        "success": True,
        "data": {
            "apps": [
                {
                    "id": "hubspot",
                    "category": "CRM",
                    "integrationId": "int-1",
                    "isActive": True,
                }
            ]
        },
    }
    respx_mock.get(f"{KNIT}/integration.details").respond(200, json=crm)
    with pytest.raises(ValidationError):
        await svc.complete_connection(
            get_supabase_admin_client(),
            make_current(),
            integration_id="int-1",
            origin_org_id=ORG_ID,
            app_id="hubspot",
        )


async def test_complete_happy_path_calls_rpc_and_returns_status(respx_mock):
    respx_mock.get(f"{KNIT}/integration.details").respond(200, json=APPS_OK)
    mock_rpc(respx_mock, "ats_connect", "conn-1")
    mock_select(respx_mock, "ats_connections", [ACTIVE_ROW])
    mock_select(respx_mock, "profiles", [{"full_name": "Rae R"}])
    status = await svc.complete_connection(
        get_supabase_admin_client(),
        make_current(),
        integration_id="int-1",
        origin_org_id=ORG_ID,
        app_id="workable",
    )
    assert status.connected is True
    assert status.provider == "workable"
    assert status.connected_by_name == "Rae R"


async def test_status_not_connected(respx_mock):
    mock_select(respx_mock, "ats_connections", [])
    status = await svc.get_status(get_supabase_admin_client(), make_current())
    assert status.connected is False and status.provider is None


async def test_disconnect_survives_knit_failure(respx_mock):
    mock_select(respx_mock, "ats_connections", [ACTIVE_ROW])
    # 400 → AtsProviderError without the retry/backoff loop (keeps the test fast;
    # retry behavior itself is covered in test_transport.py).
    respx_mock.post(f"{KNIT}/integration.deactivate").respond(
        400, json={"success": False, "error": {"msg": "boom"}}
    )
    mock_update(respx_mock, "ats_connections")
    await svc.disconnect(get_supabase_admin_client(), make_current())


async def test_disconnect_without_connection_raises(respx_mock):
    mock_select(respx_mock, "ats_connections", [])
    with pytest.raises(NotFoundError):
        await svc.disconnect(get_supabase_admin_client(), make_current())
