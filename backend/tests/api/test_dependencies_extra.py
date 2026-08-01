"""Characterization tests for the uncovered parts of app/dependencies.py:
ProfileCache (LRU + TTL), JWKSClient caching, get_current_user (cache hit /
DB fetch / not-found), require_staff, invalidate_profile_cache,
get_jwks_client singleton, and get_anthropic_async_client.
"""

import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import httpx
import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

import app.dependencies as deps
from app.dependencies import (
    CurrentUser,
    JWKSClient,
    ProfileCache,
    get_current_user,
    invalidate_profile_cache,
    require_staff,
)

USER_ID = "11111111-1111-1111-1111-111111111111"
ORG_ID = "22222222-2222-2222-2222-222222222222"


# ----------------------- ProfileCache -----------------------

def test_profile_cache_set_get():
    cache = ProfileCache(max_size=2, ttl_seconds=60)
    cache.set("u1", {"email": "a@b.com"})
    assert cache.get("u1") == {"email": "a@b.com"}
    assert cache.get("missing") is None


def test_profile_cache_ttl_expiry():
    cache = ProfileCache(max_size=2, ttl_seconds=60)
    cache.set("u1", {"email": "a@b.com"})
    with patch.object(deps.time, "time", return_value=time.time() + 1000):
        assert cache.get("u1") is None  # expired -> evicted


def test_profile_cache_lru_eviction():
    cache = ProfileCache(max_size=2, ttl_seconds=60)
    cache.set("u1", {"e": 1})
    cache.set("u2", {"e": 2})
    cache.set("u3", {"e": 3})  # evicts oldest (u1)
    assert cache.get("u1") is None
    assert cache.get("u2") == {"e": 2}
    assert cache.get("u3") == {"e": 3}


def test_profile_cache_reset_moves_to_end():
    cache = ProfileCache(max_size=2, ttl_seconds=60)
    cache.set("u1", {"e": 1})
    cache.set("u1", {"e": 9})  # overwrite existing
    assert cache.get("u1") == {"e": 9}


def test_profile_cache_invalidate():
    cache = ProfileCache(max_size=2, ttl_seconds=60)
    cache.set("u1", {"e": 1})
    cache.invalidate("u1")
    assert cache.get("u1") is None
    cache.invalidate("never-existed")  # no error


def test_invalidate_profile_cache_module_helper():
    deps._profile_cache.set("ux", {"email": "x@y.com"})
    invalidate_profile_cache("ux")
    assert deps._profile_cache.get("ux") is None


# ----------------------- JWKSClient -----------------------

@pytest.mark.asyncio
async def test_jwks_client_fetches_and_caches():
    client = JWKSClient("https://auth.test/jwks.json", cache_ttl=3600)
    http = MagicMock()
    http.get = AsyncMock(return_value=httpx.Response(200, json={"keys": [{"kid": "k1"}]}))
    with patch.object(deps, "get_async_http_client", return_value=http):
        first = await client.get_jwks()
        second = await client.get_jwks()  # cached, no second fetch
    assert first == {"keys": [{"kid": "k1"}]}
    http.get.assert_awaited_once()


@pytest.mark.asyncio
async def test_jwks_client_fetch_error_raises_500():
    client = JWKSClient("https://auth.test/jwks.json")
    http = MagicMock()
    http.get = AsyncMock(return_value=httpx.Response(503))
    with patch.object(deps, "get_async_http_client", return_value=http):
        with pytest.raises(HTTPException) as exc:
            await client.get_jwks()
    assert exc.value.status_code == 500


@pytest.mark.asyncio
async def test_jwks_client_get_key_match_and_miss():
    client = JWKSClient("https://auth.test/jwks.json")
    client._jwks_cache = {"keys": [{"kid": "k1", "x": 1}]}
    client._cache_time = time.time()
    assert (await client.get_key("k1")) == {"kid": "k1", "x": 1}
    assert (await client.get_key("nope")) is None


def test_get_jwks_client_singleton():
    deps._jwks_client = None
    a = deps.get_jwks_client()
    b = deps.get_jwks_client()
    assert a is b


# ----------------------- get_current_user -----------------------

def _creds():
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials="tok")


@pytest.mark.asyncio
async def test_get_current_user_cache_hit():
    deps._profile_cache.set(USER_ID, {
        "email": "c@d.com", "is_staff": True, "organization_id": ORG_ID,
    })
    with patch.object(deps, "_decode_supabase_jwt", AsyncMock(return_value={"sub": USER_ID})):
        user = await get_current_user(_creds())
    assert user.id == UUID(USER_ID)
    assert user.is_staff is True
    assert user.organization_id == UUID(ORG_ID)
    deps._profile_cache.invalidate(USER_ID)


@pytest.mark.asyncio
async def test_get_current_user_db_fetch_then_caches():
    deps._profile_cache.invalidate(USER_ID)
    sb = MagicMock()
    builder = MagicMock()
    for attr in ("select", "eq", "single"):
        setattr(builder, attr, MagicMock(return_value=builder))
    builder.execute_async = AsyncMock(return_value=MagicMock(data={
        "email": "db@d.com", "is_staff": False, "organization_id": None,
    }))
    sb.table = MagicMock(return_value=builder)
    with patch.object(deps, "_decode_supabase_jwt", AsyncMock(return_value={"sub": USER_ID})), \
         patch.object(deps, "get_supabase_admin_client", return_value=sb):
        user = await get_current_user(_creds())
    assert user.email == "db@d.com"
    assert user.organization_id is None
    assert deps._profile_cache.get(USER_ID) is not None
    deps._profile_cache.invalidate(USER_ID)


@pytest.mark.asyncio
async def test_get_current_user_no_sub_401():
    with patch.object(deps, "_decode_supabase_jwt", AsyncMock(return_value={})):
        with pytest.raises(HTTPException) as exc:
            await get_current_user(_creds())
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_get_current_user_profile_not_found_401():
    deps._profile_cache.invalidate(USER_ID)
    sb = MagicMock()
    builder = MagicMock()
    for attr in ("select", "eq", "single"):
        setattr(builder, attr, MagicMock(return_value=builder))
    builder.execute_async = AsyncMock(return_value=MagicMock(data=None))
    sb.table = MagicMock(return_value=builder)
    with patch.object(deps, "_decode_supabase_jwt", AsyncMock(return_value={"sub": USER_ID})), \
         patch.object(deps, "get_supabase_admin_client", return_value=sb):
        with pytest.raises(HTTPException) as exc:
            await get_current_user(_creds())
    assert exc.value.status_code == 401


# ----------------------- require_staff -----------------------

@pytest.mark.asyncio
async def test_require_staff_allows_staff():
    staff = CurrentUser(id=UUID(USER_ID), email="s@m.ai", is_staff=True)
    assert await require_staff(staff) is staff


@pytest.mark.asyncio
async def test_require_staff_rejects_non_staff():
    user = CurrentUser(id=UUID(USER_ID), email="u@m.ai", is_staff=False)
    with pytest.raises(HTTPException) as exc:
        await require_staff(user)
    assert exc.value.status_code == 403


# ----------------------- get_anthropic_async_client -----------------------

def test_get_anthropic_async_client_singleton():
    deps._anthropic_client = None
    fake = object()
    with patch.object(deps, "_AsyncAnthropic", return_value=fake):
        a = deps.get_anthropic_async_client()
        b = deps.get_anthropic_async_client()
    assert a is b is fake
    deps._anthropic_client = None
