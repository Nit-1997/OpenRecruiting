"""Per-alias function-calling support, read from the proxy's /model/info.

One successful read is cached for the process; a failed one is cached only for
_FAILURE_BACKOFF_SECONDS, so an outage neither freezes the fail-open default in
place forever nor charges every caller a fresh timeout.

Defaults to True on any uncertainty. A false negative would silently downgrade a
capable model to emulated tools, which is worse than a loud failure from a model
that genuinely cannot do tools. Only an explicit boolean from the proxy overrides
that default — a string, a null or an absent key is treated as no answer at all.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Awaitable, Callable

import structlog

logger = structlog.get_logger(__name__)

HttpGet = Callable[[str], Awaitable[dict[str, Any]]]

# How long a failed probe suppresses the next one. Retrying inside the lock on
# every call turns a gateway outage into O(N callers x LLM_TIMEOUT_SECONDS) of
# serialized waiting, because each caller queues behind the previous one's
# timeout. Long enough to collapse a burst, short enough that recovery is
# noticed within a request or two.
_FAILURE_BACKOFF_SECONDS = 30.0


def _monotonic() -> float:
    """Indirection so tests can drive the backoff clock. Monotonic, so a system
    clock adjustment cannot extend or shorten the window."""
    return time.monotonic()


class CapabilityCache:
    def __init__(
        self,
        http_get: HttpGet,
        forced_json_aliases: frozenset[str] = frozenset(),
    ) -> None:
        self._http_get = http_get
        self._forced = forced_json_aliases
        self._map: dict[str, bool] | None = None
        self._failed_at: float | None = None
        self._lock = asyncio.Lock()

    def reset(self) -> None:
        self._map = None
        self._failed_at = None

    async def supports_tools(self, alias: str) -> bool:
        if alias in self._forced:
            return False
        table = await self._load()
        return table.get(alias, True)

    def _backing_off(self) -> bool:
        """True while the last failure is still recent. Expiry is self-clearing, so
        the window can never become permanent."""
        if self._failed_at is None:
            return False
        if _monotonic() - self._failed_at < _FAILURE_BACKOFF_SECONDS:
            return True
        self._failed_at = None
        return False

    async def _load(self) -> dict[str, bool]:
        if self._map is not None:
            return self._map
        if self._backing_off():
            return {}
        async with self._lock:
            # Re-checked under the lock: callers that queued while the holder was
            # timing out must fall straight through to the fail-open default
            # rather than each paying their own round-trip.
            if self._map is not None:
                return self._map
            if self._backing_off():
                return {}
            try:
                payload = await self._http_get("/model/info")
            except Exception as exc:  # noqa: BLE001 — never block a call on discovery
                # The empty table is never memoized. Caching it would pin every alias
                # to the fail-open default for the life of the process, so a single
                # hiccup at boot would permanently strip tool emulation from the models
                # that actually need it. Only the failure *time* is recorded, and the
                # next call after the window probes again.
                self._failed_at = _monotonic()
                logger.warning("llm_capability_probe_failed", error=str(exc))
                return {}

            self._failed_at = None
            table: dict[str, bool] = {}
            for entry in payload.get("data", []) or []:
                name = entry.get("model_name")
                if not name:
                    continue
                info = entry.get("model_info") or {}
                flag = info.get("supports_function_calling")
                # Only a real bool is an answer. A string, a null or a missing key is
                # an unparsed config value, not a claim of incapability, so it falls
                # through to the fail-open default rather than through truthiness.
                table[name] = flag if isinstance(flag, bool) else True
            self._map = table
            logger.info("llm_capabilities_loaded", aliases=len(table))
            return self._map
