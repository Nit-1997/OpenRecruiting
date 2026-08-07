from unittest.mock import AsyncMock, MagicMock

import pytest
from postgrest.exceptions import APIError

from src.service.force_publish_job_service import (
    UNIQUE_VIOLATION_PG_CODE,
    ForcePublishJobService,
    STALE_RUNNING_THRESHOLD_MINUTES,
)


@pytest.fixture
def supabase():
    c = MagicMock()
    c.table = MagicMock(return_value=c)
    c.select = MagicMock(return_value=c)
    c.insert = MagicMock(return_value=c)
    c.update = MagicMock(return_value=c)
    c.eq = MagicMock(return_value=c)
    c.in_ = MagicMock(return_value=c)
    c.lt = MagicMock(return_value=c)
    c.order = MagicMock(return_value=c)
    c.limit = MagicMock(return_value=c)
    c.maybe_single = MagicMock(return_value=c)
    c.execute = AsyncMock()
    return c


def _unique_violation() -> APIError:
    return APIError({
        "code": UNIQUE_VIOLATION_PG_CODE,
        "message": "duplicate key value violates unique constraint",
        "details": "Key (org_id)=(org-1) already exists.",
        "hint": "",
    })


@pytest.mark.asyncio
async def test_create_or_409_returns_new_id_when_insert_succeeds(supabase):
    # New flow is INSERT-first (race-free at DB boundary):
    #   1) _recover_stale_running update → empty
    #   2) insert → succeeds
    supabase.execute.side_effect = [
        MagicMock(data=[]),
        MagicMock(data=[{"id": "doesnt-matter"}]),
    ]
    svc = ForcePublishJobService(supabase)

    job_id, created = await svc.create_or_409("org-1")

    assert created is True
    assert job_id
    supabase.insert.assert_called_once()
    insert_payload = supabase.insert.call_args.args[0]
    assert insert_payload["org_id"] == "org-1"
    assert insert_payload["status"] == "pending"


@pytest.mark.asyncio
async def test_create_or_409_handles_unique_violation_race(supabase):
    """The race-free guarantee: the partial unique index makes concurrent
    INSERTs lose with Postgres 23505. We catch that and resolve to the
    winning row's id rather than spawning a duplicate publish loop."""
    supabase.execute.side_effect = [
        MagicMock(data=[]),          # _recover_stale_running update
        _unique_violation(),         # insert raises 23505
        MagicMock(data=[{           # find_active sees the winner
            "id": "winning-job-id",
            "status": "pending",
            "scanned": 0,
            "published": 0,
            "batches": 0,
            "started_at": "2026-05-09T00:00:00+00:00",
            "updated_at": "2026-05-09T00:00:00+00:00",
        }]),
    ]
    svc = ForcePublishJobService(supabase)

    job_id, created = await svc.create_or_409("org-1")

    assert created is False
    assert job_id == "winning-job-id"


@pytest.mark.asyncio
async def test_create_or_409_reraises_non_unique_api_errors(supabase):
    """Don't swallow real DB errors — only 23505 means 'someone else won the
    race'. An RLS denial, syntax error, or anything else should bubble up so
    the operator sees it."""
    rls_err = APIError({
        "code": "42501",
        "message": "permission denied",
        "details": "",
        "hint": "",
    })
    supabase.execute.side_effect = [
        MagicMock(data=[]),  # _recover_stale_running update
        rls_err,             # insert raises a non-23505 error
    ]
    svc = ForcePublishJobService(supabase)

    with pytest.raises(APIError) as exc_info:
        await svc.create_or_409("org-1")
    assert exc_info.value.code == "42501"


@pytest.mark.asyncio
async def test_create_or_409_reraises_when_winner_disappears(supabase):
    """Defensive: 23505 fired but find_active returns nothing. Don't fabricate
    a fake success — re-raise so the caller doesn't silently lose the request."""
    supabase.execute.side_effect = [
        MagicMock(data=[]),  # _recover_stale_running
        _unique_violation(),  # insert loses race
        MagicMock(data=[]),  # find_active sees nothing
    ]
    svc = ForcePublishJobService(supabase)

    with pytest.raises(APIError):
        await svc.create_or_409("org-1")


@pytest.mark.asyncio
async def test_recover_stale_runs_before_insert(supabase):
    supabase.execute.side_effect = [
        MagicMock(data=[{"id": "stale-1"}]),  # stale recovery update
        MagicMock(data=[]),                   # insert succeeds
    ]
    svc = ForcePublishJobService(supabase)

    job_id, created = await svc.create_or_409("org-1")

    assert created is True
    # Stale recovery filtered for active statuses and old updated_at.
    supabase.in_.assert_any_call("status", ["pending", "running"])
    lt_calls = [c for c in supabase.lt.call_args_list if c.args[0] == "updated_at"]
    assert lt_calls, "expected lt('updated_at', cutoff) for stale recovery"


@pytest.mark.asyncio
async def test_update_progress_writes_counters(supabase):
    supabase.execute.return_value = MagicMock(data=[])
    svc = ForcePublishJobService(supabase)

    await svc.update_progress("job-1", scanned=500, published=480, batches=5)

    supabase.update.assert_called_once()
    update_payload = supabase.update.call_args.args[0]
    assert update_payload["scanned"] == 500
    assert update_payload["published"] == 480
    assert update_payload["batches"] == 5
    assert "updated_at" in update_payload
    supabase.eq.assert_any_call("id", "job-1")


@pytest.mark.asyncio
async def test_mark_completed_sets_terminal_state(supabase):
    supabase.execute.return_value = MagicMock(data=[])
    svc = ForcePublishJobService(supabase)

    await svc.mark_completed(
        "job-1", scanned=10, published=10, batches=1, errors=[]
    )

    update_payload = supabase.update.call_args.args[0]
    assert update_payload["status"] == "completed"
    assert update_payload["completed_at"] is not None
    assert update_payload["scanned"] == 10
    assert update_payload["errors"] == []


@pytest.mark.asyncio
async def test_mark_partial_sets_partial_terminal_state(supabase):
    """`partial` is distinct from `completed` and `failed` — caller should be
    able to tell 'some rows published, some failed' apart from full success
    and full failure."""
    supabase.execute.return_value = MagicMock(data=[])
    svc = ForcePublishJobService(supabase)

    await svc.mark_partial(
        "job-1", scanned=10, published=7, batches=1,
        errors=["event_pk=ev-3: neo4j timeout", "event_pk=ev-5: neo4j timeout"],
    )

    update_payload = supabase.update.call_args.args[0]
    assert update_payload["status"] == "partial"
    assert update_payload["completed_at"] is not None
    assert update_payload["scanned"] == 10
    assert update_payload["published"] == 7
    assert len(update_payload["errors"]) == 2


@pytest.mark.asyncio
async def test_mark_failed_truncates_long_messages(supabase):
    supabase.execute.return_value = MagicMock(data=[])
    svc = ForcePublishJobService(supabase)

    huge = "x" * 5000
    await svc.mark_failed("job-1", huge)

    update_payload = supabase.update.call_args.args[0]
    assert update_payload["status"] == "failed"
    assert len(update_payload["error_message"]) == 500


@pytest.mark.asyncio
async def test_get_returns_row_when_present(supabase):
    supabase.execute.return_value = MagicMock(data={
        "id": "job-1",
        "org_id": "org-1",
        "status": "completed",
        "scanned": 10,
        "published": 10,
        "batches": 1,
        "errors": [],
        "started_at": "2026-05-09T00:00:00+00:00",
        "updated_at": "2026-05-09T00:01:00+00:00",
        "completed_at": "2026-05-09T00:01:00+00:00",
    })
    svc = ForcePublishJobService(supabase)

    row = await svc.get("job-1")

    assert row is not None
    assert row["id"] == "job-1"
    assert row["status"] == "completed"


@pytest.mark.asyncio
async def test_get_returns_none_when_missing(supabase):
    supabase.execute.return_value = MagicMock(data=None)
    svc = ForcePublishJobService(supabase)

    row = await svc.get("nope")

    assert row is None


def test_stale_threshold_is_exposed_for_visibility():
    # Guards against accidentally dropping the threshold to 0 — which would
    # mark every fresh job as stale immediately.
    assert STALE_RUNNING_THRESHOLD_MINUTES >= 1
