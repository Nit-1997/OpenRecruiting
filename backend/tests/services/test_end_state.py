from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.recall_webhook import end_state
from app.services.recall_webhook.end_state import EndStateVerdict, evaluate_end_state


def test_coerce_confidence_handles_non_numeric_and_clamps():
    # Non-numeric / None -> safe default 0.0 (never raises).
    assert end_state._coerce_confidence("high") == 0.0
    assert end_state._coerce_confidence(None) == 0.0
    assert end_state._coerce_confidence("") == 0.0
    # Numeric (incl. numeric strings) parsed; out-of-range clamped to [0, 1].
    assert end_state._coerce_confidence("0.8") == 0.8
    assert end_state._coerce_confidence(0.5) == 0.5
    assert end_state._coerce_confidence(5) == 1.0
    assert end_state._coerce_confidence(-2) == 0.0


@pytest.mark.asyncio
async def test_evaluate_end_state_survives_non_numeric_confidence(monkeypatch):
    """A valid LLM JSON verdict with a non-numeric confidence must NOT raise past
    the failsafe — it yields a verdict with confidence coerced to 0.0."""
    monkeypatch.setattr(
        end_state,
        "_llm_judge",
        AsyncMock(return_value={"phase": "ended", "confidence": "high", "is_no_show": False, "reasoning": "x"}),
    )
    verdict = await evaluate_end_state(
        recall_bot={"joined_at": "2026-06-03T01:00:00Z", "scheduled_at": "2026-06-03T01:00:00Z"},
        tracked_participants=[],
        transcript_text="",
        trigger="call_ended",
    )
    assert verdict.confidence == 0.0
    assert verdict.phase == "ended"


HOST = {"id": 100, "name": "Bob Interviewer", "is_host": True, "left_at": "2026-06-03T01:31:00Z"}
CAND = {"id": 200, "name": "Alice Candidate", "is_host": False, "left_at": "2026-06-03T01:30:50Z"}


def _bot(**over):
    base = {
        "joined_at": "2026-06-03T01:00:00Z",
        "scheduled_at": "2026-06-03T01:00:00Z",
        "candidate_name": "Alice Candidate",
        "detected_candidate_participant_id": 200,
        "tracked_participants": [HOST, CAND],
    }
    base.update(over)
    return base


@pytest.fixture
def stub_llm(monkeypatch):
    calls = {}

    def _set(verdict_dict):
        async def _fake(prompt, settings):
            calls["prompt"] = prompt
            return verdict_dict
        monkeypatch.setattr(end_state, "_llm_judge", _fake)
        return calls

    return _set


@pytest.mark.asyncio
async def test_drop_early_returns_mid_no_trigger(stub_llm):
    stub_llm({"phase": "mid", "confidence": 0.9, "is_no_show": False, "reasoning": "early small talk"})
    v = await evaluate_end_state(_bot(), [HOST, CAND], "Bob: hi\nAlice: hi", "candidate_drop")
    assert v.phase == "mid"
    assert v.source == "llm"


@pytest.mark.asyncio
async def test_drop_wrapping_up_returns_ended(stub_llm):
    stub_llm({"phase": "wrapping_up", "confidence": 0.95, "is_no_show": False, "reasoning": "closing"})
    v = await evaluate_end_state(_bot(), [HOST, CAND], "Bob: any questions for me?", "candidate_drop")
    assert v.phase == "wrapping_up"
    assert v.confidence == 0.95


@pytest.mark.asyncio
async def test_rejoin_guardrail_short_circuits_llm(stub_llm):
    calls = stub_llm({"phase": "ended", "confidence": 1.0, "is_no_show": False, "reasoning": "x"})
    rejoined = {**CAND, "left_at": None}  # candidate came back
    v = await evaluate_end_state(_bot(tracked_participants=[HOST, rejoined]), [HOST, rejoined],
                                 "irrelevant", "candidate_drop", dropped_participant_id=200)
    assert v.phase == "mid"
    assert v.source == "guardrail:rejoin"
    assert "prompt" not in calls  # LLM never called


@pytest.mark.asyncio
async def test_call_ended_forces_ended_keeps_is_no_show(stub_llm):
    stub_llm({"phase": "wrapping_up", "confidence": 0.6, "is_no_show": True, "reasoning": "no-show feedback"})
    v = await evaluate_end_state(_bot(), [HOST], "Bob: candidate didn't join, strong no.", "call_ended")
    assert v.phase == "ended"
    assert v.is_no_show is True
    assert v.source == "guardrail:call_ended"


@pytest.mark.asyncio
async def test_llm_failure_drop_defaults_to_mid(monkeypatch):
    async def _boom(prompt, settings):
        return None
    monkeypatch.setattr(end_state, "_llm_judge", _boom)
    v = await evaluate_end_state(_bot(), [HOST, CAND], "x", "candidate_drop")
    assert v.phase == "mid"
    assert v.source == "llm_failed"


@pytest.mark.asyncio
async def test_llm_failure_call_ended_completes_and_infers_noshow(monkeypatch):
    async def _boom(prompt, settings):
        return None
    monkeypatch.setattr(end_state, "_llm_judge", _boom)
    # only the host ever present → inferred no-show
    v = await evaluate_end_state(_bot(tracked_participants=[HOST]), [HOST], "x", "call_ended")
    assert v.phase == "ended"
    assert v.is_no_show is True
    assert v.source == "llm_failed"


@pytest.mark.asyncio
async def test_null_confidence_from_llm_degrades_safely(stub_llm):
    # A malformed verdict ("confidence": null) must not raise outside the fail-safe.
    stub_llm({"phase": "ended", "confidence": None, "is_no_show": False, "reasoning": "x"})
    v = await evaluate_end_state(_bot(), [HOST], "x", "call_ended")
    assert v.confidence == 0.0
    assert v.phase == "ended"


# ---------------------------------------------------------------------------
# _llm_judge — the real one-shot httpx → Anthropic call (HTTP layer mocked)
# ---------------------------------------------------------------------------


def _fake_http_client(*, content_text=None, raise_status=None, post_exc=None):
    """Build a MagicMock standing in for `httpx.AsyncClient(...)` whose async
    context manager yields a client with an awaitable `.post`."""
    client = MagicMock()
    if post_exc is not None:
        client.post = AsyncMock(side_effect=post_exc)
    else:
        response = MagicMock()
        if raise_status is not None:
            response.raise_for_status = MagicMock(side_effect=raise_status)
        else:
            response.raise_for_status = MagicMock(return_value=None)
        response.json = MagicMock(return_value={
            "content": [{"text": content_text or ""}],
            "usage": {"input_tokens": 11, "output_tokens": 7},
        })
        client.post = AsyncMock(return_value=response)

    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=client)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return MagicMock(return_value=ctx)


_SETTINGS = SimpleNamespace(
    ANTHROPIC_API_KEY="test-key",
    END_STATE_MODEL="claude-sonnet-4-6",
)


@pytest.mark.asyncio
async def test_llm_judge_success_returns_parsed_dict(monkeypatch):
    monkeypatch.setattr(
        end_state.httpx, "AsyncClient",
        _fake_http_client(content_text='{"phase": "ended", "confidence": 0.9, "is_no_show": true, "reasoning": "done"}'),
    )
    result = await end_state._llm_judge("prompt", _SETTINGS)
    assert result == {"phase": "ended", "confidence": 0.9, "is_no_show": True, "reasoning": "done"}


@pytest.mark.asyncio
async def test_llm_judge_bad_shape_missing_phase_returns_none(monkeypatch):
    monkeypatch.setattr(
        end_state.httpx, "AsyncClient",
        _fake_http_client(content_text='{"confidence": 0.5, "is_no_show": false}'),  # no "phase"
    )
    assert await end_state._llm_judge("prompt", _SETTINGS) is None


@pytest.mark.asyncio
async def test_llm_judge_http_error_returns_none(monkeypatch):
    import httpx

    monkeypatch.setattr(
        end_state.httpx, "AsyncClient",
        _fake_http_client(raise_status=httpx.HTTPStatusError("500", request=MagicMock(), response=MagicMock())),
    )
    assert await end_state._llm_judge("prompt", _SETTINGS) is None


@pytest.mark.asyncio
async def test_llm_judge_post_exception_returns_none(monkeypatch):
    monkeypatch.setattr(
        end_state.httpx, "AsyncClient",
        _fake_http_client(post_exc=RuntimeError("network down")),
    )
    assert await end_state._llm_judge("prompt", _SETTINGS) is None


@pytest.mark.asyncio
async def test_evaluate_end_state_runs_real_llm_judge_path(monkeypatch):
    # Exercise evaluate_end_state through the real _llm_judge (HTTP mocked) so
    # the prompt-build + call + parse wiring is covered end to end.
    monkeypatch.setattr(
        end_state.httpx, "AsyncClient",
        _fake_http_client(content_text='{"phase": "wrapping_up", "confidence": 0.8, "is_no_show": false, "reasoning": "closing"}'),
    )
    v = await evaluate_end_state(_bot(), [HOST, CAND], "Bob: thanks for your time", "candidate_drop")
    assert v.phase == "wrapping_up"
    assert v.confidence == 0.8
    assert v.source == "llm"


# ---------------------------------------------------------------------------
# transcript formatters + _elapsed_minutes edge cases
# ---------------------------------------------------------------------------


def test_transcript_from_segments_uses_text_fallback_and_skips_non_dict():
    segs = [
        "not-a-dict",
        {"participant": {"name": "Bob", "is_host": True}, "text": "plain text line"},
        {"participant": {"name": "Quiet"}, "words": []},  # no text -> skipped
    ]
    out = end_state.transcript_from_segments(segs)
    assert out == "Bob (host=True): plain text line"


def test_transcript_from_segments_non_list_returns_empty():
    assert end_state.transcript_from_segments("nope") == ""


def test_transcript_from_utterances_skips_empty_and_unknown_id():
    tracked = [{"id": 100, "name": "Bob", "is_host": True}]
    out = end_state.transcript_from_utterances(tracked, {"100": "hi", "999": "", "200": "unknown speaker"})
    assert "Bob (host=True): hi" in out
    assert "speaker (host=False): unknown speaker" in out


def test_elapsed_minutes_none_when_no_joined_at():
    assert end_state._elapsed_minutes({}) is None


def test_elapsed_minutes_none_on_bad_timestamp():
    assert end_state._elapsed_minutes({"joined_at": "not-a-date"}) is None
