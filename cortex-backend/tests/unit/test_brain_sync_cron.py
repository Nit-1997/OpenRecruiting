import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.sync.brain_sync_cron import BrainSyncCron


@pytest.fixture
def supabase():
    c = MagicMock()
    c.rpc = MagicMock(return_value=c)
    c.table = MagicMock(return_value=c)
    c.select = MagicMock(return_value=c)
    c.update = MagicMock(return_value=c)
    c.eq = MagicMock(return_value=c)
    c.is_ = MagicMock(return_value=c)
    c.or_ = MagicMock(return_value=c)
    c.lt = MagicMock(return_value=c)
    c.order = MagicMock(return_value=c)
    c.limit = MagicMock(return_value=c)
    c.execute = AsyncMock()
    return c


@pytest.fixture
def sqs():
    s = MagicMock()
    s.send_message = MagicMock()
    return s


@pytest.mark.asyncio
async def test_publish_settled_emits_to_sqs_and_marks_published(supabase, sqs):
    supabase.execute.side_effect = [
        MagicMock(data=[{
            "id": "ev-1",
            "event_type": "feedback_debrief_available",
            "source_id": "cr-1",
            "org_id": "org-1",
            "last_touch_at": "2026-05-07T00:00:00+00:00",
            "publish_count": 0,
        }]),
        MagicMock(data=[{"id": "ev-1"}]),  # update result
    ]
    cron = BrainSyncCron(
        supabase=supabase, sqs_client=sqs, queue_url="q",
        settledness_window_hours=48, batch_size=100,
    )
    sent = await cron.publish_settled_events()
    assert sent == 1
    sqs.send_message.assert_called_once()
    kw = sqs.send_message.call_args.kwargs
    body = json.loads(kw["MessageBody"])
    assert body["event_type"] == "feedback_debrief_available"
    assert kw["MessageGroupId"] == "feedback_debrief_available:cr-1"


@pytest.mark.asyncio
async def test_publish_zero_when_nothing_settled(supabase, sqs):
    supabase.execute.return_value = MagicMock(data=[])
    cron = BrainSyncCron(
        supabase=supabase, sqs_client=sqs, queue_url="q",
        settledness_window_hours=48, batch_size=100,
    )
    sent = await cron.publish_settled_events()
    assert sent == 0
    sqs.send_message.assert_not_called()


@pytest.mark.asyncio
async def test_publish_org_now_emits_and_marks_published(supabase, sqs):
    # First call: select returns one eligible row.
    # Second call: the UPDATE that marks it published.
    # Third call: re-select returns empty (row no longer eligible) → loop exits.
    supabase.execute.side_effect = [
        MagicMock(data=[{
            "id": "ev-1",
            "event_type": "feedback_debrief_available",
            "source_id": "cr-1",
            "org_id": "org-1",
            "last_touch_at": "2026-05-09T00:00:00+00:00",
            "publish_count": 2,
        }]),
        MagicMock(data=[{"id": "ev-1"}]),
        MagicMock(data=[]),
    ]
    cron = BrainSyncCron(
        supabase=supabase, sqs_client=sqs, queue_url="q",
        settledness_window_hours=48, batch_size=100,
    )

    result = await cron.publish_org_now("org-1")

    assert result["scanned"] == 1
    assert result["published"] == 1
    assert result["batches"] == 1
    assert result["errors"] == []
    sqs.send_message.assert_called_once()
    kw = sqs.send_message.call_args.kwargs
    body = json.loads(kw["MessageBody"])
    assert body["org_id"] == "org-1"
    assert body["publish_count"] == 3  # 2 + 1
    assert kw["MessageGroupId"] == "feedback_debrief_available:cr-1"


@pytest.mark.asyncio
async def test_publish_org_now_returns_empty_when_nothing_eligible(supabase, sqs):
    supabase.execute.return_value = MagicMock(data=[])
    cron = BrainSyncCron(
        supabase=supabase, sqs_client=sqs, queue_url="q",
        settledness_window_hours=48, batch_size=100,
    )

    result = await cron.publish_org_now("org-1")

    assert result == {"scanned": 0, "published": 0, "batches": 0, "errors": []}
    sqs.send_message.assert_not_called()


@pytest.mark.asyncio
async def test_publish_org_now_breaks_when_no_progress(supabase, sqs):
    # SQS fails for every row → publishes never happen → published_at never moves
    # → next select returns the same row → seen_ids guard breaks the loop.
    row = {
        "id": "ev-stuck",
        "event_type": "feedback_completed",
        "source_id": "cr-stuck",
        "org_id": "org-1",
        "last_touch_at": "2026-05-09T00:00:00+00:00",
        "publish_count": 0,
    }
    supabase.execute.side_effect = [
        MagicMock(data=[row]),
        MagicMock(data=[row]),  # re-fetch returns same row because publish failed
    ]
    sqs.send_message.side_effect = Exception("sqs unavailable")

    cron = BrainSyncCron(
        supabase=supabase, sqs_client=sqs, queue_url="q",
        settledness_window_hours=48, batch_size=100,
    )

    result = await cron.publish_org_now("org-1")

    assert result["scanned"] == 1
    assert result["published"] == 0
    assert result["batches"] == 1
    assert len(result["errors"]) == 1
    assert "sqs unavailable" in result["errors"][0]


@pytest.mark.asyncio
async def test_publish_org_now_uses_rpc_for_eligibility(supabase, sqs):
    """Regression: eligibility is `last_touch_at > published_at`, a column-vs-
    column comparison that PostgREST URL filters can't express. The first cut
    used `.or_("published_at.is.null,last_touch_at.gt.published_at")` which
    PostgREST parses as `last_touch_at > 'published_at'` (string literal) and
    fails at runtime. The fix is the SQL RPC `cortex_events_for_org_unpublished`
    (migration 75). Lock that in: assert the RPC is invoked with the org_id
    and limit, and assert we do NOT fall back to a table().or_() filter."""
    supabase.execute.return_value = MagicMock(data=[])
    cron = BrainSyncCron(
        supabase=supabase, sqs_client=sqs, queue_url="q",
        settledness_window_hours=48, batch_size=100,
    )

    await cron.publish_org_now("org-xyz")

    supabase.rpc.assert_any_call(
        "cortex_events_for_org_unpublished",
        {"p_org_id": "org-xyz", "p_limit": 100},
    )
    # The broken column-vs-column filter pattern must not appear.
    for call in supabase.or_.call_args_list:
        assert "last_touch_at.gt.published_at" not in (call.args[0] if call.args else ""), (
            "force-publish must use RPC, not the column-vs-column filter"
        )


@pytest.mark.asyncio
async def test_publish_org_now_fires_progress_callback_per_batch(supabase, sqs):
    # Two batches: first returns one row, second returns empty → loop exits.
    supabase.execute.side_effect = [
        MagicMock(data=[{
            "id": "ev-1",
            "event_type": "feedback_completed",
            "source_id": "cr-1",
            "org_id": "org-1",
            "last_touch_at": "2026-05-09T00:00:00+00:00",
            "publish_count": 0,
        }]),
        MagicMock(data=[{"id": "ev-1"}]),  # update result
        MagicMock(data=[]),  # second select returns nothing → exit
    ]
    cron = BrainSyncCron(
        supabase=supabase, sqs_client=sqs, queue_url="q",
        settledness_window_hours=48, batch_size=100,
    )

    progress_calls: list[tuple[int, int, int]] = []

    async def _record(scanned: int, published: int, batches: int) -> None:
        progress_calls.append((scanned, published, batches))

    result = await cron.publish_org_now("org-1", on_progress=_record)

    assert result["published"] == 1
    # Callback fires once per batch (only one batch happened).
    assert progress_calls == [(1, 1, 1)]


@pytest.mark.asyncio
async def test_publish_org_now_progress_callback_errors_do_not_abort(supabase, sqs):
    supabase.execute.side_effect = [
        MagicMock(data=[{
            "id": "ev-1",
            "event_type": "feedback_completed",
            "source_id": "cr-1",
            "org_id": "org-1",
            "last_touch_at": "2026-05-09T00:00:00+00:00",
            "publish_count": 0,
        }]),
        MagicMock(data=[{"id": "ev-1"}]),
        MagicMock(data=[]),
    ]
    cron = BrainSyncCron(
        supabase=supabase, sqs_client=sqs, queue_url="q",
        settledness_window_hours=48, batch_size=100,
    )

    async def _flaky(*_args: int) -> None:
        raise RuntimeError("supabase update flaked")

    # Should not raise — progress reporting is best-effort.
    result = await cron.publish_org_now("org-1", on_progress=_flaky)
    assert result["published"] == 1
