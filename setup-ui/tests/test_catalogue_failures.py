"""A catalogue outage must not be able to read as a fact about the provider.

The negative cache stored `(expiry, {})` in the same slot a success uses, so
only the FIRST call in each 30s window raised. Everything after it got an empty
dict and treated it as a real answer: the picker rendered "0 models can call
tools", the probe ran without the model's quirks, and — worst — a save rendered
litellm-config.yaml with no `reasoning` settings, which is precisely the
empty-reply failure quirks.py exists to prevent.
"""

from __future__ import annotations

import httpx
import pytest

from app import catalogue

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _clear_cache():
    catalogue.reset()
    yield
    catalogue.reset()


@pytest.fixture
def failing(monkeypatch):
    async def boom(self, *a, **k):
        raise httpx.ConnectError("network down")

    monkeypatch.setattr(httpx.AsyncClient, "get", boom)


async def test_every_call_in_the_failure_window_raises_not_just_the_first(failing):
    for attempt in range(3):
        with pytest.raises(catalogue.CatalogueError):
            await catalogue.fetch("openrouter")


async def test_the_cached_failure_keeps_its_message(failing):
    with pytest.raises(catalogue.CatalogueError) as first:
        await catalogue.fetch("openrouter")
    with pytest.raises(catalogue.CatalogueError) as cached:
        await catalogue.fetch("openrouter")
    assert str(cached.value) == str(first.value)
    assert "OpenRouter" in str(cached.value)


async def test_the_failure_is_only_fetched_once_per_window(monkeypatch):
    """The negative cache still has to do its job — a type-ahead must not retry
    per keystroke."""
    calls = 0

    async def boom(self, *a, **k):
        nonlocal calls
        calls += 1
        raise httpx.ConnectError("network down")

    monkeypatch.setattr(httpx.AsyncClient, "get", boom)
    for _ in range(5):
        with pytest.raises(catalogue.CatalogueError):
            await catalogue.fetch("openrouter")
    assert calls == 1


async def test_a_provider_with_no_catalogue_returns_empty_without_raising():
    """The other half of the distinction: {} is a legitimate answer meaning
    'publishes no catalogue', and must NOT be conflated with a failure."""
    assert await catalogue.fetch("anthropic") == {}
