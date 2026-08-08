"""Per-alias function-calling support, read once from the proxy's /model/info.

Defaults to True on any uncertainty. A false negative would silently downgrade a
capable model to emulated tools, which is worse than a loud failure from a model
that genuinely cannot do tools.
"""

from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable

import structlog

logger = structlog.get_logger(__name__)

HttpGet = Callable[[str], Awaitable[dict[str, Any]]]


class CapabilityCache:
    def __init__(
        self,
        http_get: HttpGet,
        forced_json_aliases: frozenset[str] = frozenset(),
    ) -> None:
        self._http_get = http_get
        self._forced = forced_json_aliases
        self._map: dict[str, bool] | None = None
        self._lock = asyncio.Lock()

    def reset(self) -> None:
        self._map = None

    async def supports_tools(self, alias: str) -> bool:
        if alias in self._forced:
            return False
        table = await self._load()
        return table.get(alias, True)

    async def _load(self) -> dict[str, bool]:
        if self._map is not None:
            return self._map
        async with self._lock:
            if self._map is not None:
                return self._map
            try:
                payload = await self._http_get("/model/info")
            except Exception as exc:  # noqa: BLE001 — never block a call on discovery
                logger.warning("llm_capability_probe_failed", error=str(exc))
                self._map = {}
                return self._map

            table: dict[str, bool] = {}
            for entry in payload.get("data", []) or []:
                name = entry.get("model_name")
                if not name:
                    continue
                info = entry.get("model_info") or {}
                table[name] = bool(info.get("supports_function_calling", True))
            self._map = table
            logger.info("llm_capabilities_loaded", aliases=len(table))
            return self._map
