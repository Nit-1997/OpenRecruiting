"""KnitPlatformApi contracts: session creation (ATS-filtered), org-integration
listing (the server-side verification source of truth), deactivation."""

import json

import pytest
import respx

from app.integrations.ats.core.errors import AtsProviderError
from app.integrations.ats.unified_knit.auth import KnitPlatformApi
from app.integrations.ats.unified_knit.transport import KnitTransport

BASE = "https://knit.test/v1.0"


def make_api() -> tuple[KnitPlatformApi, KnitTransport]:
    transport = KnitTransport(api_key="k", base_url=BASE)
    return KnitPlatformApi(transport), transport


async def test_create_auth_session_returns_token_and_filters_ats():
    with respx.mock as mock:
        route = mock.post(f"{BASE}/auth.createSession").respond(
            200, json={"success": True, "msg": {"token": "sess-tok"}}
        )
        api, transport = make_api()
        token = await api.create_auth_session(
            origin_org_id="org-1",
            origin_org_name="Acme",
            origin_user_email="r@acme.co",
            origin_user_name="Rae",
        )
        await transport.aclose()
    assert token == "sess-tok"
    sent = json.loads(route.calls[0].request.content)
    assert sent["originOrgId"] == "org-1"
    assert sent["originOrgName"] == "Acme"
    assert sent["originUserEmail"] == "r@acme.co"
    assert sent["originUserName"] == "Rae"
    assert sent["filters"] == [{"category": "ATS"}]


async def test_create_auth_session_malformed_response_raises():
    with respx.mock as mock:
        mock.post(f"{BASE}/auth.createSession").respond(200, json={"success": True})
        api, transport = make_api()
        with pytest.raises(AtsProviderError):
            await api.create_auth_session(
                origin_org_id="o",
                origin_org_name="n",
                origin_user_email="e@x.co",
                origin_user_name="u",
            )
        await transport.aclose()


async def test_list_org_integrations_parses_apps():
    with respx.mock as mock:
        route = mock.get(f"{BASE}/integration.details").respond(
            200,
            json={
                "success": True,
                "data": {
                    "apps": [
                        {
                            "id": "workable",
                            "category": "ATS",
                            "integrationId": "int-9",
                            "isActive": True,
                            "deactivatedAt": None,
                            "shortLogo": "https://x/logo.png",
                        }
                    ]
                },
            },
        )
        api, transport = make_api()
        apps = await api.list_org_integrations("org-1")
        await transport.aclose()
    assert "originOrgId=org-1" in str(route.calls[0].request.url)
    assert apps[0].app_id == "workable"
    assert apps[0].integration_id == "int-9"
    assert apps[0].is_active is True


async def test_list_org_integrations_empty_data():
    with respx.mock as mock:
        mock.get(f"{BASE}/integration.details").respond(
            200, json={"success": True, "data": {}}
        )
        api, transport = make_api()
        apps = await api.list_org_integrations("org-1")
        await transport.aclose()
    assert apps == []


async def test_deactivate_integration_sends_integration_header():
    with respx.mock as mock:
        route = mock.post(f"{BASE}/integration.deactivate").respond(
            200, json={"success": True, "data": None}
        )
        api, transport = make_api()
        await api.deactivate_integration("int-9")
        await transport.aclose()
    assert route.calls[0].request.headers["X-Knit-Integration-Id"] == "int-9"
