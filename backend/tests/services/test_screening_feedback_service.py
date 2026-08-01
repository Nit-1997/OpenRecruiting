"""Tests for ScreeningFeedbackService — the AI feedback generator that turns a
screening transcript into a scorecard by reusing the EXISTING feedback pipeline.

The single LLM seam (`_author_assessment`) is monkeypatched to a canned string,
so these tests assert the orchestration: the authored assessment is written to
`candidate_rounds.scorecard_transcript`, and the existing feedback Lambda trigger
is invoked with `skip_prereq_check=True`. The DB boundary is a fluent MagicMock.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.screening_feedback_service import ScreeningFeedbackService

CR_ID = "00000000-0000-0000-0000-0000000000aa"


def _fluent_supabase():
    builder = MagicMock()
    for m in (
        "table",
        "select",
        "update",
        "eq",
        "in_",
        "is_",
        "single",
        "order",
        "limit",
    ):
        getattr(builder, m).return_value = builder
    builder.execute_async = AsyncMock(return_value=MagicMock(data=[]))
    supa = MagicMock()
    supa.table.return_value = builder
    return supa, builder


def _make_feedback_job():
    job = MagicMock()
    job.trigger_feedback_processing = AsyncMock(return_value={"status": "accepted"})
    return job


async def test_generate_writes_scorecard_and_triggers(monkeypatch):
    supa, builder = _fluent_supabase()
    feedback_job = _make_feedback_job()
    svc = ScreeningFeedbackService(db=supa, feedback_job=feedback_job)

    # Stub the load so we don't depend on the exact DB query shape here.
    monkeypatch.setattr(svc, "_load", AsyncMock(return_value={"transcript_text": "x"}))
    monkeypatch.setattr(
        svc, "_author_assessment", AsyncMock(return_value="CANNED ASSESSMENT")
    )
    monkeypatch.setattr(svc, "_compute_authenticity", AsyncMock(return_value={}))

    await svc.generate_and_dispatch(CR_ID)

    # scorecard_transcript written with the authored assessment.
    update_calls = [c.args[0] for c in builder.update.call_args_list]
    assert any(
        payload.get("scorecard_transcript") == "CANNED ASSESSMENT"
        for payload in update_calls
    ), f"scorecard_transcript not written; updates={update_calls}"

    # Existing feedback Lambda triggered with the force/override flag.
    feedback_job.trigger_feedback_processing.assert_awaited_once_with(
        CR_ID, skip_prereq_check=True
    )


async def test_write_scorecard_transcript_scopes_by_id(monkeypatch):
    supa, builder = _fluent_supabase()
    svc = ScreeningFeedbackService(db=supa, feedback_job=_make_feedback_job())

    await svc._write_scorecard_transcript(CR_ID, "ASSESSMENT TEXT")

    builder.update.assert_called_once()
    payload = builder.update.call_args.args[0]
    assert payload["scorecard_transcript"] == "ASSESSMENT TEXT"
    builder.eq.assert_any_call("id", CR_ID)


async def test_author_assessment_is_the_only_llm_seam(monkeypatch):
    """_author_assessment is the mockable seam: generate_and_dispatch never
    touches the Anthropic client directly when it is stubbed."""
    supa, _ = _fluent_supabase()
    feedback_job = _make_feedback_job()
    svc = ScreeningFeedbackService(db=supa, feedback_job=feedback_job)

    monkeypatch.setattr(svc, "_load", AsyncMock(return_value={"transcript_text": "x"}))
    seam = AsyncMock(return_value="ASSESSMENT")
    monkeypatch.setattr(svc, "_author_assessment", seam)
    monkeypatch.setattr(svc, "_compute_authenticity", AsyncMock(return_value={}))

    await svc.generate_and_dispatch(CR_ID)

    seam.assert_awaited_once()
    feedback_job.trigger_feedback_processing.assert_awaited_once()


_CANNED_SIGNALS = {
    "overall": "some_concern",
    "confidence": 0.6,
    "signals": [
        {"kind": "specificity", "level": "low", "note": "Answers stayed generic."},
        {"kind": "read_aloud", "level": "medium", "note": "Cadence felt scripted."},
    ],
    "summary": "Directional: a couple of answers read as rehearsed.",
}


async def test_generate_writes_authenticity_signals(monkeypatch):
    """generate_and_dispatch persists the structured authenticity dict to
    candidate_rounds.authenticity_signals."""
    supa, builder = _fluent_supabase()
    feedback_job = _make_feedback_job()
    svc = ScreeningFeedbackService(db=supa, feedback_job=feedback_job)

    monkeypatch.setattr(svc, "_load", AsyncMock(return_value={"transcript_text": "x"}))
    monkeypatch.setattr(
        svc, "_author_assessment", AsyncMock(return_value="CANNED ASSESSMENT")
    )
    monkeypatch.setattr(
        svc, "_compute_authenticity", AsyncMock(return_value=_CANNED_SIGNALS)
    )

    await svc.generate_and_dispatch(CR_ID)

    update_calls = [c.args[0] for c in builder.update.call_args_list]
    assert any(
        payload.get("authenticity_signals") == _CANNED_SIGNALS
        for payload in update_calls
    ), f"authenticity_signals not written; updates={update_calls}"


async def test_authenticity_failure_does_not_block_scorecard(monkeypatch):
    """A raise inside _compute_authenticity must NOT prevent the scorecard write
    or the Lambda trigger — authenticity is a non-blocking directional signal."""
    supa, builder = _fluent_supabase()
    feedback_job = _make_feedback_job()
    svc = ScreeningFeedbackService(db=supa, feedback_job=feedback_job)

    monkeypatch.setattr(svc, "_load", AsyncMock(return_value={"transcript_text": "x"}))
    monkeypatch.setattr(
        svc, "_author_assessment", AsyncMock(return_value="CANNED ASSESSMENT")
    )
    monkeypatch.setattr(
        svc,
        "_compute_authenticity",
        AsyncMock(side_effect=RuntimeError("LLM exploded")),
    )

    # Must not raise.
    await svc.generate_and_dispatch(CR_ID)

    # Scorecard still written.
    update_calls = [c.args[0] for c in builder.update.call_args_list]
    assert any(
        payload.get("scorecard_transcript") == "CANNED ASSESSMENT"
        for payload in update_calls
    ), f"scorecard_transcript not written; updates={update_calls}"
    # No authenticity payload was persisted (compute failed).
    assert not any(
        "authenticity_signals" in payload for payload in update_calls
    ), f"authenticity_signals should not be written on failure; updates={update_calls}"
    # Lambda still triggered.
    feedback_job.trigger_feedback_processing.assert_awaited_once_with(
        CR_ID, skip_prereq_check=True
    )
