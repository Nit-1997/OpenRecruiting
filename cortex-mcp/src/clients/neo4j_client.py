"""Async Neo4j client for the Cortex MCP service.

The driver is created once at startup and owns its own connection pool.
The MCP server's process model is long-lived (uvicorn workers), so we
do not face the warm-Lambda event-loop pitfall the Cortex backend has
to manage. Lifecycle is handled by FastAPI's startup/shutdown hooks
through `init_driver` / `close_driver` below.
"""
from __future__ import annotations

import structlog
from neo4j import AsyncDriver, AsyncGraphDatabase

from src.config.settings import get_settings

logger = structlog.get_logger(__name__)

_driver: AsyncDriver | None = None


async def init_driver() -> None:
    global _driver
    if _driver is not None:
        return
    settings = get_settings()
    _driver = AsyncGraphDatabase.driver(
        settings.neo4j_uri,
        auth=(settings.neo4j_username, settings.neo4j_password),
        connection_timeout=10,
    )
    await _driver.verify_connectivity()
    logger.info("neo4j_driver_ready", uri=settings.neo4j_uri)


async def close_driver() -> None:
    global _driver
    if _driver is None:
        return
    await _driver.close()
    _driver = None
    logger.info("neo4j_driver_closed")


def get_driver() -> AsyncDriver:
    if _driver is None:
        raise RuntimeError("Neo4j driver not initialised — call init_driver() first")
    return _driver


async def run_read_query(
    query: str,
    params: dict,
    timeout_seconds: int,
    max_rows: int,
) -> list[dict]:
    """Execute a read-only Cypher query and return rows as plain dicts.

    Truncates at `max_rows` (defensive — the validator caps complexity but
    cannot bound the result set on its own). If the query exceeds the
    configured timeout, the underlying session raises and we surface that
    to the caller as a structured error.
    """
    driver = get_driver()
    settings = get_settings()
    async with driver.session(
        database=settings.neo4j_database,
        default_access_mode="READ",
    ) as session:
        result = await session.run(query, params, timeout=timeout_seconds)
        rows: list[dict] = []
        async for record in result:
            rows.append(dict(record))
            if len(rows) >= max_rows:
                break
        return rows
