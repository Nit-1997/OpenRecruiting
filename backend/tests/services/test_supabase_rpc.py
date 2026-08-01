"""Unit tests for SupabaseAdminClient.rpc — specifically the 204 No Content path
that PostgREST returns for RETURNS VOID functions."""

import httpx
import pytest
import respx

from app.services.supabase import RpcError, SupabaseAdminClient, TableResponse

FAKE_URL = "http://test-supabase.local"
FAKE_KEY = "test-secret-key-placeholder"


@pytest.fixture
def client():
    return SupabaseAdminClient(url=FAKE_URL, secret_key=FAKE_KEY)


@pytest.mark.asyncio
async def test_rpc_204_returns_empty_success(client):
    """204 No Content (RETURNS VOID) must not raise; data must be None."""
    with respx.mock:
        respx.post(f"{FAKE_URL}/rest/v1/rpc/intake_sessions_append_turn").mock(
            return_value=httpx.Response(204)
        )
        result = await client.rpc("intake_sessions_append_turn", {"p_session_id": "abc"})

    assert isinstance(result, TableResponse)
    assert result.data is None


@pytest.mark.asyncio
async def test_rpc_200_returns_data(client):
    """200 OK with JSON body is still handled correctly."""
    with respx.mock:
        respx.post(f"{FAKE_URL}/rest/v1/rpc/some_func").mock(
            return_value=httpx.Response(200, json={"key": "value"})
        )
        result = await client.rpc("some_func", {})

    assert result.data == {"key": "value"}


@pytest.mark.asyncio
async def test_rpc_error_raises(client):
    """4xx/5xx responses must still raise RpcError."""
    with respx.mock:
        respx.post(f"{FAKE_URL}/rest/v1/rpc/bad_func").mock(
            return_value=httpx.Response(
                400,
                json={"message": "bad input", "code": "P0001", "details": None, "hint": None},
            )
        )
        with pytest.raises(RpcError) as exc_info:
            await client.rpc("bad_func", {})

    assert exc_info.value.code == "P0001"
    assert "bad input" in str(exc_info.value)
