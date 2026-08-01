import time
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import jwt
from jwt.exceptions import InvalidTokenError as JWTError
from app.config import get_settings
from app.services.supabase import get_supabase_admin_client, get_async_http_client
from uuid import UUID
from dataclasses import dataclass
from typing import Optional
from collections import OrderedDict
import threading


security = HTTPBearer()


@dataclass
class CurrentUser:
    id: UUID
    email: str
    is_staff: bool
    organization_id: UUID | None = None


class ProfileCache:
    def __init__(self, max_size: int = 1000, ttl_seconds: int = 60):
        self.max_size = max_size
        self.ttl_seconds = ttl_seconds
        self._cache: OrderedDict[str, tuple[dict, float]] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, user_id: str) -> Optional[dict]:
        with self._lock:
            if user_id not in self._cache:
                return None
            profile, timestamp = self._cache[user_id]
            if time.time() - timestamp > self.ttl_seconds:
                del self._cache[user_id]
                return None
            self._cache.move_to_end(user_id)
            return profile

    def set(self, user_id: str, profile: dict) -> None:
        with self._lock:
            if user_id in self._cache:
                del self._cache[user_id]
            elif len(self._cache) >= self.max_size:
                self._cache.popitem(last=False)
            self._cache[user_id] = (profile, time.time())

    def invalidate(self, user_id: str) -> None:
        with self._lock:
            if user_id in self._cache:
                del self._cache[user_id]


_profile_cache = ProfileCache(max_size=1000, ttl_seconds=300)


class JWKSClient:
    def __init__(self, jwks_url: str, cache_ttl: int = 3600):
        self.jwks_url = jwks_url
        self.cache_ttl = cache_ttl
        self._jwks_cache: dict | None = None
        self._cache_time: float = 0

    async def get_jwks(self) -> dict:
        if self._jwks_cache and (time.time() - self._cache_time) < self.cache_ttl:
            return self._jwks_cache

        client = get_async_http_client()
        response = await client.get(self.jwks_url)
        if response.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to fetch JWKS",
            )
        self._jwks_cache = response.json()
        self._cache_time = time.time()
        return self._jwks_cache

    async def get_key(self, kid: str) -> dict | None:
        jwks = await self.get_jwks()
        for key in jwks.get("keys", []):
            if key.get("kid") == kid:
                return key
        return None


_jwks_client: JWKSClient | None = None


def get_jwks_client() -> JWKSClient:
    global _jwks_client
    if _jwks_client is None:
        settings = get_settings()
        _jwks_client = JWKSClient(f"{settings.SUPABASE_URL}/auth/v1/.well-known/jwks.json")
    return _jwks_client


async def _decode_supabase_jwt(token: str) -> dict:
    """Verify a Supabase access token and return its claims.

    Handles both signing schemes Supabase emits: ES256 (asymmetric, JWKS-backed,
    keyed by `kid`) and HS256 (the shared `SUPABASE_JWT_SECRET`). Any verification
    failure surfaces as a 401 — identical to the prior inline blocks in
    `get_current_user` / `get_authenticated_user_id`.
    """
    try:
        unverified_header = jwt.get_unverified_header(token)
        alg = unverified_header.get("alg", "HS256")
        kid = unverified_header.get("kid")

        if alg == "ES256" and kid:
            jwks_client = get_jwks_client()
            jwk = await jwks_client.get_key(kid)
            if not jwk:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Unknown signing key",
                )
            public_key = jwt.algorithms.ECAlgorithm.from_jwk(jwk)
            return jwt.decode(
                token,
                public_key,
                algorithms=["ES256"],
                audience="authenticated",
            )

        settings = get_settings()
        return jwt.decode(
            token,
            settings.SUPABASE_JWT_SECRET,
            algorithms=["HS256"],
            audience="authenticated",
        )
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
        )


async def get_authenticated_user_id(
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> str:
    payload = await _decode_supabase_jwt(credentials.credentials)
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    return user_id


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> CurrentUser:
    payload = await _decode_supabase_jwt(credentials.credentials)

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token"
        )

    cached_profile = _profile_cache.get(user_id)
    if cached_profile:
        return CurrentUser(
            id=UUID(user_id),
            email=cached_profile["email"],
            is_staff=cached_profile.get("is_staff", False),
            organization_id=UUID(cached_profile["organization_id"]) if cached_profile.get("organization_id") else None
        )

    supabase = get_supabase_admin_client()
    result = await supabase.table("profiles").select("*").eq("id", user_id).single().execute_async()

    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found"
        )

    profile = result.data
    _profile_cache.set(user_id, profile)

    return CurrentUser(
        id=UUID(user_id),
        email=profile["email"],
        is_staff=profile.get("is_staff", False),
        organization_id=UUID(profile["organization_id"]) if profile.get("organization_id") else None
    )


async def require_staff(
    current_user: CurrentUser = Depends(get_current_user)
) -> CurrentUser:
    if not current_user.is_staff:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Staff access required"
        )
    return current_user


def invalidate_profile_cache(user_id: str) -> None:
    _profile_cache.invalidate(user_id)


# Anthropic async client — singleton at app scope.
# FastAPI/uvicorn runs a single event loop for the lifetime of the process,
# so a module-level AsyncAnthropic instance is safe here.

import os as _os
from anthropic import AsyncAnthropic as _AsyncAnthropic

_anthropic_client: "_AsyncAnthropic | None" = None


def get_anthropic_async_client() -> "_AsyncAnthropic":
    """FastAPI dependency that returns a process-scoped AsyncAnthropic client."""
    global _anthropic_client
    if _anthropic_client is None:
        api_key = _os.environ["ANTHROPIC_API_KEY"]
        _anthropic_client = _AsyncAnthropic(api_key=api_key, max_retries=2)
    return _anthropic_client
