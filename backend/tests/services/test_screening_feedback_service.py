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


# --------------------------------------------------------------------------- #
# The two LLM seams, tested directly against FakeLLM. Every test above mocks
# them out, so these are the only tests of their bodies.
# --------------------------------------------------------------------------- #
import logging  # noqa: E402

from llm_core.errors import LLMError  # noqa: E402

import app.services.screening_feedback_service as feedback_module  # noqa: E402

FORCED_AUTHENTICITY = {
    "type": "function",
    "function": {"name": "emit_authenticity_signals"},
}

_CTX = {
    "role": {"role_title": "Backend Engineer"},
    "transcript_text": "Q: tell me about an incident. A: we lost the primary db.",
}


def _svc(fake_llm, monkeypatch):
    monkeypatch.setattr(feedback_module, "get_llm_client", lambda: fake_llm)
    supa, _ = _fluent_supabase()
    return ScreeningFeedbackService(db=supa, feedback_job=_make_feedback_job())


async def test_author_assessment_returns_the_reply_text(fake_llm, monkeypatch):
    """Site 8 — the one call in this phase that reads prose, not a tool call.
    LLMReply.text is the joined text of every block, which is what the old
    content loop built by hand."""
    svc = _svc(fake_llm, monkeypatch)
    fake_llm.queue_text("  ## Assessment\n\nStrong incident response.  ")

    out = await svc._author_assessment(_CTX)

    assert out == "## Assessment\n\nStrong incident response."


async def test_author_assessment_sends_no_tools_at_all(fake_llm, monkeypatch):
    """It asks for prose, so supplying tools — or a tool_choice — would be wrong.
    llm_core rejects a tool_choice without tools, so this is load-bearing."""
    svc = _svc(fake_llm, monkeypatch)
    fake_llm.queue_text("text")

    await svc._author_assessment(_CTX)

    call = fake_llm.calls[0]
    assert call["model"] == "screening-assessor"   # was "claude-sonnet-4-6"
    assert call["max_tokens"] == 2000
    assert call.get("tools") is None
    assert call.get("tool_choice") is None


async def test_compute_authenticity_normalizes_the_tool_arguments(fake_llm, monkeypatch):
    svc = _svc(fake_llm, monkeypatch)
    fake_llm.queue_tool_call(
        "emit_authenticity_signals",
        {
            "overall": "some_concern",
            "confidence": 0.62,
            "signals": [
                {"kind": "specificity", "level": "medium", "note": "few concrete numbers"}
            ],
        },
    )

    out = await svc._compute_authenticity(_CTX)

    assert out["overall"] == "some_concern"
    assert out["confidence"] == 0.62


async def test_compute_authenticity_forces_its_tool(fake_llm, monkeypatch):
    svc = _svc(fake_llm, monkeypatch)
    fake_llm.queue_tool_call("emit_authenticity_signals", {"overall": "likely_authentic"})

    await svc._compute_authenticity(_CTX)

    call = fake_llm.calls[0]
    assert call["model"] == "screening-assessor"
    assert call["max_tokens"] == 1200
    assert call["tool_choice"] == FORCED_AUTHENTICITY
    assert call["tools"][0]["type"] == "function"
    assert call["tools"][0]["function"]["name"] == "emit_authenticity_signals"


async def test_compute_authenticity_logs_a_missing_tool_call(fake_llm, monkeypatch, caplog):
    """{} is also the caller's "nothing worth flagging" result, so a degraded
    reply is otherwise indistinguishable from a clean transcript — and this
    output reaches a hiring panel.

    This module logs through app.logging_config.get_logger (stdlib), not
    structlog, so the assertion goes through caplog.
    """
    svc = _svc(fake_llm, monkeypatch)
    fake_llm.queue_text("The candidate seemed genuine to me.")

    with caplog.at_level(logging.WARNING, logger=feedback_module.__name__):
        out = await svc._compute_authenticity(_CTX)

    assert out == {}
    assert "authenticity_no_tool_call" in caplog.text


async def test_a_truncated_call_never_fabricates_an_authenticity_verdict(
    fake_llm, monkeypatch
):
    """The one that must not regress.

    A named call whose argument JSON was truncated arrives as arguments={}.
    Every branch of _normalize_authenticity has a default, so an empty payload
    used to normalize into a COMPLETE, truthy verdict of
    overall='likely_authentic' — which generate_and_dispatch persists to
    candidate_rounds.authenticity_signals and renders to a hiring panel. An
    invented affirmative reading of a real candidate is the worst thing a
    degraded reply here can produce.
    """
    svc = _svc(fake_llm, monkeypatch)
    fake_llm.queue_tool_call("emit_authenticity_signals", {})

    out = await svc._compute_authenticity(_CTX)

    assert out == {}, "an empty payload must not become a 'likely_authentic' verdict"


async def test_a_partial_payload_still_gets_its_defaults(fake_llm, monkeypatch):
    """The empty-payload guard must not swallow a genuine partial reply — the
    defaults exist for model wordings that miss a field, and that is unchanged."""
    svc = _svc(fake_llm, monkeypatch)
    fake_llm.queue_tool_call(
        "emit_authenticity_signals", {"summary": "Answers were concrete."}
    )

    out = await svc._compute_authenticity(_CTX)

    assert out["summary"] == "Answers were concrete."
    assert out["overall"] == "likely_authentic"
    assert out["confidence"] == 0.0


async def test_compute_authenticity_does_not_swallow_gateway_errors(fake_llm, monkeypatch):
    """generate_and_dispatch owns the fallback — a raise here must not block the
    scorecard write, which the test above already pins."""
    svc = _svc(fake_llm, monkeypatch)
    fake_llm.queue_error(LLMError("gateway 500", alias="screening-assessor", status=500))

    with pytest.raises(LLMError):
        await svc._compute_authenticity(_CTX)


async def test_no_transcript_text_reaches_the_degraded_log_line(fake_llm, monkeypatch, caplog):
    """Transcripts carry candidate speech. A degraded-shape log describes shape."""
    svc = _svc(fake_llm, monkeypatch)
    secret = "My salary at Acme was 190000 and my manager was Dana."
    fake_llm.queue_text(secret)

    with caplog.at_level(logging.WARNING, logger=feedback_module.__name__):
        await svc._compute_authenticity({"role": {}, "transcript_text": secret})

    assert secret not in caplog.text
