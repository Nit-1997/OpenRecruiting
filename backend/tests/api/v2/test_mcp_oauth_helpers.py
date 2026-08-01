"""Characterization tests for mcp_oauth helper functions:
_validate_scope, _allowed_audiences, _normalize_audience, _redirect_with_error,
_describe_scope, _load_user_org_context, _load_current_membership,
_load_token_claim_context, _validate_authorize_params.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest

from app.api.v2.routers import mcp_oauth as mo
from app.dependencies import CurrentUser

USER_ID = "11111111-1111-1111-1111-111111111111"
ORG_ID = "22222222-2222-2222-2222-222222222222"


def _settings(auds="cortex-mcp,http://localhost:8020/"):
    return SimpleNamespace(MCP_ALLOWED_AUDIENCES=auds)


# ----------------------- _validate_scope -----------------------

def test_validate_scope_empty_ok():
    assert mo._validate_scope("") is None
    assert mo._validate_scope("   ") is None


def test_validate_scope_allowed():
    assert mo._validate_scope("cortex:read") is None


def test_validate_scope_rejects_unknown():
    err = mo._validate_scope("cortex:write")
    assert err is not None and "not enabled" in err


# ----------------------- _allowed_audiences / _normalize_audience -----------------------

def test_allowed_audiences_strips_slashes():
    with patch.object(mo, "get_settings", _settings):
        auds = mo._allowed_audiences()
    assert "cortex-mcp" in auds
    assert "http://localhost:8020" in auds  # trailing slash stripped


def test_normalize_audience_default():
    with patch.object(mo, "get_settings", _settings):
        out = mo._normalize_audience(None)
    assert out  # one of the allowed


def test_normalize_audience_strips_slash():
    assert mo._normalize_audience("https://x/") == "https://x"


# ----------------------- _redirect_with_error -----------------------

def test_redirect_with_error_adds_query():
    resp = mo._redirect_with_error("https://app/cb", "invalid_request", "bad", "st1")
    loc = resp.headers["location"]
    assert "error=invalid_request" in loc
    assert "state=st1" in loc
    assert loc.count("?") == 1


def test_redirect_with_error_existing_query_uses_amp():
    resp = mo._redirect_with_error("https://app/cb?foo=1", "x", "y", "")
    assert "?foo=1&error=x" in resp.headers["location"]


# ----------------------- _describe_scope -----------------------

def test_describe_scope_known_and_unknown():
    assert "graph" in mo._describe_scope("cortex:read")
    assert mo._describe_scope("custom:scope") == "custom:scope"


# ----------------------- _load_user_org_context -----------------------

@pytest.mark.asyncio
async def test_load_user_org_context_no_org():
    user = CurrentUser(id=UUID(USER_ID), email="u@m.ai", is_staff=False, organization_id=None)
    org_id, org_name, email = await mo._load_user_org_context(user)
    assert org_id is None
    assert org_name == "OpenRecruiting"
    assert email == "u@m.ai"


@pytest.mark.asyncio
async def test_load_user_org_context_with_org():
    user = CurrentUser(id=UUID(USER_ID), email="u@m.ai", is_staff=False, organization_id=UUID(ORG_ID))
    sb = MagicMock()
    builder = MagicMock()
    for attr in ("select", "eq", "single"):
        setattr(builder, attr, MagicMock(return_value=builder))
    builder.execute_async = AsyncMock(return_value=MagicMock(data={"name": "Acme"}))
    sb.table.return_value = builder
    with patch("app.services.supabase.get_supabase_admin_client", return_value=sb):
        org_id, org_name, email = await mo._load_user_org_context(user)
    assert org_name == "Acme"


# ----------------------- _load_current_membership -----------------------

def _profile_supabase(data):
    sb = MagicMock()
    builder = MagicMock()
    for attr in ("select", "eq", "single"):
        setattr(builder, attr, MagicMock(return_value=builder))
    builder.execute_async = AsyncMock(return_value=MagicMock(data=data))
    sb.table.return_value = builder
    return sb


@pytest.mark.asyncio
async def test_load_current_membership_missing_profile():
    sb = _profile_supabase(None)
    with patch("app.services.supabase.get_supabase_admin_client", return_value=sb):
        assert (await mo._load_current_membership(USER_ID)) is None


@pytest.mark.asyncio
async def test_load_current_membership_soft_deleted():
    sb = _profile_supabase({"organization_id": ORG_ID, "deleted_at": "2025-01-01T00:00:00Z"})
    with patch("app.services.supabase.get_supabase_admin_client", return_value=sb):
        assert (await mo._load_current_membership(USER_ID)) is None


@pytest.mark.asyncio
async def test_load_current_membership_active():
    sb = _profile_supabase({"organization_id": ORG_ID, "deleted_at": None})
    with patch("app.services.supabase.get_supabase_admin_client", return_value=sb):
        m = await mo._load_current_membership(USER_ID)
    assert m.org_id == ORG_ID


# ----------------------- _load_token_claim_context -----------------------

@pytest.mark.asyncio
async def test_load_token_claim_context_with_org():
    sb = MagicMock()

    def table(name):
        builder = MagicMock()
        for attr in ("select", "eq", "single"):
            setattr(builder, attr, MagicMock(return_value=builder))
        if name == "profiles":
            builder.execute_async = AsyncMock(return_value=MagicMock(data={"full_name": "Alice"}))
        else:
            builder.execute_async = AsyncMock(return_value=MagicMock(data={"name": "Acme"}))
        return builder

    sb.table = MagicMock(side_effect=table)
    with patch("app.services.supabase.get_supabase_admin_client", return_value=sb):
        org_name, user_name, role = await mo._load_token_claim_context(USER_ID, ORG_ID)
    assert org_name == "Acme"
    assert user_name == "Alice"
    # `profiles` has no `role` column, so _load_token_claim_context deliberately
    # returns None instead of selecting it (selecting it was a 42703 -> 500 on
    # token exchange). jwt_signer omits the claim entirely when it is None.
    assert role is None


# ----------------------- _validate_authorize_params -----------------------

@pytest.mark.asyncio
async def test_validate_authorize_params_rejects_non_s256():
    out = await mo._validate_authorize_params(
        client_id="c1", redirect_uri="https://a/cb", code_challenge="x",
        code_challenge_method="plain", scope="cortex:read", audience="cortex-mcp",
    )
    assert out is not None  # JSONResponse error


@pytest.mark.asyncio
async def test_validate_authorize_params_unknown_client():
    with patch.object(mo.client_store, "get_client", AsyncMock(return_value=None)):
        out = await mo._validate_authorize_params(
            client_id="c1", redirect_uri="https://a/cb", code_challenge="ch",
            code_challenge_method="S256", scope="cortex:read", audience="cortex-mcp",
        )
    assert out is not None
    assert out.status_code == 401
