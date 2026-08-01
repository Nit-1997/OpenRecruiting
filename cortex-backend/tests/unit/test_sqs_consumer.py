import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.model.ingestion import SourceRef
from src.service.graph_ingestion_service import IngestionResult as HandlerResult
from src.sync.event_record import IngestionRecord
from src.sync.sqs_consumer import SqsConsumer


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


def _msg(event_type="feedback_debrief_available", source_id="cr-1",
         org_id="org-1", last_touch_at="2026-05-09T14:00:00+00:00",
         publish_count=1, event_pk="ev-1"):
    return {
        "Body": json.dumps({
            "event_type": event_type,
            "source_id": source_id,
            "org_id": org_id,
            "last_touch_at": last_touch_at,
            "publish_count": publish_count,
            "event_pk": event_pk,
        }),
        "ReceiptHandle": "rh-1",
    }


@pytest.mark.asyncio
async def test_first_ingest_path(deps):
    router, handler, repo, tombstone = deps
    consumer = SqsConsumer(
        sqs_client=MagicMock(), queue_url="q",
        event_router=router, ingestion_repo=repo, tombstone=tombstone,
    )
    await consumer.handle_message(_msg())

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
    consumer = SqsConsumer(
        sqs_client=MagicMock(), queue_url="q",
        event_router=router, ingestion_repo=repo, tombstone=tombstone,
    )
    await consumer.handle_message(_msg(last_touch_at="2026-05-09T14:00:00+00:00"))

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
    consumer = SqsConsumer(
        sqs_client=MagicMock(), queue_url="q",
        event_router=router, ingestion_repo=repo, tombstone=tombstone,
    )
    await consumer.handle_message(_msg(last_touch_at="2026-05-08T00:00:00+00:00"))

    tombstone.tombstone_prior_edges.assert_not_awaited()
    handler.handle.assert_not_awaited()
    repo.upsert.assert_not_awaited()


@pytest.mark.asyncio
async def test_handle_failure_raises_for_sqs_retry(deps):
    router, handler, repo, tombstone = deps
    handler.handle = AsyncMock(return_value=_failure_result())
    consumer = SqsConsumer(
        sqs_client=MagicMock(), queue_url="q",
        event_router=router, ingestion_repo=repo, tombstone=tombstone,
    )
    with pytest.raises(Exception):
        await consumer.handle_message(_msg())
    repo.upsert.assert_not_awaited()
