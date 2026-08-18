"""The list of models a provider offers, and what each one can do.

Only OpenRouter publishes this. Its `/api/v1/models` returns ~400 entries with a
`supported_parameters` array and a `reasoning` object per model, which is what
makes "pick any model" safe to offer rather than a coin flip: both quirk
derivation and the capability flag are lookups against it.

Cached in memory, because the catalogue backs a type-ahead over 400 models and
re-fetching 700KB per keystroke would be absurd. A failed fetch is cached only
briefly, so an outage neither pins an empty list in place for the process
lifetime nor charges every keystroke a fresh timeout — the same shape
llm-core/capabilities.py uses, for the same reason.

NO KEY IS SENT. The catalogue is public. Fetching it authenticated would put a
provider credential in this process's outbound traffic for no benefit.
"""

from __future__ import annotations

import time
from typing import Any

import httpx

from app.providers import PROVIDERS

_TTL_SECONDS = 600.0
_FAILURE_TTL_SECONDS = 30.0
_TIMEOUT = httpx.Timeout(20.0, connect=5.0)

#: provider -> (expires_at, models, error). `models` is None when the last fetch
#: FAILED, and that distinction is load-bearing: an empty dict is a legitimate
#: answer meaning "this provider publishes no catalogue", so caching a failure as
#: {} made every call after the first one report success with zero models. The
#: caller then derived quirks from nothing — silently dropping the reasoning
#: settings that quirks.py exists to emit — and the model picker rendered "0
#: models" instead of the reason. A failure stays a failure for its whole TTL.
_cache: dict[str, tuple[float, dict[str, dict[str, Any]] | None, str]] = {}


class CatalogueError(Exception):
    """The model list could not be fetched. Safe to show."""


def _fresh(provider_id: str) -> tuple[dict[str, dict[str, Any]] | None, str] | None:
    """The cached outcome, or None when there is nothing usable cached.

    Returns a (models, error) pair so a cached FAILURE is distinguishable from a
    cached empty catalogue. None as the outer value means "nothing cached";
    None as `models` means "the cached outcome was a failure".
    """
    hit = _cache.get(provider_id)
    if not hit:
        return None
    expires, value, error = hit
    if time.monotonic() >= expires:
        return None
    return value, error


def reset() -> None:
    _cache.clear()


async def fetch(provider_id: str) -> dict[str, dict[str, Any]]:
    """Model id -> metadata for one provider, keyed as `<provider>/<model id>`.

    An empty dict means "this provider publishes no catalogue", which is a normal
    answer, not a failure: Anthropic, OpenAI and Ollama all fall back to the
    provider-level capability constant in quirks.derive.
    """
    spec = PROVIDERS.get(provider_id)
    if spec is None:
        raise CatalogueError(f"Unknown provider '{provider_id}'.")
    if not spec.catalogue_url:
        return {}

    cached = _fresh(provider_id)
    if cached is not None:
        value, error = cached
        # A cached failure re-raises rather than returning {}. Returning the empty
        # dict here is what let a 30-second outage read as "this provider offers
        # no models" everywhere downstream.
        if value is None:
            raise CatalogueError(error)
        return value

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(spec.catalogue_url)
            resp.raise_for_status()
            payload = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        # Negative-cache so a type-ahead does not retry per keystroke. Cached as
        # a FAILURE, not as an empty catalogue — see the note on _cache.
        message = f"Could not fetch the {spec.label} model list: {exc}"
        _cache[provider_id] = (time.monotonic() + _FAILURE_TTL_SECONDS, None, message)
        raise CatalogueError(message) from exc

    models: dict[str, dict[str, Any]] = {}
    for item in payload.get("data") or []:
        model_id = item.get("id")
        if isinstance(model_id, str) and model_id:
            models[f"{provider_id}/{model_id}"] = item

    _cache[provider_id] = (time.monotonic() + _TTL_SECONDS, models, "")
    return models


def summarise(provider_id: str, models: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Catalogue entries reduced to what the picker shows.

    `tools` is the field that matters most: binding a workload that streams AND
    sends tools to a model without native function calling does not degrade it,
    it breaks it, because emulated tools and streaming do not compose.
    """
    out: list[dict[str, Any]] = []
    prefix = f"{provider_id}/"
    for key, item in models.items():
        model_id = key[len(prefix):] if key.startswith(prefix) else key
        pricing = item.get("pricing") or {}
        reasoning = item.get("reasoning") or {}
        params = item.get("supported_parameters") or []
        try:
            prompt_cost = float(pricing.get("prompt") or 0) * 1_000_000
            completion_cost = float(pricing.get("completion") or 0) * 1_000_000
        except (TypeError, ValueError):
            prompt_cost = completion_cost = 0.0
        out.append(
            {
                "id": model_id,
                "name": item.get("name") or model_id,
                "context_length": item.get("context_length") or 0,
                "tools": "tools" in params,
                # Open-weight models publish a Hugging Face id; proprietary ones
                # do not. Surfaced so "an OSS model" is a filter, not a guess.
                "open_weights": bool(item.get("hugging_face_id")),
                "reasoning_by_default": bool(reasoning.get("default_enabled")),
                "prompt_usd_per_m": round(prompt_cost, 4),
                "completion_usd_per_m": round(completion_cost, 4),
            }
        )
    out.sort(key=lambda m: m["id"])
    return out
