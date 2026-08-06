"""EventQueue is the only thing that knows cortex_events is a queue.

These are unit tests over a faked supabase client; the SKIP LOCKED behaviour
itself is exercised in the integration test in Task 4, because it cannot be
faked meaningfully.
"""
from datetime import datetime, timezone

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

    await q.mark_done("11111111-1111-1111-1111-111111111111")

    write = sb.writes[0]
    assert write["table"] == "cortex_events"
    assert write["eq"]["id"] == "11111111-1111-1111-1111-111111111111"
    assert write["update"]["completed_at"] is not None
    assert write["update"]["last_error"] is None
    # A later re-edit must get a fresh budget, or a healthy row eventually parks.
    assert write["update"]["publish_count"] == 0


@pytest.mark.asyncio
async def test_mark_failed_records_a_truncated_error_and_leaves_completion_unset():
    sb = FakeSupabase()
    q = EventQueue(sb)

    await q.mark_failed("11111111-1111-1111-1111-111111111111", "boom " * 500)

    write = sb.writes[0]
    assert write["update"]["last_error"].startswith("boom")
    assert len(write["update"]["last_error"]) <= 500
    assert "completed_at" not in write["update"]
