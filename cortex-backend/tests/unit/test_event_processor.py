from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.model.ingestion import SourceRef
from src.service.graph_ingestion_service import IngestionResult as HandlerResult
from src.sync.event_processor import EventProcessor
from src.sync.event_queue import ClaimedEvent
from src.sync.event_record import IngestionRecord


def _success_result():
    return HandlerResult(nodes_created=2, edges_created=3, errors=[])


def _failure_result():
    return HandlerResult(nodes_created=0, edges_created=0, errors=["validator failed"])


@pytest.fixture
def event_router():
    handler = MagicMock()
    handler.handle = AsyncMock(return_value=_success_result())
    router = MagicMock()
    router.get_handler = MagicMock(return_value=handler)
    return router, handler


@pytest.fixture
def deps(event_router):
    router, handler = event_router
    repo = MagicMock()
    repo.get = AsyncMock(return_value=None)
    repo.upsert = AsyncMock()
    tombstone = MagicMock()
    tombstone.tombstone_prior_edges = AsyncMock(return_value=0)
    return router, handler, repo, tombstone


def _event(event_type="feedback_debrief_available", source_id="cr-1",
           org_id="org-1", last_touch_at="2026-05-09T14:00:00+00:00",
           publish_count=1, event_pk="ev-1"):
    return ClaimedEvent(
        id=event_pk,
        event_type=event_type,
        source_id=source_id,
        org_id=org_id,
        last_touch_at=datetime.fromisoformat(last_touch_at),
        publish_count=publish_count,
    )


@pytest.mark.asyncio
async def test_first_ingest_path(deps):
    router, handler, repo, tombstone = deps
    processor = EventProcessor(
        event_router=router, ingestion_repo=repo, tombstone=tombstone,
    )
    await processor.process(_event())

    tombstone.tombstone_prior_edges.assert_not_awaited()
    handler.handle.assert_awaited_once()
    args = handler.handle.await_args
    source_ref = args.args[0]
    org_id = args.args[1]
    assert isinstance(source_ref, SourceRef)
    assert source_ref.candidate_round_id == "cr-1"
    assert org_id == "org-1"
    assert "provenance" in args.kwargs
    repo.upsert.assert_awaited_once()


@pytest.mark.asyncio
async def test_re_edit_path_tombstones_then_ingests(deps):
    router, handler, repo, tombstone = deps
    repo.get = AsyncMock(return_value=IngestionRecord(
        event_type="feedback_debrief_available",
        source_id="cr-1",
        org_id="org-1",
        last_touch_at=datetime(2026, 5, 7, tzinfo=timezone.utc),
        ingested_at=datetime(2026, 5, 7, tzinfo=timezone.utc),
        nodes_count=2, edges_count=3, publish_count=1,
    ))
    tombstone.tombstone_prior_edges = AsyncMock(return_value=3)
    processor = EventProcessor(
        event_router=router, ingestion_repo=repo, tombstone=tombstone,
    )
    await processor.process(_event(last_touch_at="2026-05-09T14:00:00+00:00"))

    tombstone.tombstone_prior_edges.assert_awaited_once()
    handler.handle.assert_awaited_once()
    repo.upsert.assert_awaited_once()


@pytest.mark.asyncio
async def test_stale_message_dropped(deps):
    router, handler, repo, tombstone = deps
    repo.get = AsyncMock(return_value=IngestionRecord(
        event_type="feedback_debrief_available",
        source_id="cr-1",
        org_id="org-1",
        last_touch_at=datetime(2026, 5, 9, 14, 0, 0, tzinfo=timezone.utc),
        ingested_at=datetime(2026, 5, 9, tzinfo=timezone.utc),
        nodes_count=2, edges_count=3, publish_count=1,
    ))
    processor = EventProcessor(
        event_router=router, ingestion_repo=repo, tombstone=tombstone,
    )
    await processor.process(_event(last_touch_at="2026-05-08T00:00:00+00:00"))

    tombstone.tombstone_prior_edges.assert_not_awaited()
    handler.handle.assert_not_awaited()
    repo.upsert.assert_not_awaited()


@pytest.mark.asyncio
async def test_handle_failure_raises_for_sqs_retry(deps):
    router, handler, repo, tombstone = deps
    handler.handle = AsyncMock(return_value=_failure_result())
    processor = EventProcessor(
        event_router=router, ingestion_repo=repo, tombstone=tombstone,
    )
    with pytest.raises(Exception):
        await processor.process(_event())
    repo.upsert.assert_not_awaited()


@pytest.mark.asyncio
async def test_publish_count_is_taken_from_the_claim_not_the_payload(deps):
    """publish_count used to arrive in the SQS body; it now comes off the claim.
    IngestionRecord stores it as provenance, so a wrong source is silent."""
    router, _handler, repo, tombstone = deps
    processor = EventProcessor(
        event_router=router, ingestion_repo=repo, tombstone=tombstone,
    )

    await processor.process(ClaimedEvent(
        id="11111111-1111-1111-1111-111111111111",
        event_type="plan_created",
        source_id="22222222-2222-2222-2222-222222222222",
        org_id="33333333-3333-3333-3333-333333333333",
        last_touch_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
        publish_count=3,
    ))

    assert repo.upsert.await_args.args[0].publish_count == 3
