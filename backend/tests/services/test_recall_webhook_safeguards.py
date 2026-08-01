"""BE-A4a webhook-side safeguards for the recall feedback path.

Unit-level coverage for the hardening the May-2026 "Event loop is closed"
audit found, beyond the integration coverage in
tests/api/v2/test_webhooks_recall.py:

  - partial_feedback: the last-20%-of-segments fallback must NOT mark a
    short interview `ready` when there is no real feedback_start_offset.
  - recording_handler._decide_feedback_path: the enqueue must be gated on
    the SAME source readiness was computed from (stored segments), not the
    freshly-fetched transcript_data which can be None.
  - recall_service.schedule_or_replace_recall_bot: the cancel loop must
    tolerate a transient (non-HTTPStatus) Recall error and still mark the
    bot cancelled in DB.
  - notifications.notify_bot_not_admitted: a failure to revert the CAS
    marker must be logged at WARNING, never silently swallowed.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.services.recall_webhook import partial_feedback


# ---------------------------------------------------------------------------
# partial_feedback — last-20% fallback requires a real offset
# ---------------------------------------------------------------------------


def _seg(name: str, text: str) -> dict:
    return {"participant": {"name": name}, "text": text}


def test_partial_feedback_fallback_not_ready_without_offset():
    """No feedback_start_offset → the last-20% heuristic must NOT mark the
    transcript ready. A short interview where the interviewer happens to
    speak last would otherwise mis-fire the Lambda."""
    segments = [
        _seg("Candidate", "I think the answer is forty two and here is why."),
        _seg("Jane Interviewer", "Great, thanks for explaining that so clearly."),
    ]
    ready, source, turns, chars = partial_feedback.is_meaningful_partial_feedback(
        feedback_transcript=None,
        fallback_segments=segments,
        feedback_start_seconds=None,
        candidate_names={"candidate"},
    )
    assert ready is False
    assert source == "segments_fallback"


def test_partial_feedback_ready_with_real_offset():
    """With a real offset, segments after it count and can mark ready —
    the guard only suppresses the no-offset heuristic path."""
    long_feedback = (
        "Strong communication and clear structured thinking throughout the "
        "interview. The candidate handled the system design portion confidently, "
        "asked sharp clarifying questions, and would comfortably advance to the "
        "onsite round in my assessment."
    )
    assert len(long_feedback) >= 150
    segments = [
        {
            "participant": {"name": "Jane Interviewer"},
            "text": long_feedback,
            "start_timestamp": {"relative": 100.0},
        },
    ]
    ready, source, turns, chars = partial_feedback.is_meaningful_partial_feedback(
        feedback_transcript=None,
        fallback_segments=segments,
        feedback_start_seconds=50.0,
        candidate_names={"candidate"},
    )
    assert ready is True
    assert source == "segments_fallback"
    assert turns >= 1


# ---------------------------------------------------------------------------
# recording_handler._decide_feedback_path — gate on the computed source
# ---------------------------------------------------------------------------


class _FakeQuery:
    """Minimal chainable supabase query stub. Resolves to a canned response
    keyed by table name when execute_async is awaited."""

    def __init__(self, responder, table):
        self._responder = responder
        self._table = table

    def __getattr__(self, _name):
        # select/eq/single/update/in_ all return self (chainable, no-op).
        def _chain(*_a, **_k):
            return self
        return _chain

    async def execute_async(self):
        return self._responder(self._table)


class _FakeSupabase:
    def __init__(self, responder):
        self._responder = responder

    def table(self, name):
        return _FakeQuery(self._responder, name)


@pytest.mark.asyncio
async def test_decide_feedback_path_fires_lambda_from_stored_segments_only():
    """transcript_data fetched from Recall is None, but stored
    transcripts.segments hold real interviewer feedback. The Lambda MUST
    still fire — readiness is computed from the stored segments, so the
    enqueue must gate on that same source, not the (None) fetched data."""
    from app.services.recall_webhook import recording_handler

    now = datetime.now(timezone.utc)
    joined = now.isoformat()
    fb_started = now.replace(microsecond=0).isoformat()

    segments = [
        {
            "participant": {"name": "Jane Interviewer"},
            "text": (
                "Excellent candidate, very strong on system design and tradeoff "
                "analysis. Communicated clearly, drove the conversation, and asked "
                "thoughtful questions about scale. I would advance them straight to "
                "the onsite loop without hesitation."
            ),
            "start_timestamp": {"relative": 5.0},
        },
    ]

    def responder(table):
        if table == "recall_bots":
            return MagicMock(data={
                "feedback_started_at": fb_started,
                "feedback_status": "completed",
                "joined_at": joined,
                "scheduled_at": joined,
                "candidate_name": "Bob Candidate",
                "detected_candidate_participant_id": None,
                "tracked_participants": [
                    {"id": 1, "name": "Jane Interviewer", "is_host": True},
                ],
            })
        if table == "transcripts":
            return MagicMock(data={
                "feedback_transcript": None,
                "segments": segments,
            })
        if table == "candidate_rounds":
            return MagicMock(data={"candidates": {"name": "Bob Candidate"}})
        return MagicMock(data=None)

    supabase = _FakeSupabase(responder)

    async def _verdict(*_a, **_k):
        from app.services.recall_webhook.end_state import EndStateVerdict
        # A real interview (candidate participated) that has ended — NOT a
        # no-show, so the feedback gate runs.
        return EndStateVerdict("ended", 0.95, False, "interview ended", "guardrail:call_ended")

    with patch.object(
        recording_handler.end_state, "evaluate_end_state", new=_verdict
    ), patch.object(
        recording_handler, "_trigger_feedback_lambda", new=AsyncMock()
    ) as trigger, patch.object(
        recording_handler, "_send_add_feedback_emails", new=AsyncMock()
    ) as emails:
        await recording_handler._decide_feedback_path(
            supabase,
            candidate_round_id="cr-1",
            db_record_id="bot-1",
            transcript_data=None,  # Recall fetch came back empty.
        )

    trigger.assert_awaited_once()
    emails.assert_not_awaited()


# ---------------------------------------------------------------------------
# recall_service cancel loop — tolerate transient (non-HTTPStatus) errors
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cancel_loop_tolerates_transient_error_and_marks_cancelled(monkeypatch):
    """A ConnectError/timeout from Recall during bot cancellation must not
    propagate — the bot is still marked cancelled in DB (the comment in the
    loop promises this) and scheduling continues."""
    from app.services import recall_service as rs

    cancelled_ids: list[str] = []

    # Supabase stub: first lock acquire succeeds, then the active-bot select
    # returns one bot, then the cancelled-mark update records the id, then
    # the new-bot insert + lock release succeed.
    class _SbQuery:
        def __init__(self, sb, table):
            self._sb = sb
            self._table = table
            self._op = "select"
            self._update_payload = None

        def select(self, *_a, **_k):
            self._op = "select"
            return self

        def update(self, payload):
            self._op = "update"
            self._update_payload = payload
            return self

        def insert(self, *_a, **_k):
            self._op = "insert"
            return self

        def eq(self, *_a, **_k):
            return self

        def in_(self, *_a, **_k):
            return self

        def is_(self, *_a, **_k):
            return self

        async def execute_async(self):
            if self._table == "recall_bots":
                if self._op == "select":
                    return MagicMock(data=[{
                        "id": "bot-db-1",
                        "recall_bot_id": "recall-1",
                        "status": "joining",
                    }])
                if self._op == "update":
                    cancelled_ids.append(self._update_payload.get("status"))
                    return MagicMock(data=[{}])
                return MagicMock(data=[{}])
            # candidate_rounds: lock acquire / release.
            if self._table == "candidate_rounds":
                if self._op == "update":
                    return MagicMock(data=[{"id": "cr-1"}])
                return MagicMock(data=[{}])
            return MagicMock(data=[{}])

    class _Sb:
        def table(self, name):
            return _SbQuery(self, name)

    monkeypatch.setattr(rs, "get_supabase_admin_client", lambda: _Sb(), raising=False)
    # Patch the supabase module the function actually imports.
    import app.services.supabase as supabase_module
    monkeypatch.setattr(supabase_module, "get_supabase_admin_client", lambda: _Sb())

    # Recall service: leave_call raises a transient ConnectError.
    fake_recall = MagicMock()
    fake_recall.remove_bot_from_call = AsyncMock(
        side_effect=httpx.ConnectError("connection refused")
    )
    fake_recall.delete_bot = AsyncMock(return_value=True)
    fake_recall.schedule_bot = AsyncMock(return_value={"id": "new-bot", "bot_name": "OpenRecruiting"})
    fake_recall.close = AsyncMock()
    monkeypatch.setattr(rs, "get_recall_service", lambda: fake_recall)

    # Must NOT raise.
    result = await rs.schedule_or_replace_recall_bot(
        candidate_round_id="cr-1",
        meeting_url="https://meet.google.com/test",
        scheduled_at=datetime.now(timezone.utc),
        candidate_name="Bob",
    )

    assert result["recall_warning"] is None
    # Bot was marked cancelled in DB despite the transient leave_call error.
    assert "cancelled" in cancelled_ids


# ---------------------------------------------------------------------------
# notifications — CAS revert failure is logged, not swallowed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_not_admitted_revert_failure_is_logged(monkeypatch, caplog):
    """When sending the not-admitted alert fails AND the CAS-marker revert
    ALSO fails, the revert failure must be logged at WARNING — never a bare
    `except: pass`."""
    from app.services.recall_webhook import notifications

    class _SbQuery:
        def __init__(self, calls):
            self._calls = calls
            self._is_revert = False

        def update(self, payload):
            # The revert flips error_code back to 'fatal'.
            self._is_revert = payload.get("error_code") == "fatal"
            return self

        def eq(self, *_a, **_k):
            return self

        def neq(self, *_a, **_k):
            return self

        async def execute_async(self):
            self._calls.append("execute")
            if self._is_revert:
                raise RuntimeError("db down during revert")
            # The initial CAS acquire succeeds (returns a row).
            return MagicMock(data=[{"id": "bot-db-1"}])

    calls: list[str] = []

    class _Sb:
        def table(self, _name):
            return _SbQuery(calls)

    monkeypatch.setattr(notifications, "get_supabase_admin_client", lambda: _Sb())
    # Force _send_notifications to fail so the revert path runs.
    monkeypatch.setattr(
        notifications,
        "_send_notifications",
        AsyncMock(side_effect=RuntimeError("email service down")),
    )

    import logging

    with caplog.at_level(logging.WARNING):
        await notifications.notify_bot_not_admitted({"id": "bot-db-1", "candidate_round_id": "cr-1"})

    # The revert failure produced a WARNING-or-higher log record mentioning revert.
    assert any(
        "revert" in r.getMessage().lower() and r.levelno >= logging.WARNING
        for r in caplog.records
    ), [r.getMessage() for r in caplog.records]
