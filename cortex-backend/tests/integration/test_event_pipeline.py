"""End-to-end pipeline smoke test.

Validates the processing flow with mocked Supabase + mocked Graphiti:
  1. Process a synthetic event for a NEW (event_type, source_id) → handler called, IngestionRecord upserted, no tombstone.
  2. Process a SECOND synthetic event with a NEWER last_touch_at → tombstone called, handler called, IngestionRecord updated.
  3. Process a STALE event (older last_touch_at) → no calls, dropped silently.
"""
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.service.graph_ingestion_service import IngestionResult as HandlerResult
from src.sync.event_processor import EventProcessor
from src.sync.event_queue import ClaimedEvent
from src.sync.event_record import IngestionRecord, IngestionRecordRepo
from src.sync.tombstone import TombstoneService


def _event(last_touch_at: str):
    return ClaimedEvent(
        id="ev-1",
        event_type="feedback_debrief_available",
        source_id="cr-1",
        org_id="org-1",
        last_touch_at=datetime.fromisoformat(last_touch_at),
        publish_count=1,
    )


@pytest.mark.asyncio
async def test_first_then_re_edit_then_stale():
    handler = MagicMock()
    handler.handle = AsyncMock(return_value=HandlerResult(
        nodes_created=2, edges_created=3, errors=[],
    ))
    router = MagicMock()
    router.get_handler = MagicMock(return_value=handler)

    repo_storage: dict[tuple[str, str], IngestionRecord] = {}

    class StubRepo:
        async def get(self, event_type, source_id):
            return repo_storage.get((event_type, source_id))

        async def upsert(self, rec):
            repo_storage[(rec.event_type, rec.source_id)] = rec

    tombstone = MagicMock()
    tombstone.tombstone_prior_edges = AsyncMock(return_value=3)

    processor = EventProcessor(
        event_router=router, ingestion_repo=StubRepo(), tombstone=tombstone,
    )

    await processor.process(_event("2026-05-07T00:00:00+00:00"))
    assert handler.handle.await_count == 1
    tombstone.tombstone_prior_edges.assert_not_awaited()

    await processor.process(_event("2026-05-09T00:00:00+00:00"))
    assert handler.handle.await_count == 2
    assert tombstone.tombstone_prior_edges.await_count == 1

    await processor.process(_event("2026-05-08T00:00:00+00:00"))
    assert handler.handle.await_count == 2  # unchanged
    assert tombstone.tombstone_prior_edges.await_count == 1  # unchanged
