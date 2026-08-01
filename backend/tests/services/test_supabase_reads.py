"""Unit tests for the async READ paths of the custom PostgREST client.

BE-F1: read paths (`execute_async` select/single, `count_async`) must FAIL LOUD
on a non-2xx response — raising PostgrestError — instead of silently returning
an empty TableResponse([])/None. Silent-empty reads make callers unable to tell
"no rows" from "DB/network error", which has masked production data loss.
"""

import httpx
import pytest
import respx

from app.services.supabase import PostgrestError, SupabaseAdminClient

FAKE_URL = "http://test-supabase.local"
FAKE_KEY = "test-secret-key-placeholder"


@pytest.fixture
def client():
    return SupabaseAdminClient(url=FAKE_URL, secret_key=FAKE_KEY)


@pytest.mark.asyncio
async def test_select_500_raises_postgrest_error(client):
    """A 500 on a list read must raise PostgrestError, not return empty."""
    with respx.mock:
        respx.get(f"{FAKE_URL}/rest/v1/candidates").mock(
            return_value=httpx.Response(500, text="internal error")
        )
        with pytest.raises(PostgrestError) as exc_info:
            await client.table("candidates").select("*").eq("org_id", "x").execute_async()

    assert "500" in str(exc_info.value) or exc_info.value.message


@pytest.mark.asyncio
async def test_select_single_500_raises_postgrest_error(client):
    """A 500 on a .single() read must raise PostgrestError, not return None."""
    with respx.mock:
        respx.get(f"{FAKE_URL}/rest/v1/candidates").mock(
            return_value=httpx.Response(500, text="internal error")
        )
        with pytest.raises(PostgrestError):
            await client.table("candidates").select("*").eq("id", "x").single().execute_async()


@pytest.mark.asyncio
async def test_select_404_postgrest_body_raises_with_code(client):
    """A PostgREST error body (404 with code/message) raises with that code."""
    with respx.mock:
        respx.get(f"{FAKE_URL}/rest/v1/missing_table").mock(
            return_value=httpx.Response(
                404,
                json={
                    "message": "relation does not exist",
                    "code": "42P01",
                    "details": None,
                    "hint": None,
                },
            )
        )
        with pytest.raises(PostgrestError) as exc_info:
            await client.table("missing_table").select("*").execute_async()

    assert exc_info.value.code == "42P01"
    assert "relation does not exist" in str(exc_info.value)


@pytest.mark.asyncio
async def test_count_async_500_raises_postgrest_error(client):
    """count_async must raise on a non-2xx instead of returning 0."""
    with respx.mock:
        respx.get(f"{FAKE_URL}/rest/v1/candidates").mock(
            return_value=httpx.Response(500, text="internal error")
        )
        with pytest.raises(PostgrestError):
            await client.table("candidates").select("*").eq("org_id", "x").count_async()


@pytest.mark.asyncio
async def test_single_no_rows_pgrst116_returns_none_not_raise(client):
    """.single() zero-rows is PostgREST code PGRST116 (HTTP 406) — a legitimate
    empty result, NOT a DB error. It must return TableResponse(None), preserving
    the `if not result.data:` contract callers branch on for 404s."""
    with respx.mock:
        respx.get(f"{FAKE_URL}/rest/v1/requisitions").mock(
            return_value=httpx.Response(
                406, json={"code": "PGRST116", "message": "no rows"}
            )
        )
        result = await client.table("requisitions").select("*").eq("id", "x").single().execute_async()

    assert result.data is None


@pytest.mark.asyncio
async def test_select_200_still_returns_data(client):
    """SUCCESS shape unchanged: 200 returns a list TableResponse."""
    with respx.mock:
        respx.get(f"{FAKE_URL}/rest/v1/candidates").mock(
            return_value=httpx.Response(200, json=[{"id": "1"}, {"id": "2"}])
        )
        result = await client.table("candidates").select("*").execute_async()

    assert result.data == [{"id": "1"}, {"id": "2"}]


@pytest.mark.asyncio
async def test_count_async_200_still_returns_total(client):
    """SUCCESS shape unchanged: count_async parses the content-range total."""
    with respx.mock:
        respx.get(f"{FAKE_URL}/rest/v1/candidates").mock(
            return_value=httpx.Response(
                200, json=[{"id": "1"}], headers={"content-range": "0-0/7"}
            )
        )
        total = await client.table("candidates").select("*").count_async()

    assert total == 7
