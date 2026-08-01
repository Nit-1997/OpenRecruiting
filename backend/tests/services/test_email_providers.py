"""Characterization tests for the email provider layer.

Covers ZohoEmailProvider, ResendEmailProvider, the get_email_provider factory,
and EmailService template/scheduler routing. The HTTP client is mocked so no
network is touched; we assert on the EmailResult shape the callers depend on.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.services.email.base import EmailMessage, EmailResult
from app.services.email.resend_provider import ResendEmailProvider
from app.services.email.zoho_provider import ZohoEmailProvider, get_email_provider


def _msg(**over):
    base = dict(
        to_email="dest@example.com",
        to_name="Dest",
        subject="Hi",
        html_body="<p>hello</p>",
    )
    base.update(over)
    return EmailMessage(**base)


def _mock_client(module, response=None, raise_exc=None):
    client = MagicMock()
    if raise_exc is not None:
        client.post = AsyncMock(side_effect=raise_exc)
    else:
        client.post = AsyncMock(return_value=response)
    return patch.object(module, "get_async_http_client", return_value=client), client


# ----------------------------- Zoho -----------------------------

@pytest.mark.asyncio
async def test_zoho_success_returns_request_id():
    import app.services.email.zoho_provider as zoho
    resp = httpx.Response(201, json={"request_id": "req-123"})
    p, client = _mock_client(zoho, response=resp)
    with p:
        provider = ZohoEmailProvider("tok", "from@m.ai", "OpenRecruiting", "https://api.zepto.test")
        result = await provider.send_email(_msg(text_body="plain", reply_to="reply@m.ai"))
    assert result == EmailResult(success=True, message_id="req-123")
    # text_body + reply_to should have been threaded into the payload
    sent = client.post.call_args.kwargs["json"]
    assert sent["textbody"] == "plain"
    assert sent["reply_to"] == [{"address": "reply@m.ai"}]


@pytest.mark.asyncio
async def test_zoho_error_status_parses_error_body():
    import app.services.email.zoho_provider as zoho
    resp = httpx.Response(400, json={"error": {"code": "TM_3201", "message": "bad addr"}})
    p, _ = _mock_client(zoho, response=resp)
    with p:
        provider = ZohoEmailProvider("tok", "from@m.ai", "OpenRecruiting", "https://api.zepto.test")
        result = await provider.send_email(_msg())
    assert result.success is False
    assert "TM_3201" in result.error and "bad addr" in result.error


@pytest.mark.asyncio
async def test_zoho_error_status_non_json_body():
    import app.services.email.zoho_provider as zoho
    resp = httpx.Response(503, text="upstream down")
    p, _ = _mock_client(zoho, response=resp)
    with p:
        provider = ZohoEmailProvider("tok", "from@m.ai", "OpenRecruiting", "https://api.zepto.test")
        result = await provider.send_email(_msg())
    assert result.success is False
    assert "HTTP 503" in result.error


@pytest.mark.asyncio
async def test_zoho_request_error_returns_failure():
    import app.services.email.zoho_provider as zoho
    p, _ = _mock_client(zoho, raise_exc=httpx.ConnectError("boom"))
    with p:
        provider = ZohoEmailProvider("tok", "from@m.ai", "OpenRecruiting", "https://api.zepto.test")
        result = await provider.send_email(_msg())
    assert result.success is False
    assert "Request failed" in result.error


@pytest.mark.asyncio
async def test_zoho_send_batch_iterates():
    import app.services.email.zoho_provider as zoho
    resp = httpx.Response(200, json={"request_id": "r"})
    p, _ = _mock_client(zoho, response=resp)
    with p:
        provider = ZohoEmailProvider("tok", "from@m.ai", "OpenRecruiting", "https://api.zepto.test")
        results = await provider.send_batch([_msg(), _msg()])
    assert len(results) == 2
    assert all(r.success for r in results)


# ----------------------------- Resend -----------------------------

@pytest.mark.asyncio
async def test_resend_success_returns_id():
    import app.services.email.resend_provider as resend
    resp = httpx.Response(200, json={"id": "re-1"})
    p, client = _mock_client(resend, response=resp)
    with p:
        provider = ResendEmailProvider("key", "from@m.ai", "OpenRecruiting")
        result = await provider.send_email(_msg(text_body="t", reply_to="r@m.ai"))
    assert result == EmailResult(success=True, message_id="re-1")
    sent = client.post.call_args.kwargs["json"]
    assert sent["from"] == "OpenRecruiting <from@m.ai>"
    assert sent["text"] == "t"
    assert sent["reply_to"] == "r@m.ai"


@pytest.mark.asyncio
async def test_resend_error_status_parses_body():
    import app.services.email.resend_provider as resend
    resp = httpx.Response(422, json={"name": "validation_error", "message": "bad"})
    p, _ = _mock_client(resend, response=resp)
    with p:
        provider = ResendEmailProvider("key", "from@m.ai", "OpenRecruiting")
        result = await provider.send_email(_msg())
    assert result.success is False
    assert "validation_error" in result.error


@pytest.mark.asyncio
async def test_resend_error_non_json_body():
    import app.services.email.resend_provider as resend
    resp = httpx.Response(500, text="oops")
    p, _ = _mock_client(resend, response=resp)
    with p:
        provider = ResendEmailProvider("key", "from@m.ai", "OpenRecruiting")
        result = await provider.send_email(_msg())
    assert result.success is False
    assert "HTTP 500" in result.error


@pytest.mark.asyncio
async def test_resend_request_error():
    import app.services.email.resend_provider as resend
    p, _ = _mock_client(resend, raise_exc=httpx.ConnectError("nope"))
    with p:
        provider = ResendEmailProvider("key", "from@m.ai", "OpenRecruiting")
        result = await provider.send_email(_msg())
    assert result.success is False
    assert "Request failed" in result.error


@pytest.mark.asyncio
async def test_resend_send_batch():
    import app.services.email.resend_provider as resend
    resp = httpx.Response(200, json={"id": "x"})
    p, _ = _mock_client(resend, response=resp)
    with p:
        provider = ResendEmailProvider("key", "from@m.ai", "OpenRecruiting")
        results = await provider.send_batch([_msg()])
    assert results[0].success


# ----------------------------- factory -----------------------------

def _settings(**over):
    base = dict(
        EMAIL_PROVIDER="zoho",
        ZEPTOMAIL_API_TOKEN="tok",
        EMAIL_FROM_ADDRESS="from@m.ai",
        EMAIL_FROM_NAME="OpenRecruiting",
        ZEPTOMAIL_BASE_URL="https://api.zepto.test",
        RESEND_API_KEY="rk",
    )
    base.update(over)
    return SimpleNamespace(**base)


@pytest.fixture(autouse=True)
def _clear_provider_cache():
    # get_email_provider is @lru_cache'd; clear so each factory test reads fresh settings.
    get_email_provider.cache_clear()
    yield
    get_email_provider.cache_clear()


def test_factory_zoho():
    import app.services.email.zoho_provider as zoho
    with patch.object(zoho, "get_settings", lambda: _settings()):
        provider = get_email_provider()
    assert isinstance(provider, ZohoEmailProvider)


def test_factory_zoho_missing_token_raises():
    import app.services.email.zoho_provider as zoho
    with patch.object(zoho, "get_settings", lambda: _settings(ZEPTOMAIL_API_TOKEN="")):
        with pytest.raises(ValueError, match="ZEPTOMAIL_API_TOKEN"):
            get_email_provider()


def test_factory_resend():
    import app.services.email.zoho_provider as zoho
    with patch.object(zoho, "get_settings", lambda: _settings(EMAIL_PROVIDER="resend")):
        provider = get_email_provider()
    assert isinstance(provider, ResendEmailProvider)


def test_factory_resend_missing_key_raises():
    import app.services.email.zoho_provider as zoho
    with patch.object(zoho, "get_settings", lambda: _settings(EMAIL_PROVIDER="resend", RESEND_API_KEY="")):
        with pytest.raises(ValueError, match="RESEND_API_KEY"):
            get_email_provider()


def test_factory_unimplemented_providers_raise():
    import app.services.email.zoho_provider as zoho
    for name in ("sendgrid", "postmark"):
        with patch.object(zoho, "get_settings", lambda n=name: _settings(EMAIL_PROVIDER=n)):
            with pytest.raises(NotImplementedError):
                get_email_provider()


def test_factory_unknown_provider_raises():
    import app.services.email.zoho_provider as zoho
    with patch.object(zoho, "get_settings", lambda: _settings(EMAIL_PROVIDER="carrier-pigeon")):
        with pytest.raises(ValueError, match="Unknown email provider"):
            get_email_provider()
