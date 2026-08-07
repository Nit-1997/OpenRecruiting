from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.sync.brain_sync_cron import BrainSyncCron
from src.sync.event_queue import ClaimedEvent


def _event(event_id: str = "ev-1", event_type: str = "feedback_debrief_available",
           source_id: str = "cr-1", publish_count: int = 0) -> ClaimedEvent:
    return ClaimedEvent(
        id=event_id,
        event_type=event_type,
        source_id=source_id,
        org_id="org-1",
        last_touch_at=datetime(2026, 5, 7, tzinfo=timezone.utc),
        publish_count=publish_count,
    )


@pytest.fixture
def supabase():
    c = MagicMock()
    c.rpc = MagicMock(return_value=c)
    c.table = MagicMock(return_value=c)
    c.select = MagicMock(return_value=c)
    c.update = MagicMock(return_value=c)
    c.upsert = MagicMock(return_value=c)
    c.eq = MagicMock(return_value=c)
    c.is_ = MagicMock(return_value=c)
    c.or_ = MagicMock(return_value=c)
    c.lt = MagicMock(return_value=c)
    c.order = MagicMock(return_value=c)
    c.limit = MagicMock(return_value=c)
    c.execute = AsyncMock()
    return c


@pytest.fixture
def queue():
    q = MagicMock()
    q.claim_batch = AsyncMock(return_value=[])
    q.mark_done = AsyncMock()
    q.mark_failed = AsyncMock()
    return q


@pytest.fixture
def processor():
    p = MagicMock()
    p.process = AsyncMock()
    return p


def _cron(supabase, queue, processor, batch_size: int = 100) -> BrainSyncCron:
    return BrainSyncCron(
        supabase=supabase, queue=queue, processor=processor,
        settledness_window_hours=48, batch_size=batch_size,
    )


@pytest.mark.asyncio
async def test_process_settled_ingests_and_marks_done(supabase, queue, processor):
    event = _event()
    queue.claim_batch.return_value = [event]

    processed = await _cron(supabase, queue, processor).process_settled_events()

    assert processed == 1
    processor.process.assert_awaited_once_with(event)
    queue.mark_failed.assert_not_awaited()


@pytest.mark.asyncio
async def test_mark_done_stamps_the_claimed_rows_last_touch_at(supabase, queue, processor):
    """Regression: stamping an app-clock now() would let an edit landing between
    claim and completion look older than completed_at, so it would never re-queue."""
    event = _event()
    queue.claim_batch.return_value = [event]

    await _cron(supabase, queue, processor).process_settled_events()

    queue.mark_done.assert_awaited_once_with(event.id, event.last_touch_at)


@pytest.mark.asyncio
async def test_process_zero_when_nothing_settled(supabase, queue, processor):
    processed = await _cron(supabase, queue, processor).process_settled_events()

    assert processed == 0
    processor.process.assert_not_awaited()
    queue.mark_done.assert_not_awaited()


@pytest.mark.asyncio
async def test_one_poisoned_row_does_not_stop_the_batch(supabase, queue, processor):
    good, bad = _event("ev-good"), _event("ev-bad")
    queue.claim_batch.return_value = [bad, good]
    processor.process.side_effect = [RuntimeError("handler exploded"), None]

    processed = await _cron(supabase, queue, processor).process_settled_events()

    assert processed == 1
    queue.mark_failed.assert_awaited_once_with("ev-bad", "handler exploded")
    queue.mark_done.assert_awaited_once_with("ev-good", good.last_touch_at)


@pytest.mark.asyncio
async def test_process_org_now_ingests_and_reports(supabase, queue, processor):
    queue.claim_batch.side_effect = [[_event()], []]

    result = await _cron(supabase, queue, processor).process_org_now("org-1")

    assert result == {"scanned": 1, "published": 1, "batches": 1, "errors": []}
    processor.process.assert_awaited_once()


@pytest.mark.asyncio
async def test_process_org_now_returns_empty_when_nothing_eligible(supabase, queue, processor):
    result = await _cron(supabase, queue, processor).process_org_now("org-1")

    assert result == {"scanned": 0, "published": 0, "batches": 0, "errors": []}
    processor.process.assert_not_awaited()


@pytest.mark.asyncio
async def test_process_org_now_breaks_when_no_progress(supabase, queue, processor):
    """A failing row keeps no lease once it expires, so a short lease can hand
    back the same id forever. The seen_ids guard has to break the loop."""
    stuck = _event("ev-stuck", event_type="feedback_completed", source_id="cr-stuck")
    queue.claim_batch.side_effect = [[stuck], [stuck]]
    processor.process.side_effect = RuntimeError("neo4j unavailable")

    result = await _cron(supabase, queue, processor).process_org_now("org-1")

    assert result["scanned"] == 1
    assert result["published"] == 0
    assert result["batches"] == 1
    assert len(result["errors"]) == 1
    assert "neo4j unavailable" in result["errors"][0]


@pytest.mark.asyncio
async def test_process_org_now_claims_by_org_with_no_cutoff(supabase, queue, processor):
    """Force-publish must bypass the settledness window (cutoff=None) and scope
    to the one org. Eligibility itself lives in cortex_events_claim_batch, not in
    a PostgREST filter — `last_touch_at.gt.published_at` is a column-vs-column
    comparison PostgREST parses as a string literal and cannot express."""
    await _cron(supabase, queue, processor).process_org_now("org-xyz")

    queue.claim_batch.assert_awaited_once_with(limit=100, cutoff=None, org_id="org-xyz")
    for call in supabase.or_.call_args_list:
        assert "last_touch_at.gt.published_at" not in (call.args[0] if call.args else ""), (
            "force-publish must claim via RPC, not the column-vs-column filter"
        )


@pytest.mark.asyncio
async def test_process_org_now_fires_progress_callback_per_batch(supabase, queue, processor):
    queue.claim_batch.side_effect = [[_event()], []]
    progress_calls: list[tuple[int, int, int]] = []

    async def _record(scanned: int, published: int, batches: int) -> None:
        progress_calls.append((scanned, published, batches))

    result = await _cron(supabase, queue, processor).process_org_now(
        "org-1", on_progress=_record
    )

    assert result["published"] == 1
    assert progress_calls == [(1, 1, 1)]


@pytest.mark.asyncio
async def test_process_org_now_progress_callback_errors_do_not_abort(supabase, queue, processor):
    queue.claim_batch.side_effect = [[_event()], []]

    async def _flaky(*_args: int) -> None:
        raise RuntimeError("supabase update flaked")

    result = await _cron(supabase, queue, processor).process_org_now(
        "org-1", on_progress=_flaky
    )
    assert result["published"] == 1


@pytest.mark.asyncio
async def test_reconcile_nudges_rows_missing_an_ingestion_record(supabase, queue, processor):
    supabase.execute.side_effect = [
        MagicMock(data=[{"source_id": "cr-1", "org_id": "org-1",
                        "last_touch_at": "2026-05-01T00:00:00+00:00"}]),
        MagicMock(data=[{"id": "ev-new"}]),
        MagicMock(data=[]),
    ]

    nudged = await _cron(supabase, queue, processor).reconcile()

    assert nudged == 1
    assert supabase.rpc.call_args_list[0].args[0] == "execute_readonly_query"
    supabase.table.assert_called_with("cortex_events")
    queue.claim_batch.assert_not_awaited()
