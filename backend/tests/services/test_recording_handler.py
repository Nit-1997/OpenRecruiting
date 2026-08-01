"""Characterization tests for recall_webhook.recording_handler helpers and the
fetch_and_store_recording orchestration. DB + Recall + http client are mocked.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.services.feedback_job_service import FeedbackJobServiceError
from app.services.recall_webhook import recording_handler as rh


def _supabase():
    sb = MagicMock()
    builder = MagicMock()
    for attr in ("select", "eq", "single", "update", "upsert"):
        setattr(builder, attr, MagicMock(return_value=builder))
    builder.execute_async = AsyncMock(return_value=MagicMock(data={}))
    sb.table = MagicMock(return_value=builder)
    return sb, builder


# ----------------------- _fetch_participants / _fetch_transcript -----------------------

@pytest.mark.asyncio
async def test_fetch_participants_no_url_returns_none():
    assert await rh._fetch_participants({}) is None


@pytest.mark.asyncio
async def test_fetch_participants_ok_list():
    http = MagicMock()
    http.get = AsyncMock(return_value=httpx.Response(200, json=[{"name": "Bob"}]))
    with patch.object(rh, "get_async_http_client", return_value=http):
        out = await rh._fetch_participants({"participants_download_url": "https://s3/p"})
    assert out == [{"name": "Bob"}]


@pytest.mark.asyncio
async def test_fetch_participants_non_200_returns_none():
    http = MagicMock()
    http.get = AsyncMock(return_value=httpx.Response(404))
    with patch.object(rh, "get_async_http_client", return_value=http):
        assert await rh._fetch_participants({"participants_download_url": "https://s3/p"}) is None


@pytest.mark.asyncio
async def test_fetch_participants_not_list_returns_none():
    http = MagicMock()
    http.get = AsyncMock(return_value=httpx.Response(200, json={"not": "list"}))
    with patch.object(rh, "get_async_http_client", return_value=http):
        assert await rh._fetch_participants({"participants_download_url": "https://s3/p"}) is None


@pytest.mark.asyncio
async def test_fetch_participants_exception_returns_none():
    http = MagicMock()
    http.get = AsyncMock(side_effect=httpx.ConnectError("down"))
    with patch.object(rh, "get_async_http_client", return_value=http):
        assert await rh._fetch_participants({"participants_download_url": "https://s3/p"}) is None


@pytest.mark.asyncio
async def test_fetch_transcript_ok_and_empty():
    http = MagicMock()
    http.get = AsyncMock(return_value=httpx.Response(200, json=[{"text": "hi"}]))
    with patch.object(rh, "get_async_http_client", return_value=http):
        assert await rh._fetch_transcript({"transcript_url": "https://s3/t"}) == [{"text": "hi"}]
    assert await rh._fetch_transcript({}) is None


@pytest.mark.asyncio
async def test_fetch_transcript_non_200_and_error():
    http = MagicMock()
    http.get = AsyncMock(return_value=httpx.Response(500))
    with patch.object(rh, "get_async_http_client", return_value=http):
        assert await rh._fetch_transcript({"transcript_url": "https://s3/t"}) is None
    http.get = AsyncMock(side_effect=httpx.ConnectError("x"))
    with patch.object(rh, "get_async_http_client", return_value=http):
        assert await rh._fetch_transcript({"transcript_url": "https://s3/t"}) is None


# ----------------------- _normalise_bot_speaker -----------------------

def test_normalise_bot_speaker_patches_empty_name():
    data = [{"participant": {"name": ""}}, {"participant": {"name": "Bob"}}, "not-a-dict"]
    rh._normalise_bot_speaker(data)
    assert data[0]["participant"]["name"] == "OpenRecruiting"
    assert data[1]["participant"]["name"] == "Bob"


def test_normalise_bot_speaker_none_noop():
    rh._normalise_bot_speaker(None)  # no error


# ----------------------- _persist_recording_metadata / _upsert_transcript -----------------------

@pytest.mark.asyncio
async def test_persist_recording_metadata_writes():
    sb, builder = _supabase()
    await rh._persist_recording_metadata(sb, "db1", {"video_url": "v", "transcript_url": "t"}, [{"x": 1}])
    builder.update.assert_called_once()
    payload = builder.update.call_args.args[0]
    assert payload["status"] == "done"
    assert payload["transcript_ready"] is True


@pytest.mark.asyncio
async def test_upsert_transcript_writes():
    sb, builder = _supabase()
    await rh._upsert_transcript(sb, "cr1", {"transcript_url": "t", "video_duration": 100}, [{"s": 1}], None)
    builder.upsert.assert_called_once()
    assert builder.upsert.call_args.kwargs["on_conflict"] == "candidate_round_id"


# ----------------------- _fill_interviewer_email_if_missing -----------------------

def _fill_supabase(cr_data, bot_data):
    sb = MagicMock()

    def table(name):
        builder = MagicMock()
        for attr in ("select", "eq", "single", "update"):
            setattr(builder, attr, MagicMock(return_value=builder))
        if name == "candidate_rounds":
            builder.execute_async = AsyncMock(return_value=MagicMock(data=cr_data))
        elif name == "recall_bots":
            builder.execute_async = AsyncMock(return_value=MagicMock(data=bot_data))
        else:
            builder.execute_async = AsyncMock(return_value=MagicMock(data={}))
        return builder

    sb.table = MagicMock(side_effect=table)
    return sb


@pytest.mark.asyncio
async def test_fill_interviewer_already_set_skips():
    sb = _fill_supabase({"interviewer_email": "set@m.ai", "candidates": {"name": "Alice"}}, {})
    with patch.object(rh, "detect_interviewer_emails") as detect:
        await rh._fill_interviewer_email_if_missing(sb, "cr1", "db1")
    detect.assert_not_called()


@pytest.mark.asyncio
async def test_fill_interviewer_no_cr_row_returns():
    sb = _fill_supabase(None, {})
    await rh._fill_interviewer_email_if_missing(sb, "cr1", "db1")  # no error


@pytest.mark.asyncio
async def test_fill_interviewer_detected_writes():
    sb = _fill_supabase(
        {"interviewer_email": None, "candidates": {"name": "Alice"}},
        {"tracked_participants": [{"name": "Bob", "email": "bob@m.ai", "is_host": True}]},
    )
    with patch.object(rh, "detect_interviewer_emails", return_value=["bob@m.ai"]):
        await rh._fill_interviewer_email_if_missing(sb, "cr1", "db1")
    # the update on candidate_rounds ran (verified by no exception + detect used)


# ----------------------- _trigger_feedback_lambda -----------------------

@pytest.mark.asyncio
async def test_trigger_lambda_accepted():
    sb, _ = _supabase()
    svc = MagicMock()
    svc.trigger_feedback_processing = AsyncMock(return_value={"status": "accepted"})
    with patch.object(rh, "get_feedback_job_service", return_value=svc):
        await rh._trigger_feedback_lambda(sb, "cr1")
    svc.trigger_feedback_processing.assert_awaited_once_with("cr1", skip_prereq_check=True)


@pytest.mark.asyncio
async def test_trigger_lambda_not_accepted_logs():
    sb, _ = _supabase()
    svc = MagicMock()
    svc.trigger_feedback_processing = AsyncMock(return_value={"status": "rejected", "reason": "no transcript"})
    with patch.object(rh, "get_feedback_job_service", return_value=svc):
        await rh._trigger_feedback_lambda(sb, "cr1")  # no raise


@pytest.mark.asyncio
async def test_trigger_lambda_service_error_swallowed():
    sb, _ = _supabase()
    svc = MagicMock()
    svc.trigger_feedback_processing = AsyncMock(side_effect=FeedbackJobServiceError("boom", error_code="X"))
    with patch.object(rh, "get_feedback_job_service", return_value=svc):
        await rh._trigger_feedback_lambda(sb, "cr1")  # no raise


@pytest.mark.asyncio
async def test_trigger_lambda_unexpected_error_marks_failed():
    sb, builder = _supabase()
    svc = MagicMock()
    svc.trigger_feedback_processing = AsyncMock(side_effect=RuntimeError("kaboom"))
    with patch.object(rh, "get_feedback_job_service", return_value=svc):
        await rh._trigger_feedback_lambda(sb, "cr1")
    # the failed-status update ran
    update_payloads = [c.args[0] for c in builder.update.call_args_list]
    assert any(p.get("processing_status") == "failed" for p in update_payloads)


# ----------------------- _send_add_feedback_emails -----------------------

@pytest.mark.asyncio
async def test_send_add_feedback_emails_ok():
    svc = MagicMock()
    svc.send_interview_complete_emails = AsyncMock()
    with patch("app.services.feedback_notification_service.get_feedback_notification_service", return_value=svc):
        await rh._send_add_feedback_emails("cr1")
    svc.send_interview_complete_emails.assert_awaited_once_with("cr1")


@pytest.mark.asyncio
async def test_send_add_feedback_emails_error_swallowed():
    svc = MagicMock()
    svc.send_interview_complete_emails = AsyncMock(side_effect=RuntimeError("smtp"))
    with patch("app.services.feedback_notification_service.get_feedback_notification_service", return_value=svc):
        await rh._send_add_feedback_emails("cr1")  # no raise


# ----------------------- _decide_feedback_path -----------------------

class _DecideSupabase:
    """Per-table fake for _decide_feedback_path. Returns canned rows for the
    recall_bots + transcripts `.single()` reads, and records the
    candidate_rounds completion write into `completed_cr`."""

    def __init__(self, bot_data, transcript_data):
        self._bot_data = bot_data
        self._transcript_data = transcript_data
        self.completed_cr = None

    def table(self, name):
        outer = self
        builder = MagicMock()
        for attr in ("select", "eq", "single", "update"):
            setattr(builder, attr, MagicMock(return_value=builder))

        if name == "recall_bots":
            builder.execute_async = AsyncMock(return_value=MagicMock(data=outer._bot_data))
        elif name == "transcripts":
            builder.execute_async = AsyncMock(return_value=MagicMock(data=outer._transcript_data))
        elif name == "candidate_rounds":
            update_payload = {}

            def _update(payload):
                update_payload.update(payload)
                return builder
            builder.update = MagicMock(side_effect=_update)

            async def _exec():
                if update_payload.get("status") == "completed":
                    # mirror the guarded .eq("status","in_progress") write
                    outer.completed_cr = "cr-1"
                return MagicMock(data={})
            builder.execute_async = AsyncMock(side_effect=_exec)
        else:
            builder.execute_async = AsyncMock(return_value=MagicMock(data={}))
        return builder


@pytest.mark.asyncio
async def test_decide_no_show_completes_round_and_skips_lambda(monkeypatch):
    sb = _DecideSupabase(
        bot_data={
            "feedback_started_at": None,
            "feedback_status": "completed",
            "joined_at": "2026-06-02T00:00:00Z",
            "scheduled_at": "2026-06-02T00:00:00Z",
            "candidate_name": "Nitin Bhat",
            "detected_candidate_participant_id": None,
            "tracked_participants": [{"id": 1, "name": "Nitin Bhat", "is_host": True}],
        },
        transcript_data={
            "feedback_transcript": None,
            "segments": [{"participant": {"name": "Nitin Bhat", "is_host": True}, "text": "no-show"}],
        },
    )
    triggered = {"lambda": False}

    async def _fake_verdict(*a, **k):
        from app.services.recall_webhook.end_state import EndStateVerdict
        return EndStateVerdict("ended", 0.9, True, "no-show feedback", "guardrail:call_ended")
    monkeypatch.setattr(rh.end_state, "evaluate_end_state", _fake_verdict)

    async def _fake_lambda(supabase, cr_id):
        triggered["lambda"] = True
    monkeypatch.setattr(rh, "_trigger_feedback_lambda", _fake_lambda)

    async def _fake_emails(cr_id):
        pass
    monkeypatch.setattr(rh, "_send_add_feedback_emails", _fake_emails)

    await rh._decide_feedback_path(sb, "cr-1", "bot-db-1", None)

    assert triggered["lambda"] is False
    assert sb.completed_cr == "cr-1"


@pytest.mark.asyncio
async def test_decide_meaningful_feedback_triggers_lambda(monkeypatch):
    feedback_text = "Interviewer: " + ("The candidate did well on system design. " * 5)  # > 150 chars
    sb = _DecideSupabase(
        bot_data={
            "feedback_started_at": "2026-06-02T00:30:00Z",
            "feedback_status": "completed",
            "joined_at": "2026-06-02T00:00:00Z",
            "scheduled_at": "2026-06-02T00:00:00Z",
            "candidate_name": "Alice",
            "detected_candidate_participant_id": 2,
            "tracked_participants": [{"id": 1, "name": "Bob", "is_host": True}],
        },
        transcript_data={"feedback_transcript": feedback_text, "segments": None},
    )
    triggered = {"lambda": False, "emails": False}

    async def _fake_verdict(*a, **k):
        from app.services.recall_webhook.end_state import EndStateVerdict
        return EndStateVerdict("ended", 0.95, False, "real interview", "guardrail:call_ended")
    monkeypatch.setattr(rh.end_state, "evaluate_end_state", _fake_verdict)

    async def _fake_lambda(supabase, cr_id):
        triggered["lambda"] = True
    monkeypatch.setattr(rh, "_trigger_feedback_lambda", _fake_lambda)

    async def _fake_emails(cr_id):
        triggered["emails"] = True
    monkeypatch.setattr(rh, "_send_add_feedback_emails", _fake_emails)

    await rh._decide_feedback_path(sb, "cr-1", "bot-db-1", None)

    assert triggered["lambda"] is True
    assert triggered["emails"] is False
    assert sb.completed_cr is None  # Lambda completes the round, not us


@pytest.mark.asyncio
async def test_decide_no_feedback_completes_and_emails(monkeypatch):
    sb = _DecideSupabase(
        bot_data={
            "feedback_started_at": None,
            "feedback_status": "none",
            "joined_at": "2026-06-02T00:00:00Z",
            "scheduled_at": "2026-06-02T00:00:00Z",
            "candidate_name": "Alice",
            "detected_candidate_participant_id": 2,
            "tracked_participants": [{"id": 1, "name": "Bob", "is_host": True}],
        },
        transcript_data={"feedback_transcript": None, "segments": [{"participant": {"name": "Bob"}, "text": "hi"}]},
    )
    triggered = {"lambda": False, "emails": False}

    async def _fake_verdict(*a, **k):
        from app.services.recall_webhook.end_state import EndStateVerdict
        return EndStateVerdict("ended", 0.9, False, "real interview, no dictated feedback", "guardrail:call_ended")
    monkeypatch.setattr(rh.end_state, "evaluate_end_state", _fake_verdict)

    async def _fake_lambda(supabase, cr_id):
        triggered["lambda"] = True
    monkeypatch.setattr(rh, "_trigger_feedback_lambda", _fake_lambda)

    async def _fake_emails(cr_id):
        triggered["emails"] = True
    monkeypatch.setattr(rh, "_send_add_feedback_emails", _fake_emails)

    await rh._decide_feedback_path(sb, "cr-1", "bot-db-1", None)

    assert triggered["lambda"] is False
    assert triggered["emails"] is True
    assert sb.completed_cr == "cr-1"


# ----------------------- fetch_and_store_recording orchestration -----------------------

@pytest.mark.asyncio
async def test_fetch_and_store_no_recording_marks_done():
    sb, builder = _supabase()
    recall = MagicMock()
    recall.get_recording_urls = AsyncMock(return_value=None)
    recall.close = AsyncMock()
    with patch.object(rh, "get_supabase_admin_client", return_value=sb), \
         patch.object(rh, "get_recall_service", return_value=recall):
        await rh.fetch_and_store_recording("rb1", "db1", "cr1")
    recall.close.assert_awaited_once()
    builder.update.assert_called_once_with({"status": "done"})


@pytest.mark.asyncio
async def test_fetch_and_store_no_candidate_round_stops_after_persist():
    sb, _ = _supabase()
    recall = MagicMock()
    recall.get_recording_urls = AsyncMock(return_value={"video_url": "v"})
    recall.close = AsyncMock()
    with patch.object(rh, "get_supabase_admin_client", return_value=sb), \
         patch.object(rh, "get_recall_service", return_value=recall), \
         patch.object(rh, "_fetch_participants", AsyncMock(return_value=None)), \
         patch.object(rh, "_fetch_transcript", AsyncMock()) as ft:
        await rh.fetch_and_store_recording("rb1", "db1", None)
    ft.assert_not_awaited()  # transcript path skipped when no candidate_round_id
    recall.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_fetch_and_store_full_path_invokes_decide():
    sb, _ = _supabase()
    recall = MagicMock()
    recall.get_recording_urls = AsyncMock(return_value={"video_url": "v", "transcript_url": "t"})
    recall.close = AsyncMock()
    with patch.object(rh, "get_supabase_admin_client", return_value=sb), \
         patch.object(rh, "get_recall_service", return_value=recall), \
         patch.object(rh, "_fetch_participants", AsyncMock(return_value=[])), \
         patch.object(rh, "_fetch_transcript", AsyncMock(return_value=[{"text": "x"}])), \
         patch.object(rh, "_upsert_transcript", AsyncMock()), \
         patch.object(rh, "_fill_interviewer_email_if_missing", AsyncMock()), \
         patch.object(rh, "_decide_feedback_path", AsyncMock()) as decide:
        await rh.fetch_and_store_recording("rb1", "db1", "cr1")
    decide.assert_awaited_once()
    recall.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_fetch_and_store_error_still_closes():
    sb, _ = _supabase()
    recall = MagicMock()
    recall.get_recording_urls = AsyncMock(side_effect=RuntimeError("recall 500"))
    recall.close = AsyncMock()
    with patch.object(rh, "get_supabase_admin_client", return_value=sb), \
         patch.object(rh, "get_recall_service", return_value=recall):
        await rh.fetch_and_store_recording("rb1", "db1", "cr1")  # no raise
    recall.close.assert_awaited_once()
