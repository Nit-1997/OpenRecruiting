"""Regression: candidate no-show where the interviewer (host) shares the
candidate's name 'Nitin Bhat'. Must end + complete the round + NOT fire the
Lambda (no junk packet), so 'Request feedback' becomes available.

This is the exact f5bac7e2 production scenario: the sole speaker is the host
"Nitin Bhat", whose name equals the candidate's name, and the candidate never
joined. The name-collision must NOT mask the no-show, and the no-show must NOT
fire the feedback Lambda — the round just completes so the recruiter can
request feedback manually.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.recall_webhook import recording_handler
from app.services.recall_webhook.end_state import EndStateVerdict


SEGMENTS = [{
    "participant": {"id": 100, "name": "Nitin Bhat", "is_host": True},
    "words": [{"text": w, "start_timestamp": {"relative": 12.0}} for w in
              ("strong no candidate did not join no scalability reasoning no trade off "
               "analysis no design communication it is a strong no from my end".split())],
}]


class _FakeSupabase:
    """Per-table fake for `_decide_feedback_path`. Returns canned rows for the
    recall_bots + transcripts `.single()` reads, and records the
    candidate_round_id of the guarded completion write into `completed_cr`."""

    def __init__(self, bot, transcript):
        self._bot = bot
        self._transcript = transcript
        self.completed_cr = None

    def table(self, name):
        outer = self
        builder = MagicMock()
        for attr in ("select", "single"):
            setattr(builder, attr, MagicMock(return_value=builder))

        if name == "recall_bots":
            builder.eq = MagicMock(return_value=builder)
            builder.execute_async = AsyncMock(return_value=MagicMock(data=outer._bot))
        elif name == "transcripts":
            builder.eq = MagicMock(return_value=builder)
            builder.execute_async = AsyncMock(return_value=MagicMock(data=outer._transcript))
        elif name == "candidate_rounds":
            state = {"payload": {}, "id": None}

            def _update(payload):
                state["payload"].update(payload)
                return builder

            def _eq(col, val):
                if col == "id":
                    state["id"] = val
                return builder

            builder.update = MagicMock(side_effect=_update)
            builder.eq = MagicMock(side_effect=_eq)

            async def _exec():
                # Mirror the guarded .eq("status","in_progress") completion write.
                if state["payload"].get("status") == "completed":
                    outer.completed_cr = state["id"]
                return MagicMock(data={})

            builder.execute_async = AsyncMock(side_effect=_exec)
        else:
            builder.eq = MagicMock(return_value=builder)
            builder.execute_async = AsyncMock(return_value=MagicMock(data={}))
        return builder


@pytest.fixture
def fake_supabase_factory():
    def _make(bot, transcript):
        return _FakeSupabase(bot, transcript)
    return _make


@pytest.mark.asyncio
async def test_f5bac7e2_no_show_completes_without_lambda(monkeypatch, fake_supabase_factory):
    supabase = fake_supabase_factory(
        bot={
            "feedback_status": "completed",
            "feedback_started_at": "2026-06-03T01:30:49Z",
            "joined_at": "2026-06-03T01:30:41Z",
            "scheduled_at": "2026-06-03T01:30:41Z",
            "candidate_name": "Nitin Bhat",
            "detected_candidate_participant_id": None,
            "tracked_participants": [
                {"id": 100, "name": "Nitin Bhat", "is_host": True, "left_at": "t"},
            ],
        },
        transcript={"feedback_transcript": None, "segments": SEGMENTS},
    )

    async def _verdict(*a, **k):
        # No real LLM/network call: the call_ended guardrail verdict for the
        # no-show case (sole host speaker, candidate never joined).
        return EndStateVerdict("ended", 0.9, True, "interviewer reports no-show", "guardrail:call_ended")
    monkeypatch.setattr(recording_handler.end_state, "evaluate_end_state", _verdict)

    fired = {"lambda": False}

    async def _lambda(s, cr):
        fired["lambda"] = True

    async def _emails(cr):
        pass

    monkeypatch.setattr(recording_handler, "_trigger_feedback_lambda", _lambda)
    monkeypatch.setattr(recording_handler, "_send_add_feedback_emails", _emails)

    await recording_handler._decide_feedback_path(supabase, "f5bac7e2", "bot-db", None)

    assert fired["lambda"] is False           # no junk packet for a no-show
    assert supabase.completed_cr == "f5bac7e2"  # round completed -> Request feedback shows
