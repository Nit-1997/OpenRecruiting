"""BE-S2 resilience tests for the calendar-intelligence worker.

Covers:
  - _interval_loop floors its sleep at max(5, interval) so a misconfigured
    interval of 0 cannot become a tight busy-loop on repeated job failures.
  - _interval_loop escalates to ERROR after N consecutive failures (a silently
    dead loop is otherwise invisible) and resets the counter on success.
"""

from __future__ import annotations

import asyncio
import logging

import pytest


@pytest.mark.asyncio
async def test_interval_loop_floors_sleep_on_zero_interval(monkeypatch):
    """A 0s interval must NOT produce a 0s sleep on failure (busy-loop)."""
    import app.workers.calendar_intelligence_worker as w

    sleeps: list[float] = []
    real_sleep = asyncio.sleep

    async def fake_sleep(d):
        sleeps.append(d)
        # Yield control so the loop can be cancelled.
        await real_sleep(0)

    monkeypatch.setattr(w.asyncio, "sleep", fake_sleep)

    async def job():
        raise RuntimeError("boom")

    task = asyncio.create_task(w._interval_loop("test", job, 0))
    await real_sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert sleeps, "loop never slept"
    assert all(s >= 5 for s in sleeps), f"sleep not floored at 5s: {sleeps}"


@pytest.mark.asyncio
async def test_interval_loop_escalates_after_consecutive_failures(monkeypatch, caplog):
    import app.workers.calendar_intelligence_worker as w

    real_sleep = asyncio.sleep

    async def fast_sleep(d):
        await real_sleep(0)

    monkeypatch.setattr(w.asyncio, "sleep", fast_sleep)

    async def job():
        raise RuntimeError("boom")

    caplog.set_level(logging.WARNING)
    task = asyncio.create_task(w._interval_loop("escalate", job, 0))
    await real_sleep(0.1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    error_records = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert error_records, "expected ERROR escalation after consecutive failures"


@pytest.mark.asyncio
async def test_interval_loop_resets_failure_counter_on_success(monkeypatch):
    """A successful run between failures must reset the escalation counter."""
    import app.workers.calendar_intelligence_worker as w

    real_sleep = asyncio.sleep

    async def fast_sleep(d):
        await real_sleep(0)

    monkeypatch.setattr(w.asyncio, "sleep", fast_sleep)

    # alternate fail/success forever — should never escalate to ERROR.
    state = {"n": 0}

    async def job():
        state["n"] += 1
        if state["n"] % 2 == 1:
            raise RuntimeError("boom")

    import logging as _logging
    records: list[_logging.LogRecord] = []

    class _Capture(_logging.Handler):
        def emit(self, record):
            records.append(record)

    handler = _Capture()
    w.logger.addHandler(handler)
    try:
        task = asyncio.create_task(w._interval_loop("reset", job, 0))
        await real_sleep(0.1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        w.logger.removeHandler(handler)

    assert not any(r.levelno >= _logging.ERROR for r in records), \
        "counter must reset on success; no sustained-failure ERROR expected"


@pytest.mark.asyncio
async def test_cancel_event_closes_recall_client_once_per_loop(monkeypatch):
    """In _check_reschedule's cancellation path, the Recall service must be
    created once and closed in finally (not per bot, not leaked)."""
    import app.workers.calendar_intelligence_worker as w

    close_calls = {"n": 0}

    class FakeRecall:
        async def remove_bot_from_call(self, bot_id):
            return True

        async def delete_bot(self, bot_id):
            return True

        async def close(self):
            close_calls["n"] += 1

    created = {"n": 0}

    def fake_get_recall_service():
        created["n"] += 1
        return FakeRecall()

    import app.services.recall_service as rs
    monkeypatch.setattr(rs, "get_recall_service", fake_get_recall_service)

    # Two bots so a per-iteration leak would create/close twice (or never).
    bot_rows = type("R", (), {"data": [
        {"id": "b1", "recall_bot_id": "rb1", "status": "in_call_recording"},
        {"id": "b2", "recall_bot_id": "rb2", "status": "created"},
    ]})()

    class FakeQuery:
        def __init__(self, result):
            self._result = result

        def select(self, *a, **k):
            return self

        def update(self, *a, **k):
            return self

        def eq(self, *a, **k):
            return self

        async def execute_async(self):
            return self._result

    class FakeSupabase:
        def table(self, name):
            if name == "recall_bots":
                return FakeQuery(bot_rows)
            if name == "candidate_rounds":
                return FakeQuery(type("R", (), {"data": []})())
            if name == "calendar_event_detections":
                return FakeQuery(type("R", (), {"data": [{"matched_candidate_round_id": None, "profile_id": "p1"}]})())
            if name == "slack_connections":
                return FakeQuery(type("R", (), {"data": []})())
            return FakeQuery(type("R", (), {"data": []})())

    existing = {"id": "det1", "detection_status": "confirmed"}
    event = {"raw": {"status": "cancelled"}, "is_deleted": True}

    await w._check_reschedule(existing, event, FakeSupabase(), org_domain="")

    assert created["n"] == 1, f"recall service must be created once per loop, got {created['n']}"
    assert close_calls["n"] == 1, f"recall client must be closed once, got {close_calls['n']}"
