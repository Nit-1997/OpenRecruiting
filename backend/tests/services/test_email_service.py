"""Characterization tests for EmailService (template render + recipient routing)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from jinja2 import DictLoader, Environment

from app.services.email.base import EmailMessage, EmailResult
from app.services.email.service import EmailService


def _service(provider=None):
    env = Environment(loader=DictLoader({"hello.html": "Hi {{ name }}"}))
    provider = provider or MagicMock()
    return EmailService(provider=provider, template_env=env)


@pytest.mark.asyncio
async def test_send_templated_email_renders_and_delegates():
    provider = MagicMock()
    provider.send_email = AsyncMock(return_value=EmailResult(success=True, message_id="m1"))
    svc = _service(provider)
    result = await svc.send_templated_email(
        to_email="x@y.com", to_name="X", subject="S",
        template_name="hello.html", context={"name": "World"}, reply_to="r@y.com",
    )
    assert result.message_id == "m1"
    sent: EmailMessage = provider.send_email.call_args.args[0]
    assert sent.html_body == "Hi World"
    assert sent.reply_to == "r@y.com"


@pytest.mark.asyncio
async def test_send_email_delegates_to_provider():
    provider = MagicMock()
    provider.send_email = AsyncMock(return_value=EmailResult(success=True))
    svc = _service(provider)
    msg = EmailMessage(to_email="a@b.com", to_name=None, subject="s", html_body="<p>x</p>")
    assert (await svc.send_email(msg)).success


def _supabase_for_scheduler(rounds_row, req_row, profile_row=None, fallback_rows=None):
    """Build a supabase mock keyed by table name; each table call returns its row(s)."""
    sb = MagicMock()

    def table(name):
        tbl = MagicMock()
        chain = MagicMock()
        # the chain ends in .execute_async() returning a result with .data
        if name == "candidate_rounds":
            data = rounds_row
            is_single = True
        elif name == "requisitions":
            data = req_row
            is_single = True
        elif name == "profiles":
            # profiles is used twice (scheduler single, fallback list); pick by call
            data = profile_row
            is_single = profile_row is not None or fallback_rows is None

        result = MagicMock()
        if name == "profiles" and fallback_rows is not None and profile_row is None:
            result.data = fallback_rows
        else:
            result.data = data
        # make every chained builder method return chain, terminal execute_async returns result
        for attr in ("select", "eq", "single", "is_null", "order"):
            setattr(chain, attr, MagicMock(return_value=chain))
        chain.execute_async = AsyncMock(return_value=result)
        tbl.select = MagicMock(return_value=chain)
        return tbl

    sb.table = MagicMock(side_effect=table)
    return sb


@pytest.mark.asyncio
async def test_get_scheduler_email_uses_active_scheduler():
    sb = _supabase_for_scheduler(
        rounds_row={"created_by_user_id": "u1", "candidates": {"requisition_id": "req1"}},
        req_row={"organization_id": "org1"},
        profile_row={"email": "sched@m.ai", "full_name": "Sched Uler", "deleted_at": None},
    )
    with patch("app.services.email.service.get_supabase_admin_client", return_value=sb):
        result = await _service().get_scheduler_email("cr1")
    assert result == ("sched@m.ai", "Sched Uler")


@pytest.mark.asyncio
async def test_get_scheduler_email_round_not_found():
    sb = _supabase_for_scheduler(rounds_row=None, req_row=None)
    with patch("app.services.email.service.get_supabase_admin_client", return_value=sb):
        assert await _service().get_scheduler_email("cr1") is None


@pytest.mark.asyncio
async def test_get_scheduler_email_no_candidate_data():
    sb = _supabase_for_scheduler(
        rounds_row={"created_by_user_id": "u1", "candidates": None}, req_row=None
    )
    with patch("app.services.email.service.get_supabase_admin_client", return_value=sb):
        assert await _service().get_scheduler_email("cr1") is None


@pytest.mark.asyncio
async def test_get_scheduler_email_falls_back_to_org_admin():
    sb = _supabase_for_scheduler(
        rounds_row={"created_by_user_id": None, "candidates": {"requisition_id": "req1"}},
        req_row={"organization_id": "org1"},
        profile_row=None,
        fallback_rows=[{"email": "admin@m.ai", "full_name": "Admin"}],
    )
    with patch("app.services.email.service.get_supabase_admin_client", return_value=sb):
        result = await _service().get_scheduler_email("cr1")
    assert result == ("admin@m.ai", "Admin")


@pytest.mark.asyncio
async def test_get_scheduler_email_no_recipient_at_all():
    sb = _supabase_for_scheduler(
        rounds_row={"created_by_user_id": None, "candidates": {"requisition_id": "req1"}},
        req_row={"organization_id": "org1"},
        profile_row=None,
        fallback_rows=[],
    )
    with patch("app.services.email.service.get_supabase_admin_client", return_value=sb):
        assert await _service().get_scheduler_email("cr1") is None


@pytest.mark.asyncio
async def test_get_interviewer_email_present():
    sb = MagicMock()
    chain = MagicMock()
    for attr in ("select", "eq", "single"):
        setattr(chain, attr, MagicMock(return_value=chain))
    chain.execute_async = AsyncMock(return_value=MagicMock(data={"interviewer_email": "jane.doe@m.ai"}))
    sb.table.return_value.select.return_value = chain
    with patch("app.services.email.service.get_supabase_admin_client", return_value=sb):
        result = await _service().get_interviewer_email("cr1")
    assert result == ("jane.doe@m.ai", "Jane Doe")


@pytest.mark.asyncio
async def test_get_interviewer_email_absent():
    sb = MagicMock()
    chain = MagicMock()
    for attr in ("select", "eq", "single"):
        setattr(chain, attr, MagicMock(return_value=chain))
    chain.execute_async = AsyncMock(return_value=MagicMock(data={"interviewer_email": None}))
    sb.table.return_value.select.return_value = chain
    with patch("app.services.email.service.get_supabase_admin_client", return_value=sb):
        assert await _service().get_interviewer_email("cr1") is None


@pytest.mark.asyncio
async def test_get_interviewer_email_round_not_found():
    sb = MagicMock()
    chain = MagicMock()
    for attr in ("select", "eq", "single"):
        setattr(chain, attr, MagicMock(return_value=chain))
    chain.execute_async = AsyncMock(return_value=MagicMock(data=None))
    sb.table.return_value.select.return_value = chain
    with patch("app.services.email.service.get_supabase_admin_client", return_value=sb):
        assert await _service().get_interviewer_email("cr1") is None
