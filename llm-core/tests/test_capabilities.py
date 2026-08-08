import asyncio

import pytest

from llm_core import capabilities as capabilities_module
from llm_core.capabilities import CapabilityCache


class FakeClock:
    """A monotonic clock the test drives by hand."""

    def __init__(self, now: float = 1_000.0):
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def clock(monkeypatch):
    fake = FakeClock()
    monkeypatch.setattr(capabilities_module, "_monotonic", fake)
    return fake


def _model_info_payload():
    return {
        "data": [
            {"model_name": "intake-jd", "model_info": {"supports_function_calling": True}},
            {"model_name": "intake-jd-local", "model_info": {"supports_function_calling": False}},
            {"model_name": "mystery", "model_info": {}},
        ]
    }


async def test_reports_support_from_proxy():
    cache = CapabilityCache(http_get=lambda path: _async(_model_info_payload()))

    assert await cache.supports_tools("intake-jd") is True
    assert await cache.supports_tools("intake-jd-local") is False


async def test_missing_flag_defaults_to_supported():
    cache = CapabilityCache(http_get=lambda path: _async(_model_info_payload()))

    assert await cache.supports_tools("mystery") is True


async def test_unknown_alias_defaults_to_supported():
    cache = CapabilityCache(http_get=lambda path: _async(_model_info_payload()))

    assert await cache.supports_tools("never-heard-of-it") is True


async def test_forced_aliases_override_proxy():
    cache = CapabilityCache(
        http_get=lambda path: _async(_model_info_payload()),
        forced_json_aliases=frozenset({"intake-jd"}),
    )

    assert await cache.supports_tools("intake-jd") is False


async def test_proxy_failure_defaults_to_supported_and_does_not_raise():
    async def boom(path):
        raise RuntimeError("proxy down")

    cache = CapabilityCache(http_get=boom)

    assert await cache.supports_tools("intake-jd") is True


async def test_probe_failure_is_not_sticky(clock):
    """The failure backoff must expire. Once it has, the next call probes again."""
    attempts = []

    async def flaky(path):
        attempts.append(path)
        if len(attempts) == 1:
            raise RuntimeError("proxy down")
        return _model_info_payload()

    cache = CapabilityCache(http_get=flaky)

    assert await cache.supports_tools("intake-jd-local") is True
    clock.advance(capabilities_module._FAILURE_BACKOFF_SECONDS + 1)
    assert await cache.supports_tools("intake-jd-local") is False
    assert len(attempts) == 2


async def test_probe_is_not_repeated_inside_the_failure_window(clock):
    """A dead gateway must cost one timeout per window, not one per call."""
    attempts = []

    async def down(path):
        attempts.append(path)
        raise RuntimeError("proxy down")

    cache = CapabilityCache(http_get=down)

    assert await cache.supports_tools("intake-jd-local") is True
    clock.advance(capabilities_module._FAILURE_BACKOFF_SECONDS - 1)
    assert await cache.supports_tools("intake-jd-local") is True
    assert len(attempts) == 1


async def test_concurrent_calls_during_an_outage_probe_once(clock):
    """N callers arriving together must not serialize into N timeouts."""
    attempts = []

    async def slow_and_down(path):
        attempts.append(path)
        await asyncio.sleep(0)
        raise RuntimeError("proxy down")

    cache = CapabilityCache(http_get=slow_and_down)
    results = await asyncio.gather(
        *[cache.supports_tools("intake-jd-local") for _ in range(5)]
    )

    assert results == [True] * 5
    assert len(attempts) == 1


async def test_reset_clears_the_failure_window(clock):
    attempts = []

    async def flaky(path):
        attempts.append(path)
        if len(attempts) == 1:
            raise RuntimeError("proxy down")
        return _model_info_payload()

    cache = CapabilityCache(http_get=flaky)

    assert await cache.supports_tools("intake-jd-local") is True
    cache.reset()
    assert await cache.supports_tools("intake-jd-local") is False
    assert len(attempts) == 2


async def test_quoted_false_is_not_read_as_support():
    payload = {
        "data": [
            {"model_name": "quoted", "model_info": {"supports_function_calling": "false"}},
        ]
    }
    cache = CapabilityCache(http_get=lambda path: _async(payload))

    assert await cache.supports_tools("quoted") is True


async def test_explicit_null_flag_defaults_to_supported():
    payload = {
        "data": [
            {"model_name": "nulled", "model_info": {"supports_function_calling": None}},
        ]
    }
    cache = CapabilityCache(http_get=lambda path: _async(payload))

    assert await cache.supports_tools("nulled") is True


async def test_fetches_once_and_caches():
    calls = []

    async def counting(path):
        calls.append(path)
        return _model_info_payload()

    cache = CapabilityCache(http_get=counting)
    await cache.supports_tools("intake-jd")
    await cache.supports_tools("intake-jd-local")

    assert len(calls) == 1


async def test_concurrent_first_calls_probe_once():
    calls = []

    async def slow(path):
        calls.append(path)
        await asyncio.sleep(0)
        return _model_info_payload()

    cache = CapabilityCache(http_get=slow)
    results = await asyncio.gather(
        cache.supports_tools("intake-jd"),
        cache.supports_tools("intake-jd-local"),
    )

    assert calls == ["/model/info"]
    assert results == [True, False]


async def _async(value):
    return value
