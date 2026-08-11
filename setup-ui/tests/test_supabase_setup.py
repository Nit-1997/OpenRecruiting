import httpx
import pytest

from app.supabase_setup import check_schema, manual_instructions


def _patched(handler):
    original = httpx.AsyncClient
    transport = httpx.MockTransport(handler)

    class Patched(original):  # type: ignore[misc,valid-type]
        def __init__(self, *a, **kw):
            kw["transport"] = transport
            super().__init__(*a, **kw)

    httpx.AsyncClient = Patched  # type: ignore[misc]
    return lambda: setattr(httpx, "AsyncClient", original)


@pytest.mark.asyncio
async def test_a_provisioned_project_reports_ready():
    restore = _patched(lambda r: httpx.Response(200, json=[]))
    try:
        status = await check_schema("https://p.supabase.co", "key")
    finally:
        restore()
    assert status.ready is True


@pytest.mark.asyncio
async def test_a_reachable_but_empty_project_reports_not_applied():
    """404 on the sentinel table means the project is fine and the schema is
    missing — a completely different fix from a bad URL, so the two must not
    collapse into one message."""
    restore = _patched(lambda r: httpx.Response(404, json={"code": "PGRST205"}))
    try:
        status = await check_schema("https://p.supabase.co", "key")
    finally:
        restore()
    assert status.state == "not_applied"
    assert status.ready is False


@pytest.mark.asyncio
async def test_a_rejected_key_is_not_reported_as_a_missing_schema():
    restore = _patched(lambda r: httpx.Response(401))
    try:
        status = await check_schema("https://p.supabase.co", "key")
    finally:
        restore()
    assert status.state == "unreachable"


@pytest.mark.asyncio
async def test_an_unreachable_host_is_reported_as_unreachable():
    def boom(request):
        raise httpx.ConnectError("no route to host")

    restore = _patched(boom)
    try:
        status = await check_schema("https://p.supabase.co", "key")
    finally:
        restore()
    assert status.state == "unreachable"


@pytest.mark.asyncio
async def test_missing_credentials_short_circuit_without_a_request():
    called = []

    restore = _patched(lambda r: called.append(1) or httpx.Response(200, json=[]))
    try:
        status = await check_schema("", "")
    finally:
        restore()
    assert status.state == "unconfigured"
    assert called == []


def test_the_instructions_name_the_users_own_project():
    steps = manual_instructions("https://abcdef.supabase.co")

    assert any("abcdef" in s for s in steps)
    assert any("schema.sql" in s for s in steps)
    # schema.sql is NOT idempotent, so "just run it again" must never be the
    # advice — the warning is part of the instructions.
    assert any("not re-runnable" in s for s in steps)
