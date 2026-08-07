"""Tests for _run_force_publish_job's terminal-state selector.

Locks in fix #3 from the adversarial review: when process_org_now returns
errors, the job MUST NOT be marked 'completed'. The original implementation
unconditionally called mark_completed, making Neo4j/Supabase outages look green
to status pollers.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.controller.ingestion_controller import _run_force_publish_job


def _make_jobs() -> MagicMock:
    jobs = MagicMock()
    jobs.mark_running = AsyncMock()
    jobs.update_progress = AsyncMock()
    jobs.mark_completed = AsyncMock()
    jobs.mark_partial = AsyncMock()
    jobs.mark_failed = AsyncMock()
    return jobs


def _make_cron(result: dict) -> MagicMock:
    cron = MagicMock()
    cron.process_org_now = AsyncMock(return_value=result)
    return cron


@pytest.mark.asyncio
async def test_terminal_completed_when_no_errors():
    cron = _make_cron({"scanned": 5, "published": 5, "batches": 1, "errors": []})
    jobs = _make_jobs()

    await _run_force_publish_job("job-1", "org-1", cron, jobs)

    jobs.mark_completed.assert_awaited_once_with(
        "job-1", scanned=5, published=5, batches=1, errors=[]
    )
    jobs.mark_partial.assert_not_called()
    jobs.mark_failed.assert_not_called()


@pytest.mark.asyncio
async def test_terminal_partial_when_some_published_and_some_errors():
    cron = _make_cron({
        "scanned": 10,
        "published": 7,
        "batches": 1,
        "errors": ["event_pk=ev-3: neo4j timeout"],
    })
    jobs = _make_jobs()

    await _run_force_publish_job("job-1", "org-1", cron, jobs)

    jobs.mark_partial.assert_awaited_once()
    kwargs = jobs.mark_partial.call_args.kwargs
    assert kwargs["scanned"] == 10
    assert kwargs["published"] == 7
    assert kwargs["batches"] == 1
    assert len(kwargs["errors"]) == 1
    jobs.mark_completed.assert_not_called()
    jobs.mark_failed.assert_not_called()


@pytest.mark.asyncio
async def test_terminal_failed_when_nothing_published_but_errors():
    """Neo4j/Supabase outage scenario: every row failed → must not be
    'completed'. Regression for the adversarial review's fix #3."""
    cron = _make_cron({
        "scanned": 4,
        "published": 0,
        "batches": 1,
        "errors": [
            "event_pk=ev-1: neo4j unavailable",
            "event_pk=ev-2: neo4j unavailable",
            "event_pk=ev-3: neo4j unavailable",
            "event_pk=ev-4: neo4j unavailable",
        ],
    })
    jobs = _make_jobs()

    await _run_force_publish_job("job-1", "org-1", cron, jobs)

    jobs.mark_failed.assert_awaited_once()
    fail_args = jobs.mark_failed.call_args.args
    assert fail_args[0] == "job-1"
    summary = fail_args[1]
    assert "All 4 eligible rows failed" in summary
    assert "neo4j unavailable" in summary
    jobs.mark_completed.assert_not_called()
    jobs.mark_partial.assert_not_called()


@pytest.mark.asyncio
async def test_unexpected_exception_marks_failed():
    cron = MagicMock()
    cron.process_org_now = AsyncMock(side_effect=RuntimeError("network died"))
    jobs = _make_jobs()

    await _run_force_publish_job("job-1", "org-1", cron, jobs)

    jobs.mark_failed.assert_awaited_once()
    assert "network died" in jobs.mark_failed.call_args.args[1]
