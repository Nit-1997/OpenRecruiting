"""Characterization tests for app/api/v2/services/recording_service.py:
_parse_iso_utc, _flatten_recall_segment, get_recording_url (cache hit/miss,
not-ready, Recall error), _lazy_ingest_transcript_from_recall, get_transcript.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import httpx
import pytest

from app.api.v2.core.exceptions import NotFoundError, UpstreamServiceError
from app.api.v2.services import recording_service as rs

CR_ID = uuid4()
ORG_ID = "org-1"


# ----------------------- _parse_iso_utc -----------------------

def test_parse_iso_utc_none():
    assert rs._parse_iso_utc(None) is None


def test_parse_iso_utc_datetime_naive_gets_utc():
    dt = datetime(2025, 1, 1)
    out = rs._parse_iso_utc(dt)
    assert out.tzinfo == timezone.utc


def test_parse_iso_utc_string_z():
    out = rs._parse_iso_utc("2025-01-01T00:00:00Z")
    assert out.tzinfo is not None


def test_parse_iso_utc_bad_string():
    assert rs._parse_iso_utc("garbage") is None


# ----------------------- _flatten_recall_segment -----------------------

def test_flatten_segment_happy():
    raw = {
        "participant": {"name": "Bob"},
        "words": [
            {"text": "Hello", "start_timestamp": {"relative": 1.0}, "end_timestamp": {"relative": 1.5}},
            {"text": "there", "start_timestamp": {"relative": 1.6}, "end_timestamp": {"relative": 2.0}},
        ],
    }
    out = rs._flatten_recall_segment(raw)
    assert out["speaker"] == "Bob"
    assert out["text"] == "Hello there"
    assert out["ts_start"] == 1.0
    assert out["ts_end"] == 2.0


def test_flatten_segment_no_words():
    assert rs._flatten_recall_segment({"words": []}) is None


def test_flatten_segment_blank_text():
    assert rs._flatten_recall_segment({"words": [{"text": ""}]}) is None


# ----------------------- get_recording_url -----------------------

def _recording_supabase(bot_rows, update_ok=True):
    sb = MagicMock()
    builder = MagicMock()
    for attr in ("select", "eq", "order", "limit", "update"):
        setattr(builder, attr, MagicMock(return_value=builder))
    builder.execute_async = AsyncMock(return_value=MagicMock(data=bot_rows))
    sb.table = MagicMock(return_value=builder)
    return sb


@pytest.mark.asyncio
async def test_recording_url_no_bot_404():
    sb = _recording_supabase([])
    with patch.object(rs, "load_cr_with_round_for_org", AsyncMock()):
        with pytest.raises(NotFoundError):
            await rs.get_recording_url(sb, ORG_ID, CR_ID)


@pytest.mark.asyncio
async def test_recording_url_not_ready_409():
    sb = _recording_supabase([{"id": "b1", "recall_bot_id": "rb1", "status": "processing"}])
    with patch.object(rs, "load_cr_with_round_for_org", AsyncMock()):
        with pytest.raises(Exception) as exc:
            await rs.get_recording_url(sb, ORG_ID, CR_ID)
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_recording_url_cache_hit():
    future = (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()
    sb = _recording_supabase([{
        "id": "b1", "recall_bot_id": "rb1", "status": "done",
        "recording_url": "https://cached", "recording_url_expires_at": future,
    }])
    with patch.object(rs, "load_cr_with_round_for_org", AsyncMock()):
        out = await rs.get_recording_url(sb, ORG_ID, CR_ID)
    assert out["url"] == "https://cached"


@pytest.mark.asyncio
async def test_recording_url_follows_origin_for_untracked_copy():
    """An untracked-copy round has no recall_bots row of its own (recall_bot_id
    is globally unique). get_recording_url must follow origin_candidate_round_id
    to the source round's bot so Round Replay works on the merged round."""
    future = (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()
    origin_bot = {
        "id": "b1", "recall_bot_id": "rb1", "status": "done",
        "recording_url": "https://origin-recording", "recording_url_expires_at": future,
    }

    # Table-routed fake. The recall_bots exec mock is SHARED across builder
    # instances so its FIFO spans both lookups: own (-> []) then origin (-> bot).
    recall_exec = AsyncMock(side_effect=[
        MagicMock(data=[]),            # own lookup -> none
        MagicMock(data=[origin_bot]),  # origin lookup -> bot
    ])
    cr_exec = AsyncMock(return_value=MagicMock(
        data=[{"origin_candidate_round_id": "origin-cr-1"}]))
    sb = MagicMock()

    def table(name):
        b = MagicMock()
        for attr in ("select", "eq", "order", "limit", "update"):
            setattr(b, attr, MagicMock(return_value=b))
        if name == "recall_bots":
            b.execute_async = recall_exec
        elif name == "candidate_rounds":
            b.execute_async = cr_exec
        else:
            b.execute_async = AsyncMock(return_value=MagicMock(data=[]))
        return b

    sb.table = MagicMock(side_effect=table)
    with patch.object(rs, "load_cr_with_round_for_org", AsyncMock()):
        out = await rs.get_recording_url(sb, ORG_ID, CR_ID)
    assert out["url"] == "https://origin-recording"


@pytest.mark.asyncio
async def test_recording_url_cache_miss_remints():
    sb = _recording_supabase([{
        "id": "b1", "recall_bot_id": "rb1", "status": "done",
        "recording_url": None, "recording_url_expires_at": None,
    }])
    recall = MagicMock()
    recall.get_recording_urls = AsyncMock(return_value={"video_url": "https://fresh"})
    recall.close = AsyncMock()
    with patch.object(rs, "load_cr_with_round_for_org", AsyncMock()), \
         patch("app.services.recall_service.get_recall_service", return_value=recall):
        out = await rs.get_recording_url(sb, ORG_ID, CR_ID)
    assert out["url"] == "https://fresh"
    recall.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_recording_url_recall_returns_no_url_409():
    sb = _recording_supabase([{
        "id": "b1", "recall_bot_id": "rb1", "status": "done",
        "recording_url": None, "recording_url_expires_at": None,
    }])
    recall = MagicMock()
    recall.get_recording_urls = AsyncMock(return_value={})
    recall.close = AsyncMock()
    with patch.object(rs, "load_cr_with_round_for_org", AsyncMock()), \
         patch("app.services.recall_service.get_recall_service", return_value=recall):
        with pytest.raises(Exception) as exc:
            await rs.get_recording_url(sb, ORG_ID, CR_ID)
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_recording_url_recall_error_502():
    from app.services.recall_service import RecallServiceError
    sb = _recording_supabase([{
        "id": "b1", "recall_bot_id": "rb1", "status": "done",
        "recording_url": None, "recording_url_expires_at": None,
    }])
    recall = MagicMock()
    recall.get_recording_urls = AsyncMock(side_effect=RecallServiceError("boom"))
    recall.close = AsyncMock()
    with patch.object(rs, "load_cr_with_round_for_org", AsyncMock()), \
         patch("app.services.recall_service.get_recall_service", return_value=recall):
        with pytest.raises(UpstreamServiceError):
            await rs.get_recording_url(sb, ORG_ID, CR_ID)


# ----------------------- _lazy_ingest_transcript_from_recall -----------------------

@pytest.mark.asyncio
async def test_lazy_ingest_fetches_and_upserts():
    sb = MagicMock()
    builder = MagicMock()
    builder.upsert.return_value = builder
    builder.execute_async = AsyncMock(return_value=MagicMock(data=[{}]))
    sb.table.return_value = builder
    http = MagicMock()
    http.get = AsyncMock(return_value=httpx.Response(200, json=[{"words": [{"text": "hi"}]}]))
    with patch("app.services.supabase.get_async_http_client", return_value=http):
        out = await rs._lazy_ingest_transcript_from_recall(sb, CR_ID, "https://s3/t")
    assert out == [{"words": [{"text": "hi"}]}]


@pytest.mark.asyncio
async def test_lazy_ingest_non_200_returns_none():
    sb = MagicMock()
    http = MagicMock()
    http.get = AsyncMock(return_value=httpx.Response(404))
    with patch("app.services.supabase.get_async_http_client", return_value=http):
        assert await rs._lazy_ingest_transcript_from_recall(sb, CR_ID, "https://s3/t") is None


@pytest.mark.asyncio
async def test_lazy_ingest_empty_segments_returns_none():
    sb = MagicMock()
    http = MagicMock()
    http.get = AsyncMock(return_value=httpx.Response(200, json={"segments": []}))
    with patch("app.services.supabase.get_async_http_client", return_value=http):
        assert await rs._lazy_ingest_transcript_from_recall(sb, CR_ID, "https://s3/t") is None


# ----------------------- get_transcript -----------------------

def _transcript_supabase(cr_data, transcript_data, bot_rows):
    sb = MagicMock()

    def table(name):
        builder = MagicMock()
        for attr in ("select", "eq", "single", "order", "limit"):
            setattr(builder, attr, MagicMock(return_value=builder))
        if name == "candidate_rounds":
            builder.execute_async = AsyncMock(return_value=MagicMock(data=cr_data))
        elif name == "transcripts":
            builder.execute_async = AsyncMock(return_value=MagicMock(data=transcript_data))
        elif name == "recall_bots":
            builder.execute_async = AsyncMock(return_value=MagicMock(data=bot_rows))
        else:
            builder.execute_async = AsyncMock(return_value=MagicMock(data=[]))
        return builder

    sb.table = MagicMock(side_effect=table)
    return sb


@pytest.mark.asyncio
async def test_get_transcript_cr_not_found():
    sb = _transcript_supabase(None, None, [])
    with pytest.raises(NotFoundError):
        await rs.get_transcript(sb, ORG_ID, CR_ID)


@pytest.mark.asyncio
async def test_get_transcript_wrong_org_404():
    cr = {"candidates": {"requisitions": {"organization_id": "OTHER"}}}
    sb = _transcript_supabase(cr, None, [])
    with pytest.raises(NotFoundError):
        await rs.get_transcript(sb, ORG_ID, CR_ID)


@pytest.mark.asyncio
async def test_get_transcript_no_transcript_row_404():
    cr = {"candidates": {"requisitions": {"organization_id": ORG_ID}}}
    sb = _transcript_supabase(cr, None, [])
    with pytest.raises(NotFoundError):
        await rs.get_transcript(sb, ORG_ID, CR_ID)


@pytest.mark.asyncio
async def test_get_transcript_happy_path_flattens():
    cr = {"candidates": {"requisitions": {"organization_id": ORG_ID}}}
    transcript = {
        "segments": [{
            "participant": {"name": "Bob"},
            "words": [{"text": "Hi", "start_timestamp": {"relative": 1.0}, "end_timestamp": {"relative": 2.0}}],
        }],
        "duration_seconds": None,
        "word_count": 1,
    }
    bot_rows = [{"joined_at": "2025-01-01T00:00:00Z", "feedback_started_at": "2025-01-01T00:10:00Z",
                 "recording_duration_seconds": 120, "transcript_url": None, "transcript_ready": False}]
    sb = _transcript_supabase(cr, transcript, bot_rows)
    out = await rs.get_transcript(sb, ORG_ID, CR_ID)
    assert out["segments"][0]["speaker"] == "Bob"
    assert out["feedback_start_seconds"] == 600.0
    assert out["duration_seconds"] == 120  # recording_duration wins
