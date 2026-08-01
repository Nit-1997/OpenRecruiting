"""Tests for the in-memory token-bucket rate limiter.

Focus on observable behavior:
  * Bursts up to `burst` succeed back-to-back.
  * Sustained requests over `per_minute` get rejected with a useful retry_after.
  * User and org caps are independent — hitting one doesn't burn the other.
  * The "retry_after" returned matches what the LLM should actually wait.
"""
from __future__ import annotations

import time

import pytest

from src.services.rate_limit import RateLimited, RateLimiter, _BucketRegistry


def test_burst_up_to_capacity_allowed():
    reg = _BucketRegistry("test", capacity=5, per_minute=60)
    # First 5 in rapid succession should pass; the 6th must reject.
    for _ in range(5):
        allowed, _ = reg.check_and_consume("u1")
        assert allowed
    allowed, retry = reg.check_and_consume("u1")
    assert not allowed
    assert retry > 0


def test_retry_after_matches_refill_rate():
    # 60/min → 1 token/sec refill. After exhausting a 5-token bucket the
    # next request should report retry_after ≈ 1.0 seconds.
    reg = _BucketRegistry("test", capacity=5, per_minute=60)
    for _ in range(5):
        reg.check_and_consume("u1")
    allowed, retry = reg.check_and_consume("u1")
    assert not allowed
    assert 0.5 <= retry <= 1.5  # within ~50% slop for clock noise


def test_refill_recovers_capacity():
    """Two tokens in, sleep for >2/refill_rate, two more tokens consumable."""
    reg = _BucketRegistry("test", capacity=2, per_minute=120)  # 2/sec refill
    assert reg.check_and_consume("u1")[0]
    assert reg.check_and_consume("u1")[0]
    assert not reg.check_and_consume("u1")[0]
    # Sleep enough for the bucket to refill to capacity.
    time.sleep(1.2)
    assert reg.check_and_consume("u1")[0]


def test_different_keys_independent():
    reg = _BucketRegistry("test", capacity=2, per_minute=60)
    reg.check_and_consume("u1")
    reg.check_and_consume("u1")
    # u1 is now empty, but u2 still has full capacity.
    assert reg.check_and_consume("u2")[0]
    assert reg.check_and_consume("u2")[0]


def test_user_and_org_buckets_independent():
    """A heavy user should not get throttled by an org bucket they belong
    to (unless the org bucket itself is exhausted), and vice versa."""
    limiter = RateLimiter(
        user_per_minute=60, user_burst=2,
        org_per_minute=600, org_burst=10,
    )
    # First two by user-1 consume user bucket; org has 8 remaining.
    limiter.check(user_id="u1", org_id="org-A")
    limiter.check(user_id="u1", org_id="org-A")
    # Third by user-1 should fail on the USER cap, not org cap.
    with pytest.raises(RateLimited) as exc:
        limiter.check(user_id="u1", org_id="org-A")
    assert "user u1" in str(exc.value)
    # Different user in same org succeeds — burns org bucket but user is fresh.
    limiter.check(user_id="u2", org_id="org-A")


def test_org_cap_blocks_when_user_still_has_quota():
    limiter = RateLimiter(
        user_per_minute=600, user_burst=100,
        org_per_minute=60, org_burst=2,
    )
    limiter.check(user_id="u1", org_id="org-A")
    limiter.check(user_id="u2", org_id="org-A")
    with pytest.raises(RateLimited) as exc:
        limiter.check(user_id="u3", org_id="org-A")
    assert "organization org-A" in str(exc.value)


def test_missing_org_id_skips_org_check():
    """Internal/service tokens that have no org should not be blocked by
    the org bucket. They still pay the user cap."""
    limiter = RateLimiter(
        user_per_minute=60, user_burst=10,
        org_per_minute=1, org_burst=1,  # extreme org cap
    )
    # Even with the org cap at 1, multiple no-org calls should succeed.
    for _ in range(5):
        limiter.check(user_id="service", org_id=None)


def test_rate_limited_message_is_actionable():
    """The error message must tell the LLM what to do."""
    err = RateLimited(scope="user u1", retry_after=2.5)
    msg = str(err)
    assert "Retry after" in msg
    assert "2.5" in msg
    assert "user u1" in msg


def test_reset_clears_state():
    limiter = RateLimiter(user_per_minute=60, user_burst=1,
                          org_per_minute=60, org_burst=1)
    limiter.check(user_id="u1", org_id="org-A")
    with pytest.raises(RateLimited):
        limiter.check(user_id="u1", org_id="org-A")
    limiter.reset()
    limiter.check(user_id="u1", org_id="org-A")  # should not raise


def test_registry_cap_fails_closed():
    """A flood of unique keys must not exhaust process memory; once the
    cap is hit, new keys are denied."""
    from src.services import rate_limit as rl_module

    reg = _BucketRegistry("test", capacity=10, per_minute=60)
    # Inject far fewer keys than the production cap to keep this fast.
    original = rl_module._MAX_KEYS_PER_REGISTRY
    rl_module._MAX_KEYS_PER_REGISTRY = 100
    try:
        for i in range(100):
            allowed, _ = reg.check_and_consume(f"k{i}")
            assert allowed
        allowed, retry = reg.check_and_consume("k101")
        assert not allowed
        assert retry > 0
    finally:
        rl_module._MAX_KEYS_PER_REGISTRY = original
