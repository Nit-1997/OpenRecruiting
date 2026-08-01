"""Unit tests for RecallService + schedule_or_replace_recall_bot (BE-T7).

Covers: meeting-url parsing, transcript/recording config builders, bot
create/schedule/get/delete/leave/chat, get_recording_urls, and the
schedule-or-replace orchestrator including the BE-A4a cancel-loop that must
swallow transient errors and still mark the row cancelled in DB.

The httpx.AsyncClient is replaced with a MagicMock via the `client` property,
so no real network. Supabase is respx-mocked at http://test-supabase.local.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from app.services import recall_service as rs
from app.services.recall_service import (
    RecallService,
    RecallServiceError,
    get_recall_service,
    schedule_or_replace_recall_bot,
)
from tests.helpers.supabase_mocks import rest_url


def _resp(status: int, json_body=None, text: str = ""):
    r = MagicMock(spec=httpx.Response)
    r.status_code = status
    r.json.return_value = json_body if json_body is not None else {}
    r.text = text
    if status >= 400:
        r.raise_for_status.side_effect = httpx.HTTPStatusError("err", request=MagicMock(), response=r)
    else:
        r.raise_for_status.return_value = None
    return r


def _svc_with_client(monkeypatch, client) -> RecallService:
    s = RecallService()
    monkeypatch.setattr(type(s), "client", property(lambda self: client))
    return s


# --------------------------------------------------------------------------
# parse_meeting_url
# --------------------------------------------------------------------------

def test_parse_meeting_url_google_meet_with_id():
    s = RecallService()
    out = s.parse_meeting_url("https://meet.google.com/abc-defg-hij")
    assert out["platform"] == "google_meet"
    assert out["meeting_id"] == "abc-defg-hij"


def test_parse_meeting_url_google_meet_no_id():
    s = RecallService()
    out = s.parse_meeting_url("https://meet.google.com/lookup/xyz")
    assert out["platform"] == "google_meet"
    assert "meeting_id" not in out


def test_parse_meeting_url_zoom_teams_webex():
    s = RecallService()
    assert s.parse_meeting_url("https://us02.zoom.us/j/123")["platform"] == "zoom"
    assert s.parse_meeting_url("https://teams.microsoft.com/l/x")["platform"] == "microsoft_teams"
    assert s.parse_meeting_url("https://teams.live.com/x")["platform"] == "microsoft_teams"
    assert s.parse_meeting_url("https://acme.webex.com/m/x")["platform"] == "webex"


def test_parse_meeting_url_unsupported_raises():
    s = RecallService()
    with pytest.raises(RecallServiceError, match="Unsupported"):
        s.parse_meeting_url("https://example.com/call")


# --------------------------------------------------------------------------
# config builders
# --------------------------------------------------------------------------

def test_build_transcript_config_deepgram_default(monkeypatch):
    s = RecallService()
    settings = rs.get_settings()
    monkeypatch.setattr(settings, "RECALL_TRANSCRIPT_PROVIDER", "deepgram", raising=False)
    monkeypatch.setattr(settings, "RECALL_TRANSCRIPT_MODEL", "nova-2", raising=False)
    monkeypatch.setattr(settings, "RECALL_TRANSCRIPT_WORD_BOOST", "alpha, beta", raising=False)
    monkeypatch.setattr(settings, "RECALL_TRANSCRIPT_SEPARATE_STREAMS", True, raising=False)
    cfg = s._build_transcript_config(settings)
    dg = cfg["provider"]["deepgram_streaming"]
    assert dg["model"] == "nova-2"
    assert dg["keywords"] == ["alpha", "beta"]
    assert cfg["diarization"]["use_separate_streams_when_available"] is True


def test_build_transcript_config_deepgram_nova3_keyterm(monkeypatch):
    s = RecallService()
    settings = rs.get_settings()
    monkeypatch.setattr(settings, "RECALL_TRANSCRIPT_PROVIDER", "deepgram", raising=False)
    monkeypatch.setattr(settings, "RECALL_TRANSCRIPT_MODEL", "nova-3", raising=False)
    monkeypatch.setattr(settings, "RECALL_TRANSCRIPT_WORD_BOOST", "x", raising=False)
    cfg = s._build_transcript_config(settings)
    assert cfg["provider"]["deepgram_streaming"]["keyterm"] == ["x"]


def test_build_transcript_config_assemblyai(monkeypatch):
    s = RecallService()
    settings = rs.get_settings()
    monkeypatch.setattr(settings, "RECALL_TRANSCRIPT_PROVIDER", "assemblyai", raising=False)
    monkeypatch.setattr(settings, "RECALL_TRANSCRIPT_WORD_BOOST", "x", raising=False)
    cfg = s._build_transcript_config(settings)
    assert "assembly_ai_v3_streaming" in cfg["provider"]
    assert cfg["provider"]["assembly_ai_v3_streaming"]["word_boost"] == ["x"]


def test_build_transcript_config_recallai_fallback(monkeypatch):
    s = RecallService()
    settings = rs.get_settings()
    monkeypatch.setattr(settings, "RECALL_TRANSCRIPT_PROVIDER", "recallai", raising=False)
    monkeypatch.setattr(settings, "RECALL_TRANSCRIPT_MODEL", "", raising=False)
    monkeypatch.setattr(settings, "RECALL_TRANSCRIPT_SEPARATE_STREAMS", False, raising=False)
    cfg = s._build_transcript_config(settings)
    assert cfg["provider"]["recallai_streaming"]["mode"] == "prioritize_accuracy"
    assert "diarization" not in cfg


def test_build_recording_config_with_webhook(monkeypatch):
    s = RecallService()
    settings = rs.get_settings()
    monkeypatch.setattr(settings, "WEBHOOK_BASE_URL", "http://host", raising=False)
    monkeypatch.setattr(settings, "RECALL_REALTIME_WEBHOOK_PATH", "api/v2/webhooks/recall/realtime", raising=False)
    cfg = s._build_recording_config(settings)
    assert cfg["realtime_endpoints"][0]["url"] == "http://host/api/v2/webhooks/recall/realtime"


def test_build_recording_config_no_webhook(monkeypatch):
    s = RecallService()
    settings = rs.get_settings()
    monkeypatch.setattr(settings, "WEBHOOK_BASE_URL", "", raising=False)
    cfg = s._build_recording_config(settings)
    assert "realtime_endpoints" not in cfg


# --------------------------------------------------------------------------
# schedule_bot
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_schedule_bot_no_api_key_raises(monkeypatch):
    s = RecallService()
    s.api_key = ""
    with pytest.raises(RecallServiceError, match="not configured"):
        await s.schedule_bot("https://meet.google.com/abc-defg-hij", datetime.now(timezone.utc), "Jane", "cr1")


@pytest.mark.asyncio
async def test_schedule_bot_success(monkeypatch):
    client = MagicMock()
    client.post = AsyncMock(return_value=_resp(201, {"id": "bot-1", "bot_name": "OpenRecruiting"}))
    s = _svc_with_client(monkeypatch, client)
    settings = rs.get_settings()
    monkeypatch.setattr(settings, "VOICE_ENABLED", False, raising=False)

    out = await s.schedule_bot("https://meet.google.com/abc-defg-hij",
                               datetime(2030, 1, 1, tzinfo=timezone.utc), "Jane", "cr1")
    assert out["id"] == "bot-1"
    body = client.post.call_args.kwargs["json"]
    assert body["meeting_url"].startswith("https://meet.google.com")
    # join_at is 45s before scheduled_at.
    assert "join_at" in body


@pytest.mark.asyncio
async def test_schedule_bot_voice_enabled_adds_output_media(monkeypatch):
    client = MagicMock()
    client.post = AsyncMock(return_value=_resp(201, {"id": "bot-1"}))
    s = _svc_with_client(monkeypatch, client)
    settings = rs.get_settings()
    monkeypatch.setattr(settings, "VOICE_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "VOICE_AGENT_URL", "http://voice", raising=False)

    out = await s.schedule_bot("https://meet.google.com/abc-defg-hij",
                               datetime(2030, 1, 1, tzinfo=timezone.utc), "Jane", "cr1")
    assert out["_voice_session_token"]
    body = client.post.call_args.kwargs["json"]
    assert "output_media" in body
    assert body["recording_config"]["include_bot_in_recording"]["audio"] is True


@pytest.mark.asyncio
async def test_schedule_bot_http_error_raises_with_details(monkeypatch):
    err_resp = _resp(422, {"detail": "bad"})
    client = MagicMock()
    client.post = AsyncMock(return_value=err_resp)
    s = _svc_with_client(monkeypatch, client)
    settings = rs.get_settings()
    monkeypatch.setattr(settings, "VOICE_ENABLED", False, raising=False)

    with pytest.raises(RecallServiceError) as exc:
        await s.schedule_bot("https://meet.google.com/abc-defg-hij",
                             datetime(2030, 1, 1, tzinfo=timezone.utc), "Jane", "cr1")
    assert exc.value.status_code == 422
    assert exc.value.details == {"detail": "bad"}


# --------------------------------------------------------------------------
# create_bot_for_intake
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_bot_for_intake_success(monkeypatch):
    client = MagicMock()
    client.post = AsyncMock(return_value=_resp(201, {"id": "intake-bot"}))
    s = _svc_with_client(monkeypatch, client)
    settings = rs.get_settings()
    monkeypatch.setattr(settings, "VOICE_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "VOICE_AGENT_URL", "http://voice", raising=False)

    out = await s.create_bot_for_intake("https://meet.google.com/abc-defg-hij", "vtoken")
    assert out["id"] == "intake-bot"
    body = client.post.call_args.kwargs["json"]
    assert "output_media" in body


@pytest.mark.asyncio
async def test_create_bot_for_intake_no_key_raises():
    s = RecallService()
    s.api_key = ""
    with pytest.raises(RecallServiceError):
        await s.create_bot_for_intake("https://meet.google.com/abc-defg-hij")


@pytest.mark.asyncio
async def test_create_bot_for_intake_http_error(monkeypatch):
    client = MagicMock()
    client.post = AsyncMock(return_value=_resp(500, text="boom"))
    s = _svc_with_client(monkeypatch, client)
    settings = rs.get_settings()
    monkeypatch.setattr(settings, "VOICE_ENABLED", False, raising=False)
    with pytest.raises(RecallServiceError) as exc:
        await s.create_bot_for_intake("https://meet.google.com/abc-defg-hij")
    assert exc.value.status_code == 500


# --------------------------------------------------------------------------
# get_bot / delete_bot / remove_bot_from_call / send_chat_message
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_bot_success(monkeypatch):
    client = MagicMock()
    client.get = AsyncMock(return_value=_resp(200, {"id": "b1"}))
    s = _svc_with_client(monkeypatch, client)
    assert (await s.get_bot("b1"))["id"] == "b1"


@pytest.mark.asyncio
async def test_get_bot_no_key_raises():
    s = RecallService()
    s.api_key = ""
    with pytest.raises(RecallServiceError):
        await s.get_bot("b1")


@pytest.mark.asyncio
async def test_get_bot_http_error_raises(monkeypatch):
    client = MagicMock()
    client.get = AsyncMock(return_value=_resp(404))
    s = _svc_with_client(monkeypatch, client)
    with pytest.raises(RecallServiceError) as exc:
        await s.get_bot("b1")
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_delete_bot_returns_true_on_2xx_and_404(monkeypatch):
    client = MagicMock()
    client.delete = AsyncMock(side_effect=[_resp(204), _resp(404), _resp(500)])
    s = _svc_with_client(monkeypatch, client)
    assert await s.delete_bot("b1") is True   # 204
    assert await s.delete_bot("b1") is True   # 404 treated as gone
    assert await s.delete_bot("b1") is False  # 500


@pytest.mark.asyncio
async def test_delete_bot_no_key_false():
    s = RecallService()
    s.api_key = ""
    assert await s.delete_bot("b1") is False


@pytest.mark.asyncio
async def test_delete_bot_http_status_error_false(monkeypatch):
    client = MagicMock()
    client.delete = AsyncMock(side_effect=httpx.HTTPStatusError("e", request=MagicMock(), response=MagicMock()))
    s = _svc_with_client(monkeypatch, client)
    assert await s.delete_bot("b1") is False


@pytest.mark.asyncio
async def test_remove_bot_from_call(monkeypatch):
    client = MagicMock()
    client.post = AsyncMock(side_effect=[_resp(200), _resp(409)])
    s = _svc_with_client(monkeypatch, client)
    assert await s.remove_bot_from_call("b1") is True
    assert await s.remove_bot_from_call("b1") is False


@pytest.mark.asyncio
async def test_remove_bot_from_call_no_key_false():
    s = RecallService()
    s.api_key = ""
    assert await s.remove_bot_from_call("b1") is False


@pytest.mark.asyncio
async def test_remove_bot_from_call_http_error_false(monkeypatch):
    client = MagicMock()
    client.post = AsyncMock(side_effect=httpx.HTTPStatusError("e", request=MagicMock(), response=MagicMock()))
    s = _svc_with_client(monkeypatch, client)
    assert await s.remove_bot_from_call("b1") is False


@pytest.mark.asyncio
async def test_send_chat_message(monkeypatch):
    client = MagicMock()
    client.post = AsyncMock(side_effect=[_resp(200), _resp(500)])
    s = _svc_with_client(monkeypatch, client)
    assert await s.send_chat_message("b1", "hi") is True
    assert await s.send_chat_message("b1", "hi") is False


@pytest.mark.asyncio
async def test_send_chat_message_no_key_false():
    s = RecallService()
    s.api_key = ""
    assert await s.send_chat_message("b1", "hi") is False


@pytest.mark.asyncio
async def test_send_chat_message_exception_false(monkeypatch):
    client = MagicMock()
    client.post = AsyncMock(side_effect=RuntimeError("network"))
    s = _svc_with_client(monkeypatch, client)
    assert await s.send_chat_message("b1", "hi") is False


# --------------------------------------------------------------------------
# get_recording_urls
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_recording_urls_no_recordings_returns_none(monkeypatch):
    s = RecallService()
    monkeypatch.setattr(s, "get_bot", AsyncMock(return_value={"recordings": []}))
    assert await s.get_recording_urls("b1") is None


@pytest.mark.asyncio
async def test_get_recording_urls_extracts_media(monkeypatch):
    s = RecallService()
    bot = {
        "recordings": [{
            "media_shortcuts": {
                "video_mixed": {"data": {"download_url": "http://video", "duration": 120}},
                "transcript": {"data": {"download_url": "http://transcript"}},
                "participant_events": {"data": {
                    "participants_download_url": "http://participants",
                    "speaker_timeline_download_url": "http://timeline",
                }},
            },
        }],
        "participants": [{"id": "p1"}],
    }
    monkeypatch.setattr(s, "get_bot", AsyncMock(return_value=bot))
    out = await s.get_recording_urls("b1")
    assert out["video_url"] == "http://video"
    assert out["video_duration"] == 120
    assert out["transcript_url"] == "http://transcript"
    assert out["participants"] == [{"id": "p1"}]
    assert out["participants_download_url"] == "http://participants"
    assert out["speaker_timeline_url"] == "http://timeline"


# --------------------------------------------------------------------------
# close + factory
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_close_aclose_and_factory():
    s = RecallService()
    fake = MagicMock()
    fake.aclose = AsyncMock()
    s._client = fake
    await s.close()
    fake.aclose.assert_awaited_once()
    assert s._client is None
    assert isinstance(get_recall_service(), RecallService)


# --------------------------------------------------------------------------
# schedule_or_replace_recall_bot orchestrator
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_schedule_or_replace_lock_held_returns_409(monkeypatch, respx_mock):
    from fastapi import HTTPException
    # Lock update returns no rows (someone else holds it); existing lock is fresh.
    fresh = datetime.now(timezone.utc).isoformat()
    # First PATCH (acquire) → []; SELECT scheduling_locked_at → fresh lock.
    respx_mock.patch(rest_url("candidate_rounds")).mock(return_value=httpx.Response(200, json=[]))
    respx_mock.get(rest_url("candidate_rounds")).mock(
        return_value=httpx.Response(200, json=[{"scheduling_locked_at": fresh}])
    )
    with pytest.raises(HTTPException) as exc:
        await schedule_or_replace_recall_bot("cr1", "https://meet.google.com/abc-defg-hij",
                                             datetime(2030, 1, 1, tzinfo=timezone.utc), "Jane")
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_schedule_or_replace_happy_path(monkeypatch, respx_mock):
    # Acquire lock succeeds (PATCH returns a row).
    respx_mock.patch(rest_url("candidate_rounds")).mock(return_value=httpx.Response(200, json=[{"id": "cr1"}]))
    # No existing active bots.
    respx_mock.get(rest_url("recall_bots")).mock(return_value=httpx.Response(200, json=[]))
    respx_mock.post(rest_url("recall_bots")).mock(return_value=httpx.Response(201, json=[{"id": "rb1"}]))

    recall = MagicMock()
    recall.schedule_bot = AsyncMock(return_value={"id": "recall-bot-1", "bot_name": "OpenRecruiting"})
    recall.close = AsyncMock()
    monkeypatch.setattr(rs, "get_recall_service", lambda: recall)

    out = await schedule_or_replace_recall_bot("cr1", "https://meet.google.com/abc-defg-hij",
                                               datetime(2030, 1, 1, tzinfo=timezone.utc), "Jane")
    assert out["recall_warning"] is None
    recall.schedule_bot.assert_awaited_once()


@pytest.mark.asyncio
async def test_schedule_or_replace_recall_error_sets_warning(monkeypatch, respx_mock):
    respx_mock.patch(rest_url("candidate_rounds")).mock(return_value=httpx.Response(200, json=[{"id": "cr1"}]))
    respx_mock.get(rest_url("recall_bots")).mock(return_value=httpx.Response(200, json=[]))

    recall = MagicMock()
    recall.schedule_bot = AsyncMock(side_effect=RecallServiceError("recall down"))
    recall.close = AsyncMock()
    monkeypatch.setattr(rs, "get_recall_service", lambda: recall)

    out = await schedule_or_replace_recall_bot("cr1", "https://meet.google.com/abc-defg-hij",
                                               datetime(2030, 1, 1, tzinfo=timezone.utc), "Jane")
    assert "recall down" in out["recall_warning"]


@pytest.mark.asyncio
async def test_schedule_or_replace_cancel_loop_swallows_transient_error(monkeypatch, respx_mock):
    """BE-A4a: a transient error while cancelling an existing bot must NOT
    propagate; the row is still marked cancelled in DB and scheduling proceeds."""
    respx_mock.patch(rest_url("candidate_rounds")).mock(return_value=httpx.Response(200, json=[{"id": "cr1"}]))
    # One existing 'joining' bot to cancel.
    respx_mock.get(rest_url("recall_bots")).mock(
        return_value=httpx.Response(200, json=[{"id": "row1", "recall_bot_id": "rb-old", "status": "joining"}])
    )
    cancel_patch = respx_mock.patch(rest_url("recall_bots")).mock(return_value=httpx.Response(200, json=[{"id": "row1"}]))
    respx_mock.post(rest_url("recall_bots")).mock(return_value=httpx.Response(201, json=[{"id": "rb1"}]))

    recall = MagicMock()
    # remove_bot_from_call raises a transient (non-HTTPStatusError) exception.
    recall.remove_bot_from_call = AsyncMock(side_effect=httpx.ConnectError("timeout"))
    recall.delete_bot = AsyncMock(return_value=True)
    recall.schedule_bot = AsyncMock(return_value={"id": "recall-new", "bot_name": "OpenRecruiting"})
    recall.close = AsyncMock()
    monkeypatch.setattr(rs, "get_recall_service", lambda: recall)

    out = await schedule_or_replace_recall_bot("cr1", "https://meet.google.com/abc-defg-hij",
                                               datetime(2030, 1, 1, tzinfo=timezone.utc), "Jane")
    assert out["recall_warning"] is None
    # Despite the transient cancel failure, the new bot was scheduled.
    recall.schedule_bot.assert_awaited_once()


@pytest.mark.asyncio
async def test_schedule_or_replace_in_call_bot_left_alone(monkeypatch, respx_mock):
    """An in-call recording bot is NOT cancelled — left to finish naturally."""
    respx_mock.patch(rest_url("candidate_rounds")).mock(return_value=httpx.Response(200, json=[{"id": "cr1"}]))
    respx_mock.get(rest_url("recall_bots")).mock(
        return_value=httpx.Response(200, json=[{"id": "row1", "recall_bot_id": "rb-live", "status": "in_call_recording"}])
    )
    respx_mock.post(rest_url("recall_bots")).mock(return_value=httpx.Response(201, json=[{"id": "rb1"}]))

    recall = MagicMock()
    recall.remove_bot_from_call = AsyncMock()
    recall.delete_bot = AsyncMock()
    recall.schedule_bot = AsyncMock(return_value={"id": "recall-new"})
    recall.close = AsyncMock()
    monkeypatch.setattr(rs, "get_recall_service", lambda: recall)

    await schedule_or_replace_recall_bot("cr1", "https://meet.google.com/abc-defg-hij",
                                         datetime(2030, 1, 1, tzinfo=timezone.utc), "Jane")
    # In-call bot must not be removed or deleted.
    recall.remove_bot_from_call.assert_not_called()
    recall.delete_bot.assert_not_called()


@pytest.mark.asyncio
async def test_schedule_or_replace_stale_lock_override(monkeypatch, respx_mock):
    """A stale lock (older than SCHEDULING_LOCK_STALE_SECONDS) is overridden."""
    stale = (datetime.now(timezone.utc) - timedelta(seconds=120)).isoformat()
    # First acquire PATCH → [] (lock held); SELECT → stale lock; override PATCH → row.
    patch_route = respx_mock.patch(rest_url("candidate_rounds"))
    patch_route.side_effect = [
        httpx.Response(200, json=[]),            # acquire fails
        httpx.Response(200, json=[{"id": "cr1"}]),  # stale override succeeds
        httpx.Response(200, json=[{"id": "cr1"}]),  # final unlock
    ]
    respx_mock.get(rest_url("candidate_rounds")).mock(
        return_value=httpx.Response(200, json=[{"scheduling_locked_at": stale}])
    )
    respx_mock.get(rest_url("recall_bots")).mock(return_value=httpx.Response(200, json=[]))
    respx_mock.post(rest_url("recall_bots")).mock(return_value=httpx.Response(201, json=[{"id": "rb1"}]))

    recall = MagicMock()
    recall.schedule_bot = AsyncMock(return_value={"id": "recall-new"})
    recall.close = AsyncMock()
    monkeypatch.setattr(rs, "get_recall_service", lambda: recall)

    out = await schedule_or_replace_recall_bot("cr1", "https://meet.google.com/abc-defg-hij",
                                               datetime(2030, 1, 1, tzinfo=timezone.utc), "Jane")
    assert out["recall_warning"] is None
    recall.schedule_bot.assert_awaited_once()
