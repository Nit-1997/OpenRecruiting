"""Phase C: act on the list returned by ats_promote_interviews.

Pure-seam unit tests — recall_orchestrator.create_recall_bot_for_cr,
feedback_job_service.trigger_feedback_processing, and
bundle.interviews.fetch_transcript are all monkeypatched. Supabase is mocked
via respx (mock_update for ats_interviews flag writes, mock_select for the
transcript/feedback_questions gates).
"""

import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from app.services.ats_sync import interview_actions
from app.services.supabase import get_supabase_admin_client
from tests.helpers.supabase_mocks import (
    mock_select,
    mock_update,
)


def _future_iso(hours=2):
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()


def _past_iso(hours=2):
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()


def _promoted(**over):
    base = {
        "candidate_round_id": "cr-1",
        "scheduled_start": _future_iso(),
        "meeting_url": "https://meet.google.com/abc-defg-hij",
        "notetaker_transcript_id": None,
        "status": "scheduled",
        "ats_interview_event_id": "evt-1",
        "candidate_name": "Jordan Lee",
        "organization_id": "org-1",
    }
    base.update(over)
    return base


class _FakeBundle:
    """Stand-in AtsProviderBundle with only the interviews port used here."""

    def __init__(self, interviews=None):
        self.interviews = interviews


class _FakeInterviews:
    def __init__(self, transcript=None, raises=None):
        self._transcript = transcript
        self._raises = raises
        self.calls = []

    async def fetch_transcript(self, notetaker_transcript_id):
        self.calls.append(notetaker_transcript_id)
        if self._raises:
            raise self._raises
        return self._transcript


@pytest.fixture
def recall_spy(monkeypatch):
    calls = []

    async def _fake_create(cr_id, candidate_name, meeting_url, scheduled_at):
        calls.append(
            {
                "cr_id": str(cr_id),
                "candidate_name": candidate_name,
                "meeting_url": meeting_url,
                "scheduled_at": scheduled_at,
            }
        )
        return {"id": "bot-row-1", "recall_bot_id": "rb-1", "status": "created"}

    monkeypatch.setattr(
        interview_actions, "create_recall_bot_for_cr", _fake_create
    )
    return calls


@pytest.fixture
def feedback_spy(monkeypatch):
    calls = []

    async def _fake_trigger(cr_id, skip_prereq_check=False):
        calls.append({"cr_id": cr_id, "skip": skip_prereq_check})
        return {"status": "accepted", "candidate_round_id": cr_id}

    monkeypatch.setattr(
        interview_actions, "trigger_feedback_processing", _fake_trigger
    )
    return calls


async def test_future_with_url_schedules_recall_and_flags_row(
    respx_mock, recall_spy, feedback_spy
):
    update_route = mock_update(respx_mock, "ats_interviews")
    # No notetaker transcript and no recall segments yet → feedback gate
    # short-circuits at the transcript check (deferred).
    mock_select(respx_mock, "transcripts", [])
    supabase = get_supabase_admin_client()

    await interview_actions.act_on_promoted_interviews(
        supabase, [_promoted()], bundle=_FakeBundle()
    )

    assert len(recall_spy) == 1
    call = recall_spy[0]
    assert call["cr_id"] == "cr-1"
    assert call["candidate_name"] == "Jordan Lee"
    assert call["meeting_url"] == "https://meet.google.com/abc-defg-hij"
    assert isinstance(call["scheduled_at"], datetime)
    # ats_interviews.recall_bot_scheduled flipped true, keyed on event id
    assert update_route.called
    body = json.loads(update_route.calls[-1].request.content)
    assert body["recall_bot_scheduled"] is True
    # no feedback trigger (no transcript)
    assert feedback_spy == []


async def test_past_interview_skips_recall(respx_mock, recall_spy, feedback_spy):
    mock_update(respx_mock, "ats_interviews")
    mock_select(respx_mock, "transcripts", [])
    supabase = get_supabase_admin_client()
    await interview_actions.act_on_promoted_interviews(
        supabase, [_promoted(scheduled_start=_past_iso())], bundle=_FakeBundle()
    )
    assert recall_spy == []


async def test_no_meeting_url_skips_recall(respx_mock, recall_spy, feedback_spy):
    mock_update(respx_mock, "ats_interviews")
    mock_select(respx_mock, "transcripts", [])
    supabase = get_supabase_admin_client()
    await interview_actions.act_on_promoted_interviews(
        supabase, [_promoted(meeting_url=None)], bundle=_FakeBundle()
    )
    assert recall_spy == []


async def test_recall_409_lock_is_skipped_not_raised(
    respx_mock, monkeypatch, feedback_spy
):
    async def _raise_409(cr_id, candidate_name, meeting_url, scheduled_at):
        raise HTTPException(status_code=409, detail="locked")

    monkeypatch.setattr(interview_actions, "create_recall_bot_for_cr", _raise_409)
    mock_update(respx_mock, "ats_interviews")
    mock_select(respx_mock, "transcripts", [])
    supabase = get_supabase_admin_client()
    # must not raise
    await interview_actions.act_on_promoted_interviews(
        supabase, [_promoted()], bundle=_FakeBundle()
    )


async def test_missing_cr_id_is_noop(respx_mock, recall_spy, feedback_spy):
    supabase = get_supabase_admin_client()
    await interview_actions.act_on_promoted_interviews(
        supabase, [_promoted(candidate_round_id=None)], bundle=_FakeBundle()
    )
    assert recall_spy == []
    assert feedback_spy == []


async def test_recall_non_409_failure_falls_back_to_notetaker(
    respx_mock, monkeypatch, feedback_spy
):
    # A non-409 Recall failure means NO bot was scheduled -> the de-dup
    # precedence treats recall_scheduled=False, so a present notetaker
    # transcript IS written to scorecard_transcript (and feedback fires).
    async def _boom(cr_id, candidate_name, meeting_url, scheduled_at):
        raise RuntimeError("recall API 500")

    monkeypatch.setattr(interview_actions, "create_recall_bot_for_cr", _boom)
    cr_update = mock_update(respx_mock, "candidate_rounds")
    mock_update(respx_mock, "ats_interviews")
    mock_select(respx_mock, "transcripts", [])
    mock_select(respx_mock, "candidate_rounds", [{"round_id": "rd-1"}])
    mock_select(respx_mock, "feedback_questions", [{"id": "q1"}])
    supabase = get_supabase_admin_client()

    from types import SimpleNamespace

    interviews = _FakeInterviews(
        transcript=SimpleNamespace(
            segments=[{"speaker": "candidate", "text": "answer"}], full_text=None
        )
    )
    await interview_actions.act_on_promoted_interviews(
        supabase,
        [
            _promoted(
                scheduled_start=_future_iso(),  # future + url, but recall raises
                meeting_url="https://zoom.us/j/5",
                notetaker_transcript_id="nt-5",
                status="scheduled",
            )
        ],
        bundle=_FakeBundle(interviews=interviews),
    )
    # recall failed (non-409) -> notetaker written to scorecard_transcript
    bodies = [json.loads(c.request.content) for c in cr_update.calls]
    assert [b for b in bodies if "scorecard_transcript" in b]
    assert feedback_spy and feedback_spy[0]["skip"] is True


async def test_recall_returns_none_falls_back_to_notetaker(
    respx_mock, monkeypatch, feedback_spy
):
    # REAL contract: create_recall_bot_for_cr RETURNS None on a Recall failure
    # (it only re-raises HTTPException for the 409 lock; every other failure is
    # logged + swallowed -> None). A None return means NO bot was scheduled, so
    # _schedule_recall must NOT set recall_bot_scheduled and must return False,
    # which keeps recall_scheduled=False so the notetaker transcript IS written
    # to scorecard_transcript and feedback fires. Regression for the
    # "no-exception == success" bug (None was treated as scheduled -> de-dup
    # precedence suppressed the fallback -> silent loss of transcript+feedback).
    async def _returns_none(cr_id, candidate_name, meeting_url, scheduled_at):
        return None

    monkeypatch.setattr(
        interview_actions, "create_recall_bot_for_cr", _returns_none
    )
    cr_update = mock_update(respx_mock, "candidate_rounds")
    ats_update = mock_update(respx_mock, "ats_interviews")
    mock_select(respx_mock, "transcripts", [])
    mock_select(respx_mock, "candidate_rounds", [{"round_id": "rd-1"}])
    mock_select(respx_mock, "feedback_questions", [{"id": "q1"}])
    supabase = get_supabase_admin_client()

    from types import SimpleNamespace

    interviews = _FakeInterviews(
        transcript=SimpleNamespace(
            segments=[{"speaker": "candidate", "text": "answer"}], full_text=None
        )
    )
    await interview_actions.act_on_promoted_interviews(
        supabase,
        [
            _promoted(
                scheduled_start=_future_iso(),  # future + url, but recall returns None
                meeting_url="https://zoom.us/j/5",
                notetaker_transcript_id="nt-5",
                status="scheduled",
            )
        ],
        bundle=_FakeBundle(interviews=interviews),
    )
    # recall_bot_scheduled MUST NOT be set (no bot was created)
    ats_bodies = [json.loads(c.request.content) for c in ats_update.calls]
    assert not [b for b in ats_bodies if b.get("recall_bot_scheduled")], (
        "recall_bot_scheduled must not be set when create_recall_bot_for_cr "
        "returns None"
    )
    # de-dup precedence treats recall as NOT scheduled -> notetaker transcript
    # IS written to scorecard_transcript and feedback fires
    cr_bodies = [json.loads(c.request.content) for c in cr_update.calls]
    assert [b for b in cr_bodies if "scorecard_transcript" in b], (
        "notetaker transcript must fall back to scorecard_transcript when "
        "recall returned None"
    )
    assert feedback_spy and feedback_spy[0]["skip"] is True


async def test_schedule_recall_returns_false_on_none_bot(respx_mock, monkeypatch):
    # Direct unit assert on the _schedule_recall return contract: a None bot
    # (real Recall failure) -> returns False so the caller fires the fallback.
    async def _returns_none(cr_id, candidate_name, meeting_url, scheduled_at):
        return None

    monkeypatch.setattr(
        interview_actions, "create_recall_bot_for_cr", _returns_none
    )
    mock_update(respx_mock, "ats_interviews")
    supabase = get_supabase_admin_client()
    result = await interview_actions._schedule_recall(
        supabase,
        _promoted(
            scheduled_start=_future_iso(),
            meeting_url="https://zoom.us/j/5",
        ),
    )
    assert result is False


def _transcript(segments=None, full_text="Q1 ... A1 ..."):
    """Stand-in AtsTranscript (Phase A model). Tests only read .segments and
    .full_text, so a simple namespace mirrors the canonical shape."""
    from types import SimpleNamespace

    return SimpleNamespace(
        segments=segments
        or [
            {"speaker": "interviewer", "text": "Tell me about a hard bug."},
            {"speaker": "candidate", "text": "I once chased a race condition."},
        ],
        full_text=full_text,
    )


async def test_notetaker_no_recall_writes_scorecard_transcript(
    respx_mock, recall_spy, feedback_spy
):
    # past interview (no recall) but completed with a notetaker transcript,
    # and the round HAS feedback questions -> store to scorecard_transcript
    # AND trigger feedback.
    cr_update = mock_update(respx_mock, "candidate_rounds")
    mock_update(respx_mock, "ats_interviews")
    # transcript gate: a row exists for the CR after we write it
    mock_select(respx_mock, "transcripts", [])  # no recall segments
    # feedback gate resolves round_id from candidate_rounds, then its questions
    mock_select(respx_mock, "candidate_rounds", [{"round_id": "rd-1"}])
    mock_select(respx_mock, "feedback_questions", [{"id": "q1"}])
    supabase = get_supabase_admin_client()

    interviews = _FakeInterviews(transcript=_transcript())
    await interview_actions.act_on_promoted_interviews(
        supabase,
        [
            _promoted(
                scheduled_start=_past_iso(),
                meeting_url=None,
                notetaker_transcript_id="nt-1",
                status="completed",
            )
        ],
        bundle=_FakeBundle(interviews=interviews),
    )

    assert interviews.calls == ["nt-1"]
    # scorecard_transcript written (neutral speakers, no "OpenRecruiting")
    bodies = [json.loads(c.request.content) for c in cr_update.calls]
    sc_bodies = [b for b in bodies if "scorecard_transcript" in b]
    assert sc_bodies, "expected scorecard_transcript write"
    text = sc_bodies[0]["scorecard_transcript"]
    assert "Interviewer:" in text and "Candidate:" in text
    assert "OpenRecruiting" not in text
    # feedback triggered with skip_prereq_check=True
    assert feedback_spy and feedback_spy[0]["skip"] is True


async def test_notetaker_with_recall_does_not_write_scorecard_transcript(
    respx_mock, recall_spy, feedback_spy
):
    # future interview WITH meeting_url => recall scheduled. Even though a
    # notetaker_transcript_id is present, we must NOT write
    # scorecard_transcript (Recall segments win). Feedback is deferred to the
    # recall webhook (no transcript row yet here).
    cr_update = mock_update(respx_mock, "candidate_rounds")
    mock_update(respx_mock, "ats_interviews")
    mock_select(respx_mock, "transcripts", [])  # recall segments not arrived yet
    mock_select(respx_mock, "feedback_questions", [{"id": "q1"}])
    supabase = get_supabase_admin_client()

    interviews = _FakeInterviews(transcript=_transcript())
    await interview_actions.act_on_promoted_interviews(
        supabase,
        [
            _promoted(
                scheduled_start=_future_iso(),
                meeting_url="https://zoom.us/j/123",
                notetaker_transcript_id="nt-1",
                status="scheduled",
            )
        ],
        bundle=_FakeBundle(interviews=interviews),
    )

    assert len(recall_spy) == 1
    # notetaker still fetched (we store nothing destructive, but precedence
    # means NO scorecard_transcript write)
    assert interviews.calls == ["nt-1"]
    bodies = [json.loads(c.request.content) for c in cr_update.calls]
    assert not [b for b in bodies if "scorecard_transcript" in b], (
        "scorecard_transcript must not be written when recall is scheduled"
    )
    # no transcript row + recall in flight => feedback NOT triggered yet (deferred)
    assert feedback_spy == []


async def test_notetaker_fetch_failure_is_best_effort(
    respx_mock, recall_spy, feedback_spy
):
    mock_update(respx_mock, "candidate_rounds")
    mock_update(respx_mock, "ats_interviews")
    mock_select(respx_mock, "transcripts", [])
    mock_select(respx_mock, "feedback_questions", [{"id": "q1"}])
    supabase = get_supabase_admin_client()
    interviews = _FakeInterviews(raises=RuntimeError("notetaker 500"))
    # must not raise
    await interview_actions.act_on_promoted_interviews(
        supabase,
        [
            _promoted(
                scheduled_start=_past_iso(),
                meeting_url=None,
                notetaker_transcript_id="nt-1",
                status="completed",
            )
        ],
        bundle=_FakeBundle(interviews=interviews),
    )


async def test_notetaker_empty_transcript_stores_nothing(
    respx_mock, recall_spy, feedback_spy
):
    cr_update = mock_update(respx_mock, "candidate_rounds")
    mock_update(respx_mock, "ats_interviews")
    mock_select(respx_mock, "transcripts", [])
    mock_select(respx_mock, "feedback_questions", [{"id": "q1"}])
    supabase = get_supabase_admin_client()
    interviews = _FakeInterviews(transcript=None)  # fetch returns None
    await interview_actions.act_on_promoted_interviews(
        supabase,
        [
            _promoted(
                scheduled_start=_past_iso(),
                meeting_url=None,
                notetaker_transcript_id="nt-1",
                status="completed",
            )
        ],
        bundle=_FakeBundle(interviews=interviews),
    )
    bodies = [json.loads(c.request.content) for c in cr_update.calls]
    assert not [b for b in bodies if "scorecard_transcript" in b]
    # no transcript stored, no recall, no questions-bearing transcript => no feedback
    assert feedback_spy == []


async def test_recall_segments_present_triggers_feedback(
    respx_mock, recall_spy, feedback_spy
):
    # No notetaker, but a Recall transcript already landed (segments) for the
    # CR and questions exist -> trigger feedback (this is the post-webhook
    # reconcile re-run path for a completed recall interview).
    mock_update(respx_mock, "ats_interviews")
    mock_select(
        respx_mock,
        "transcripts",
        [{"id": "t1", "segments": [{"speaker": "Interviewer", "text": "hi"}]}],
    )
    mock_select(respx_mock, "candidate_rounds", [{"round_id": "rd-1"}])
    mock_select(respx_mock, "feedback_questions", [{"id": "q1"}])
    supabase = get_supabase_admin_client()
    await interview_actions.act_on_promoted_interviews(
        supabase,
        [
            _promoted(
                scheduled_start=_past_iso(),
                meeting_url="https://zoom.us/j/9",  # was scheduled; now past
                notetaker_transcript_id=None,
                status="completed",
            )
        ],
        bundle=_FakeBundle(),
    )
    assert feedback_spy and feedback_spy[0]["cr_id"] == "cr-1"
    assert feedback_spy[0]["skip"] is True


async def test_no_feedback_questions_skips_trigger(
    respx_mock, recall_spy, feedback_spy
):
    mock_update(respx_mock, "candidate_rounds")
    mock_update(respx_mock, "ats_interviews")
    mock_select(respx_mock, "transcripts", [])
    # round resolves, but it has NO feedback questions -> gate must skip the
    # trigger (NOT via an exception — exercise the real no-questions branch).
    mock_select(respx_mock, "candidate_rounds", [{"round_id": "rd-1"}])
    mock_select(respx_mock, "feedback_questions", [])  # NONE
    supabase = get_supabase_admin_client()
    interviews = _FakeInterviews(transcript=_transcript())
    await interview_actions.act_on_promoted_interviews(
        supabase,
        [
            _promoted(
                scheduled_start=_past_iso(),
                meeting_url=None,
                notetaker_transcript_id="nt-1",
                status="completed",
            )
        ],
        bundle=_FakeBundle(interviews=interviews),
    )
    assert feedback_spy == []  # Lambda would reject without questions


async def test_no_transcript_anywhere_defers_feedback(
    respx_mock, recall_spy, feedback_spy
):
    # future interview, recall scheduled, no notetaker, no recall segments yet
    # -> feedback deferred (recall webhook will fire it later).
    mock_update(respx_mock, "ats_interviews")
    mock_select(respx_mock, "transcripts", [])
    mock_select(respx_mock, "feedback_questions", [{"id": "q1"}])
    supabase = get_supabase_admin_client()
    await interview_actions.act_on_promoted_interviews(
        supabase, [_promoted()], bundle=_FakeBundle()
    )
    assert feedback_spy == []


async def test_idempotent_rerun_single_feedback_trigger(
    respx_mock, recall_spy, feedback_spy
):
    # Re-running the same promoted list: recall has its own CAS lock; feedback
    # has the claim CAS. Here we assert THIS layer doesn't multiply triggers
    # for a single pass over a 1-item list with a present transcript.
    mock_update(respx_mock, "ats_interviews")
    mock_update(respx_mock, "candidate_rounds")
    mock_select(
        respx_mock,
        "transcripts",
        [{"id": "t1", "segments": [{"speaker": "Interviewer", "text": "hi"}]}],
    )
    mock_select(respx_mock, "candidate_rounds", [{"round_id": "rd-1"}])
    mock_select(respx_mock, "feedback_questions", [{"id": "q1"}])
    supabase = get_supabase_admin_client()
    promoted = [
        _promoted(
            scheduled_start=_past_iso(),
            meeting_url="https://zoom.us/j/9",
            status="completed",
        )
    ]
    await interview_actions.act_on_promoted_interviews(
        supabase, promoted, bundle=_FakeBundle()
    )
    assert len(feedback_spy) == 1


async def test_bundle_resolved_from_org_when_omitted(
    respx_mock, recall_spy, feedback_spy, monkeypatch
):
    captured = {}

    async def _fake_get_provider(supabase, organization_id):
        captured["org"] = str(organization_id)
        return _FakeBundle(interviews=_FakeInterviews(transcript=_transcript()))

    monkeypatch.setattr(interview_actions, "get_ats_provider", _fake_get_provider)
    mock_update(respx_mock, "candidate_rounds")
    mock_update(respx_mock, "ats_interviews")
    mock_select(respx_mock, "transcripts", [])
    mock_select(respx_mock, "candidate_rounds", [{"round_id": "rd-1"}])
    mock_select(respx_mock, "feedback_questions", [{"id": "q1"}])
    supabase = get_supabase_admin_client()
    await interview_actions.act_on_promoted_interviews(
        supabase,
        [
            _promoted(
                scheduled_start=_past_iso(),
                meeting_url=None,
                notetaker_transcript_id="nt-1",
                status="completed",
                organization_id="org-77",
            )
        ],
        bundle=None,  # force resolution
    )
    assert captured["org"] == "org-77"
    assert feedback_spy and feedback_spy[0]["skip"] is True


async def test_bundle_resolution_failure_is_soft(
    respx_mock, recall_spy, feedback_spy, monkeypatch
):
    async def _boom(supabase, organization_id):
        raise RuntimeError("no active connection")

    monkeypatch.setattr(interview_actions, "get_ats_provider", _boom)
    mock_update(respx_mock, "ats_interviews")
    mock_select(respx_mock, "transcripts", [])
    mock_select(respx_mock, "feedback_questions", [{"id": "q1"}])
    supabase = get_supabase_admin_client()
    # future + url => recall still fires even though bundle resolution failed
    await interview_actions.act_on_promoted_interviews(
        supabase, [_promoted(organization_id="org-77")], bundle=None
    )
    assert len(recall_spy) == 1  # recall independent of bundle
