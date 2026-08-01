from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.sync.event_record import IngestionRecord, IngestionRecordRepo


@pytest.fixture
def supabase_client():
    c = MagicMock()
    c.table = MagicMock(return_value=c)
    c.select = MagicMock(return_value=c)
    c.eq = MagicMock(return_value=c)
    c.maybe_single = MagicMock(return_value=c)
    c.execute = AsyncMock()
    c.upsert = MagicMock(return_value=c)
    return c


@pytest.mark.asyncio
async def test_get_returns_none_when_not_found(supabase_client):
    supabase_client.execute.return_value = MagicMock(data=None)
    repo = IngestionRecordRepo(supabase_client)
    out = await repo.get(event_type="feedback_debrief_available", source_id="cr-1")
    assert out is None


@pytest.mark.asyncio
async def test_get_returns_parsed_record(supabase_client):
    supabase_client.execute.return_value = MagicMock(data={
        "id": "rec-1",
        "event_type": "feedback_debrief_available",
        "source_id": "cr-1",
        "org_id": "org-1",
        "last_touch_at": "2026-05-09T14:00:00+00:00",
        "ingested_at": "2026-05-09T14:00:01+00:00",
        "nodes_count": 4,
        "edges_count": 6,
        "publish_count": 1,
    })
    repo = IngestionRecordRepo(supabase_client)
    out = await repo.get(event_type="feedback_debrief_available", source_id="cr-1")
    assert out is not None
    assert out.event_type == "feedback_debrief_available"
    assert out.last_touch_at == datetime(2026, 5, 9, 14, 0, 0, tzinfo=timezone.utc)
    assert out.edges_count == 6


@pytest.mark.asyncio
async def test_upsert_writes_payload(supabase_client):
    supabase_client.execute.return_value = MagicMock(data=[{"id": "rec-1"}])
    repo = IngestionRecordRepo(supabase_client)
    rec = IngestionRecord(
        event_type="feedback_debrief_available",
        source_id="cr-1",
        org_id="org-1",
        last_touch_at=datetime(2026, 5, 9, 14, 0, 0, tzinfo=timezone.utc),
        ingested_at=datetime(2026, 5, 9, 14, 0, 1, tzinfo=timezone.utc),
        nodes_count=4,
        edges_count=6,
        publish_count=1,
    )
    await repo.upsert(rec)
    supabase_client.upsert.assert_called_once()
    payload = supabase_client.upsert.call_args.args[0]
    assert payload["event_type"] == "feedback_debrief_available"
    assert payload["nodes_count"] == 4
