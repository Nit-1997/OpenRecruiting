from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from src.sync.tombstone import TombstoneService


@pytest.fixture
def neo4j():
    n = AsyncMock()
    n.execute_write = AsyncMock(return_value=[{"tombstoned": 5}])
    return n


@pytest.mark.asyncio
async def test_tombstone_marks_edges_invalid(neo4j):
    svc = TombstoneService(neo4j)
    cnt = await svc.tombstone_prior_edges(
        event_type="feedback_debrief_available",
        source_id="cr-1",
        before=datetime(2026, 5, 9, tzinfo=timezone.utc),
    )
    assert cnt == 5

    args = neo4j.execute_write.await_args
    cypher, params = args.args
    assert "invalid_at" in cypher.lower()
    assert "_source_event_type" in cypher
    assert params["event_type"] == "feedback_debrief_available"
    assert params["source_id"] == "cr-1"
    assert params["before"] == "2026-05-09T00:00:00+00:00"


@pytest.mark.asyncio
async def test_tombstone_returns_zero_when_no_edges_match(neo4j):
    neo4j.execute_write = AsyncMock(return_value=[{"tombstoned": 0}])
    svc = TombstoneService(neo4j)
    cnt = await svc.tombstone_prior_edges(
        event_type="x", source_id="y",
        before=datetime(2026, 5, 9, tzinfo=timezone.utc),
    )
    assert cnt == 0
