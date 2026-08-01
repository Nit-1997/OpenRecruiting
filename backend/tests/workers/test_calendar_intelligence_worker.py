import asyncio
import pytest


def test_worker_imports_and_entrypoints_present():
    import app.workers.calendar_intelligence_worker as w
    for sym in ("poll_and_detect", "process_orphan_reminders", "cleanup_expired_detections",
                "send_prep_reminders", "enqueue_calendar_sync_hint", "process_calendar_sync_hint",
                "run_calendar_intelligence_loops", "run_deferred_backfill", "_interval_loop"):
        assert hasattr(w, sym), f"missing {sym}"
    assert not hasattr(w, "register_scheduler"), "register_scheduler should be removed"


@pytest.mark.asyncio
async def test_run_loops_noop_when_disabled(monkeypatch):
    import app.workers.calendar_intelligence_worker as w
    class _S:
        CALENDAR_INTELLIGENCE_ENABLED = False
    monkeypatch.setattr(w, "get_settings", lambda: _S())
    await asyncio.wait_for(w.run_calendar_intelligence_loops(), timeout=2.0)


@pytest.mark.asyncio
async def test_interval_loop_runs_job_then_cancels(monkeypatch):
    import app.workers.calendar_intelligence_worker as w
    real_sleep = asyncio.sleep
    # Floor the loop's sleep to a yield so iteration is fast and deterministic
    # (the real floor is now max(5, interval); tests must not wall-clock wait).
    monkeypatch.setattr(w.asyncio, "sleep", lambda d: real_sleep(0))
    calls = {"n": 0}
    async def job():
        calls["n"] += 1
    task = asyncio.create_task(w._interval_loop("test", job, 0.01))
    await real_sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert calls["n"] >= 1


@pytest.mark.asyncio
async def test_interval_loop_survives_job_exception(monkeypatch):
    import app.workers.calendar_intelligence_worker as w
    real_sleep = asyncio.sleep
    monkeypatch.setattr(w.asyncio, "sleep", lambda d: real_sleep(0))
    calls = {"n": 0}
    async def job():
        calls["n"] += 1
        raise RuntimeError("boom")
    task = asyncio.create_task(w._interval_loop("test", job, 0.01))
    await real_sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert calls["n"] >= 2
