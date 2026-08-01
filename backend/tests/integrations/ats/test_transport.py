"""KnitTransport contracts: headers, bounded retry/backoff honoring
Retry-After, and the HTTP→taxonomy error mapping (the ONLY place httpx
errors are translated)."""

import httpx
import pytest
import respx

from app.integrations.ats.core.errors import (
    AtsAuthError,
    AtsNotSupportedError,
    AtsProviderError,
    AtsRateLimitedError,
    AtsResourceNotFoundError,
)
from app.integrations.ats.unified_knit.transport import KnitTransport

BASE = "https://knit.test/v1.0"


def make_transport() -> KnitTransport:
    return KnitTransport(api_key="k-secret", base_url=BASE)


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    async def _instant(_secs):
        return None

    monkeypatch.setattr(
        "app.integrations.ats.unified_knit.transport.asyncio.sleep", _instant
    )


async def test_sends_auth_and_integration_headers():
    with respx.mock(assert_all_called=True) as mock:
        route = mock.get(f"{BASE}/ats.job.list").respond(
            200, json={"success": True, "data": {"jobs": []}}
        )
        transport = make_transport()
        body = await transport.request("GET", "/ats.job.list", integration_id="int-1")
        await transport.aclose()
    sent = route.calls[0].request
    assert sent.headers["Authorization"] == "Bearer k-secret"
    assert sent.headers["X-Knit-Integration-Id"] == "int-1"
    assert body["data"]["jobs"] == []


async def test_platform_calls_omit_integration_header():
    with respx.mock as mock:
        route = mock.post(f"{BASE}/auth.createSession").respond(
            200, json={"success": True, "msg": {"token": "t"}}
        )
        transport = make_transport()
        await transport.request("POST", "/auth.createSession", json={"a": 1})
        await transport.aclose()
    assert "X-Knit-Integration-Id" not in route.calls[0].request.headers


async def test_retries_on_429_honoring_retry_after_then_succeeds():
    with respx.mock as mock:
        route = mock.get(f"{BASE}/ats.job.list")
        route.side_effect = [
            httpx.Response(
                429,
                headers={"Retry-After": "1"},
                json={"success": False, "error": {"msg": "slow down"}},
            ),
            httpx.Response(200, json={"success": True, "data": {}}),
        ]
        transport = make_transport()
        body = await transport.request("GET", "/ats.job.list", integration_id="i")
        await transport.aclose()
    assert body["success"] is True
    assert route.call_count == 2


async def test_rate_limit_exhausts_to_error():
    with respx.mock as mock:
        route = mock.get(f"{BASE}/p").respond(
            429, json={"success": False, "error": {"msg": "x"}}
        )
        transport = make_transport()
        with pytest.raises(AtsRateLimitedError):
            await transport.request("GET", "/p", integration_id="i")
        await transport.aclose()
    assert route.call_count == 3


async def test_5xx_retries_then_provider_error():
    with respx.mock as mock:
        route = mock.get(f"{BASE}/p").respond(502, json={})
        transport = make_transport()
        with pytest.raises(AtsProviderError):
            await transport.request("GET", "/p", integration_id="i")
        await transport.aclose()
    assert route.call_count == 3


@pytest.mark.parametrize("status", [401, 403])
async def test_auth_errors_no_retry(status):
    with respx.mock as mock:
        route = mock.get(f"{BASE}/p").respond(
            status, json={"success": False, "error": {"msg": "bad key"}}
        )
        transport = make_transport()
        with pytest.raises(AtsAuthError):
            await transport.request("GET", "/p", integration_id="i")
        await transport.aclose()
    assert route.call_count == 1


async def test_404_classification_unsupported_vs_missing():
    with respx.mock as mock:
        mock.get(f"{BASE}/unsupported").respond(
            404,
            json={"success": False, "error": {"msg": "Tool not supported for this app"}},
        )
        mock.get(f"{BASE}/missing").respond(
            404, json={"success": False, "error": {"msg": "Application not found"}}
        )
        transport = make_transport()
        with pytest.raises(AtsNotSupportedError):
            await transport.request("GET", "/unsupported", integration_id="i")
        with pytest.raises(AtsResourceNotFoundError):
            await transport.request("GET", "/missing", integration_id="i")
        await transport.aclose()


async def test_success_false_body_maps_to_provider_error():
    with respx.mock as mock:
        mock.get(f"{BASE}/p").respond(
            200, json={"success": False, "error": {"msg": "internal"}}
        )
        transport = make_transport()
        with pytest.raises(AtsProviderError):
            await transport.request("GET", "/p", integration_id="i")
        await transport.aclose()


async def test_network_error_retries_then_provider_error():
    with respx.mock as mock:
        route = mock.get(f"{BASE}/p")
        route.side_effect = httpx.ConnectError("boom")
        transport = make_transport()
        with pytest.raises(AtsProviderError):
            await transport.request("GET", "/p", integration_id="i")
        await transport.aclose()
    assert route.call_count == 3
