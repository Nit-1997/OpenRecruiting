"""Characterization tests for the MCP OAuth persistence layers:
client_store (DCR) and refresh_store (rotation)."""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.mcp import client_store, refresh_store
from app.services.mcp.client_store import (
    OAuthClient,
    register_client,
    validate_redirect_uri,
)


def _insert_supabase():
    sb = MagicMock()
    builder = MagicMock()
    for attr in ("insert", "select", "update", "eq", "single", "gt"):
        setattr(builder, attr, MagicMock(return_value=builder))
    builder.execute_async = AsyncMock(return_value=MagicMock(data=[{}]))
    sb.table = MagicMock(return_value=builder)
    return sb, builder


# ----------------------- client_store.register_client -----------------------

@pytest.mark.asyncio
async def test_register_client_happy_path():
    sb, builder = _insert_supabase()
    with patch.object(client_store, "get_supabase_admin_client", return_value=sb):
        client = await register_client(
            client_name="Claude", redirect_uris=["https://claude.ai/cb"],
        )
    assert isinstance(client, OAuthClient)
    assert client.client_id.startswith("mcp_")
    assert client.scope == "cortex:read"
    builder.insert.assert_called_once()


@pytest.mark.asyncio
async def test_register_client_no_redirect_uri_raises():
    with pytest.raises(ValueError, match="At least one redirect_uri"):
        await register_client(client_name="x", redirect_uris=[])


@pytest.mark.asyncio
async def test_register_client_bad_scheme_raises():
    with pytest.raises(ValueError, match="must be https"):
        await register_client(client_name="x", redirect_uris=["ftp://evil"])


@pytest.mark.asyncio
async def test_register_client_localhost_allowed():
    sb, _ = _insert_supabase()
    with patch.object(client_store, "get_supabase_admin_client", return_value=sb):
        client = await register_client(client_name="x", redirect_uris=["http://localhost:8000/cb"])
    assert client.client_id


@pytest.mark.asyncio
async def test_register_client_bad_grant_raises():
    with pytest.raises(ValueError, match="grant_types"):
        await register_client(
            client_name="x", redirect_uris=["https://a/cb"], grant_types=["password"]
        )


@pytest.mark.asyncio
async def test_register_client_bad_response_raises():
    with pytest.raises(ValueError, match="response_types"):
        await register_client(
            client_name="x", redirect_uris=["https://a/cb"], response_types=["token"]
        )


@pytest.mark.asyncio
async def test_register_client_bad_auth_method_raises():
    with pytest.raises(ValueError, match="token_endpoint_auth_method"):
        await register_client(
            client_name="x", redirect_uris=["https://a/cb"],
            token_endpoint_auth_method="client_secret_post",
        )


# ----------------------- client_store.get_client -----------------------

@pytest.mark.asyncio
async def test_get_client_found():
    sb = MagicMock()
    builder = MagicMock()
    for attr in ("select", "eq", "single"):
        setattr(builder, attr, MagicMock(return_value=builder))
    builder.execute_async = AsyncMock(return_value=MagicMock(data={
        "client_id": "c1", "redirect_uris": ["https://a/cb"],
        "grant_types": ["authorization_code"], "response_types": ["code"],
    }))
    sb.table = MagicMock(return_value=builder)
    with patch.object(client_store, "get_supabase_admin_client", return_value=sb):
        client = await client_store.get_client("c1")
    assert client.client_id == "c1"


@pytest.mark.asyncio
async def test_get_client_missing():
    sb = MagicMock()
    builder = MagicMock()
    for attr in ("select", "eq", "single"):
        setattr(builder, attr, MagicMock(return_value=builder))
    builder.execute_async = AsyncMock(return_value=MagicMock(data=None))
    sb.table = MagicMock(return_value=builder)
    with patch.object(client_store, "get_supabase_admin_client", return_value=sb):
        assert (await client_store.get_client("c1")) is None


def test_validate_redirect_uri_exact_match():
    c = OAuthClient("c1", None, ["https://a/cb"], ["authorization_code"], ["code"], "none", "cortex:read")
    assert validate_redirect_uri(c, "https://a/cb") is True
    assert validate_redirect_uri(c, "https://a/other") is False


# ----------------------- refresh_store -----------------------

@pytest.mark.asyncio
async def test_issue_refresh_token():
    sb, builder = _insert_supabase()
    with patch.object(refresh_store, "get_supabase_admin_client", return_value=sb):
        rt = await refresh_store.issue_refresh_token(
            client_id="c1", user_id="u1", organization_id="o1",
            scope="cortex:read", audience="cortex-mcp",
        )
    assert rt.token  # plaintext returned
    assert rt.token_hash == refresh_store._hash(rt.token)
    assert rt.client_id == "c1"
    builder.insert.assert_called_once()


@pytest.mark.asyncio
async def test_use_refresh_token_rotates():
    expires = (datetime.now(timezone.utc) + timedelta(days=10)).isoformat()
    sb = MagicMock()
    builder = MagicMock()
    for attr in ("update", "eq", "gt"):
        setattr(builder, attr, MagicMock(return_value=builder))
    builder.execute_async = AsyncMock(return_value=MagicMock(data=[{
        "client_id": "c1", "user_id": "u1", "organization_id": "o1",
        "scope": "cortex:read", "audience": "cortex-mcp", "expires_at": expires,
    }]))
    sb.table = MagicMock(return_value=builder)
    with patch.object(refresh_store, "get_supabase_admin_client", return_value=sb):
        rt = await refresh_store.use_refresh_token("plaintext-tok", client_id="c1")
    assert rt is not None
    assert rt.user_id == "u1"


@pytest.mark.asyncio
async def test_use_refresh_token_no_row_returns_none():
    sb = MagicMock()
    builder = MagicMock()
    for attr in ("update", "eq", "gt"):
        setattr(builder, attr, MagicMock(return_value=builder))
    builder.execute_async = AsyncMock(return_value=MagicMock(data=[]))
    sb.table = MagicMock(return_value=builder)
    with patch.object(refresh_store, "get_supabase_admin_client", return_value=sb):
        assert (await refresh_store.use_refresh_token("tok", client_id="c1")) is None


@pytest.mark.asyncio
async def test_revoke_refresh_token():
    sb = MagicMock()
    builder = MagicMock()
    for attr in ("update", "eq"):
        setattr(builder, attr, MagicMock(return_value=builder))
    builder.execute_async = AsyncMock(return_value=MagicMock(data=[{"id": "r1"}]))
    sb.table = MagicMock(return_value=builder)
    with patch.object(refresh_store, "get_supabase_admin_client", return_value=sb):
        assert (await refresh_store.revoke_refresh_token("tok")) is True


def test_parse_ts_z_suffix():
    out = refresh_store._parse_ts("2025-01-01T00:00:00Z")
    assert out.tzinfo is not None
