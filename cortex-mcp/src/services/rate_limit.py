"""In-memory token-bucket rate limiter for MCP tool calls.

Two buckets per request:
  * user_id — the authenticated user (1 req/sec sustained by default)
  * org_id  — the organization (10 req/sec sustained by default)

A request that fails either cap is rejected before reaching the tool. The
caller gets a structured message naming the cap that was hit and the
retry-after in seconds so the LLM (or its harness) can back off.

Token bucket semantics:
  - Capacity = `burst` (max instantaneous in-flight).
  - Refill rate = `per_minute / 60` tokens/sec.
  - On each call we refill based on elapsed wall time, then attempt to
    consume one token. If insufficient, we report `retry_after` =
    seconds until enough tokens have refilled.

In-memory, single-process. Good enough for v1 (cortex-mcp runs as one
container today). For multi-replica production you'd swap this for Redis
or memcached — the interface (`check_and_consume`) is designed to be
drop-in replaced.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from threading import Lock
from typing import Final

import structlog

logger = structlog.get_logger(__name__)


# Practical cap on cached buckets so a flood of unique IDs can't exhaust
# process memory. LRU-style eviction is overkill here — we just refuse
# admission once we hit the cap, which fails closed and is the safe choice.
_MAX_KEYS_PER_REGISTRY: Final[int] = 20_000


class RateLimited(Exception):
    """Raised when a caller is over its configured cap. Surfaced to the
    LLM with `retry_after` seconds so it knows how long to back off."""

    def __init__(self, *, scope: str, retry_after: float, message: str | None = None):
        self.scope = scope
        self.retry_after = retry_after
        super().__init__(message or self.default_message())

    def default_message(self) -> str:
        return (
            f"Rate limit reached for {self.scope}. Retry after "
            f"{self.retry_after:.1f} seconds. If you keep hitting this, "
            f"reduce the rate of requests — Cortex MCP caps usage per "
            f"user and per organization to prevent abuse."
        )


@dataclass
class _Bucket:
    capacity: float
    refill_per_sec: float
    tokens: float
    last_touched: float


class _BucketRegistry:
    """Thread-safe map of key → bucket. The `check_and_consume` API is
    intentionally synchronous — token bucket math doesn't need to be async
    and we want it cheap (microseconds, not milliseconds)."""

    def __init__(self, name: str, capacity: int, per_minute: int) -> None:
        self.name = name
        self.capacity = float(capacity)
        self.refill_per_sec = per_minute / 60.0
        self._buckets: dict[str, _Bucket] = {}
        self._lock = Lock()

    def check_and_consume(self, key: str, now: float | None = None) -> tuple[bool, float]:
        """Try to consume one token for `key`.

        Returns (allowed, retry_after_seconds). On allowed=True the caller
        proceeds; on allowed=False the caller must reject with
        RateLimited(retry_after=retry_after).
        """
        ts = time.monotonic() if now is None else now
        with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None:
                if len(self._buckets) >= _MAX_KEYS_PER_REGISTRY:
                    # Cap hit — fail closed. Triggers retry-after but tells
                    # the caller to back off because we have no slot left.
                    logger.warning("rate_limit_registry_full", name=self.name)
                    return False, 60.0
                bucket = _Bucket(
                    capacity=self.capacity,
                    refill_per_sec=self.refill_per_sec,
                    tokens=self.capacity,
                    last_touched=ts,
                )
                self._buckets[key] = bucket

            elapsed = max(0.0, ts - bucket.last_touched)
            bucket.tokens = min(bucket.capacity, bucket.tokens + elapsed * bucket.refill_per_sec)
            bucket.last_touched = ts

            if bucket.tokens >= 1.0:
                bucket.tokens -= 1.0
                return True, 0.0

            deficit = 1.0 - bucket.tokens
            retry_after = deficit / bucket.refill_per_sec if bucket.refill_per_sec > 0 else 60.0
            return False, retry_after

    def reset(self) -> None:
        """Test hook — wipes all buckets."""
        with self._lock:
            self._buckets.clear()


class RateLimiter:
    """Pair of registries (user + org). Inject in `main.py` from the
    settings at startup; share the instance across all middleware calls."""

    def __init__(
        self,
        *,
        user_per_minute: int,
        user_burst: int,
        org_per_minute: int,
        org_burst: int,
    ) -> None:
        self.user = _BucketRegistry("user", user_burst, user_per_minute)
        self.org = _BucketRegistry("org", org_burst, org_per_minute)

    def check(self, *, user_id: str, org_id: str | None) -> None:
        """Consume one token from BOTH buckets. Raises RateLimited on either."""
        allowed_user, retry_user = self.user.check_and_consume(user_id)
        if not allowed_user:
            raise RateLimited(scope=f"user {user_id}", retry_after=retry_user)
        if org_id:
            allowed_org, retry_org = self.org.check_and_consume(org_id)
            if not allowed_org:
                raise RateLimited(scope=f"organization {org_id}", retry_after=retry_org)

    def reset(self) -> None:
        """Test hook."""
        self.user.reset()
        self.org.reset()


def build_from_settings() -> RateLimiter:
    from src.config.settings import get_settings
    s = get_settings()
    return RateLimiter(
        user_per_minute=s.rate_limit_user_per_minute,
        user_burst=s.rate_limit_user_burst,
        org_per_minute=s.rate_limit_org_per_minute,
        org_burst=s.rate_limit_org_burst,
    )
