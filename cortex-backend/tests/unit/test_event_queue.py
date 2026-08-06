"""EventQueue is the only thing that knows cortex_events is a queue.

These are unit tests over a faked supabase client; the SKIP LOCKED behaviour
itself is exercised in the integration test in Task 4, because it cannot be
faked meaningfully.
"""
from datetime import datetime, timedelta, timezone

import pytest

from src.sync.event_queue import ClaimedEvent, EventQueue


class FakeResp:
    def __init__(self, data):
        self.data = data


class FakeQuery:
    def __init__(self, recorder, table):
        self._rec = recorder
        self._table = table
        self._update = None
        self._eq = {}

    def update(self, values):
        self._update = values
        return self

    def eq(self, col, val):
        self._eq[col] = val
        return self

    async def execute(self):
        self._rec.append({"table": self._table, "update": self._update, "eq": dict(self._eq)})
        return FakeResp([])


class FakeSupabase:
    def __init__(self, rpc_rows=None):
        self.rpc_rows = rpc_rows or []
        self.rpc_calls = []
        self.writes = []

    def rpc(self, name, params):
        self.rpc_calls.append({"name": name, "params": params})
        outer = self

        class _R:
            async def execute(self_inner):
                return FakeResp(outer.rpc_rows)

        return _R()

    def table(self, name):
        return FakeQuery(self.writes, name)


def _row(**over):
    base = {
        "id": "11111111-1111-1111-1111-111111111111",
        "event_type": "plan_created",
        "source_id": "22222222-2222-2222-2222-222222222222",
        "org_id": "33333333-3333-3333-3333-333333333333",
        "last_touch_at": "2026-08-01T00:00:00+00:00",
        "publish_count": 1,
    }
    base.update(over)
    return base


@pytest.mark.asyncio
async def test_claim_batch_passes_lease_and_attempt_caps_to_the_rpc():
    sb = FakeSupabase(rpc_rows=[_row()])
    q = EventQueue(sb, lease_seconds=300, max_attempts=5)
    cutoff = datetime(2026, 8, 1, tzinfo=timezone.utc)

    events = await q.claim_batch(limit=10, cutoff=cutoff)

    call = sb.rpc_calls[0]
    assert call["name"] == "cortex_events_claim_batch"
    assert call["params"]["p_lease_seconds"] == 300
    assert call["params"]["p_max_attempts"] == 5
    assert call["params"]["p_limit"] == 10
    assert call["params"]["p_cutoff"] == cutoff.isoformat()
    assert call["params"]["p_org_id"] is None
    assert len(events) == 1
    assert isinstance(events[0], ClaimedEvent)
    assert events[0].event_type == "plan_created"
    assert events[0].last_touch_at == datetime(2026, 8, 1, tzinfo=timezone.utc)
    # Distinct UUIDs per column: a transposed mapping hands the scheduler the
    # wrong entity, and no KeyError would ever surface it.
    assert events[0].id == "11111111-1111-1111-1111-111111111111"
    assert events[0].source_id == "22222222-2222-2222-2222-222222222222"
    assert events[0].org_id == "33333333-3333-3333-3333-333333333333"
    assert events[0].publish_count == 1


@pytest.mark.asyncio
async def test_claim_batch_scopes_to_org_and_drops_the_window_for_force_publish():
    sb = FakeSupabase(rpc_rows=[])
    q = EventQueue(sb)

    await q.claim_batch(limit=50, cutoff=None, org_id="33333333-3333-3333-3333-333333333333")

    params = sb.rpc_calls[0]["params"]
    assert params["p_cutoff"] is None
    assert params["p_org_id"] == "33333333-3333-3333-3333-333333333333"


@pytest.mark.asyncio
async def test_mark_done_stamps_completion_and_resets_the_retry_budget():
    sb = FakeSupabase()
    q = EventQueue(sb)
    touched_at = datetime(2026, 8, 1, tzinfo=timezone.utc)

    await q.mark_done("11111111-1111-1111-1111-111111111111", touched_at)

    write = sb.writes[0]
    assert write["table"] == "cortex_events"
    assert write["eq"]["id"] == "11111111-1111-1111-1111-111111111111"
    assert write["update"]["completed_at"] == touched_at.isoformat()
    assert write["update"]["last_error"] is None
    # A later re-edit must get a fresh budget, or a healthy row eventually parks.
    assert write["update"]["publish_count"] == 0


@pytest.mark.asyncio
async def test_mark_done_stamps_the_claimed_touch_so_a_mid_flight_edit_survives():
    """Stamping now() instead would swallow an edit that lands between claim
    and completion: its last_touch_at predates the stamp, so the claim
    predicate last_touch_at > completed_at stays false and the row is never
    re-queued until some later unrelated edit bumps it."""
    sb = FakeSupabase(rpc_rows=[_row()])
    q = EventQueue(sb)
    claimed = (await q.claim_batch(limit=1, cutoff=None))[0]
    edit_during_processing = claimed.last_touch_at + timedelta(seconds=5)

    await q.mark_done(claimed.id, claimed.last_touch_at)

    stamped = datetime.fromisoformat(sb.writes[0]["update"]["completed_at"])
    assert stamped == claimed.last_touch_at
    assert stamped < edit_during_processing


@pytest.mark.asyncio
async def test_mark_failed_records_a_truncated_error_and_leaves_completion_unset():
    sb = FakeSupabase()
    q = EventQueue(sb)

    await q.mark_failed("11111111-1111-1111-1111-111111111111", "boom " * 500)

    write = sb.writes[0]
    assert write["update"]["last_error"].startswith("boom")
    assert len(write["update"]["last_error"]) <= 500
    assert "completed_at" not in write["update"]
