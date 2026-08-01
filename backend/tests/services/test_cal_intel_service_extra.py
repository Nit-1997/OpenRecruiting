"""Characterization tests for calendar_intelligence_service functions not yet
covered: analyze_event, llm_classify_and_extract, resolve_organizer,
match_candidate, resolve_candidate_name.
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

import app.services.calendar_intelligence_service as cis


def _event(start, end, summary="Alice <> Acme", external_email="alice@external.com",
           internal_email="rec@acme.com", meeting_url="https://zoom.us/j/123",
           tz="America/New_York"):
    return {
        "raw": {
            "summary": summary,
            "start": {"dateTime": start, "timeZone": tz},
            "end": {"dateTime": end, "timeZone": tz},
            "conferenceData": {
                "entryPoints": [{"entryPointType": "video", "uri": meeting_url}],
            },
            "attendees": [
                {"email": external_email, "displayName": "Alice Ext"},
                {"email": internal_email, "displayName": "Rec Internal"},
            ],
            "id": "evt1",
            "description": "Interview with Alice",
            "location": "Remote",
        },
    }


# ----------------------- analyze_event -----------------------

def test_analyze_event_no_meeting_url_none():
    ev = {"raw": {"summary": "x", "attendees": []}}
    assert cis.analyze_event(ev, "acme.com") is None


def test_analyze_event_no_external_none():
    ev = _event("2025-01-01T10:00:00", "2025-01-01T10:45:00", external_email="rec@acme.com")
    # both attendees internal -> no external
    assert cis.analyze_event(ev, "acme.com") is None


def test_analyze_event_duration_too_short_none():
    ev = _event("2025-01-01T10:00:00", "2025-01-01T10:10:00")  # 10 min
    assert cis.analyze_event(ev, "acme.com") is None


def test_analyze_event_happy_path():
    ev = _event("2025-01-01T10:00:00", "2025-01-01T10:45:00")
    out = cis.analyze_event(ev, "acme.com")
    assert out is not None
    assert out["event_title"] == "Alice <> Acme"
    assert out["duration_minutes"] == 45
    assert out["meeting_platform"] is not None
    assert len(out["external_attendees"]) == 1


def test_analyze_event_recurring_skipped():
    ev = _event("2025-01-01T10:00:00", "2025-01-01T10:45:00")
    ev["raw"]["recurringEventId"] = "rec1"
    assert cis.analyze_event(ev, "acme.com") is None


def test_analyze_event_missing_times_none():
    ev = _event("2025-01-01T10:00:00", "2025-01-01T10:45:00")
    ev["raw"]["start"] = {}
    ev["raw"]["end"] = {}
    assert cis.analyze_event(ev, "acme.com") is None


# ----------------------- llm_classify_and_extract -----------------------

@pytest.mark.asyncio
async def test_llm_classify_no_api_key_none():
    from types import SimpleNamespace
    with patch.object(cis, "get_settings", lambda: SimpleNamespace(ANTHROPIC_API_KEY="")):
        assert (await cis.llm_classify_and_extract({"event_title": "x"})) is None


@pytest.mark.asyncio
async def test_llm_classify_happy_path():
    from types import SimpleNamespace
    analyzed = {
        "event_title": "Alice <> Eng", "location": "NYC", "meeting_platform": "zoom",
        "duration_minutes": 45, "description": "interview",
        "external_attendees": [{"display_name": "Alice", "email": "alice@x.com"}],
        "internal_attendees": [{"display_name": "Rec", "email": "rec@acme.com"}],
    }
    content = (
        '{"is_interview": true, "confidence": 0.9, "reasoning": "clear", '
        '"role_name": "Engineer", "round_name": "Phone Screen", '
        '"candidate_name": "Alice", "location": "NYC"}'
    )
    resp = httpx.Response(
        200, json={"content": [{"text": content}]},
        request=httpx.Request("POST", "https://api.anthropic.com/v1/messages"),
    )

    class _Client:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, *a, **k): return resp

    with patch.object(cis, "get_settings", lambda: SimpleNamespace(
            ANTHROPIC_API_KEY="key", CALENDAR_INTELLIGENCE_MODEL="claude-haiku")), \
         patch.object(cis.httpx, "AsyncClient", lambda *a, **k: _Client()):
        out = await cis.llm_classify_and_extract(analyzed)
    assert out["is_interview"] is True
    assert out["confidence"] == 0.9
    assert out["role_name"] == "Engineer"


# ----------------------- resolve_organizer -----------------------

def test_resolve_organizer_by_organizer_email():
    event = {"raw": {"organizer": {"email": "Rec@Acme.com"}, "attendees": []}}
    users = {"rec@acme.com": {"profile_id": "p1"}}
    assert cis.resolve_organizer(event, users) == "p1"


def test_resolve_organizer_by_attendee():
    event = {"raw": {"organizer": {"email": "ext@x.com"}, "attendees": [{"email": "Rec@Acme.com"}]}}
    users = {"rec@acme.com": {"profile_id": "p2"}}
    assert cis.resolve_organizer(event, users) == "p2"


def test_resolve_organizer_none():
    event = {"raw": {"organizer": {"email": "ext@x.com"}, "attendees": [{"email": "other@x.com"}]}}
    assert cis.resolve_organizer(event, {}) is None


# ----------------------- match_candidate -----------------------

@pytest.mark.asyncio
async def test_match_candidate_empty_email():
    assert (await cis.match_candidate("", "req1")) is None


@pytest.mark.asyncio
async def test_match_candidate_found():
    sb = MagicMock()
    builder = MagicMock()
    for attr in ("select", "eq", "is_"):
        setattr(builder, attr, MagicMock(return_value=builder))
    builder.execute_async = AsyncMock(return_value=MagicMock(data=[{"id": "c1", "name": "Alice", "email": "a@x.com"}]))
    sb.table = MagicMock(return_value=builder)
    with patch.object(cis, "get_supabase_admin_client", return_value=sb):
        out = await cis.match_candidate("A@X.com", "req1")
    assert out["id"] == "c1"


@pytest.mark.asyncio
async def test_match_candidate_none():
    sb = MagicMock()
    builder = MagicMock()
    for attr in ("select", "eq", "is_"):
        setattr(builder, attr, MagicMock(return_value=builder))
    builder.execute_async = AsyncMock(return_value=MagicMock(data=[]))
    sb.table = MagicMock(return_value=builder)
    with patch.object(cis, "get_supabase_admin_client", return_value=sb):
        assert (await cis.match_candidate("a@x.com", "req1")) is None


# ----------------------- resolve_candidate_name -----------------------

def test_resolve_candidate_name_from_attendee_display():
    analyzed = {
        "event_title": "Interview",
        "external_attendees": [{"email": "alice@x.com", "display_name": "Alice Wonderland"}],
        "internal_attendees": [],
    }
    out = cis.resolve_candidate_name(analyzed, "alice@x.com")
    assert "Alice" in out


def test_resolve_candidate_name_falls_back_to_email_local():
    analyzed = {"event_title": "Sync", "external_attendees": [], "internal_attendees": []}
    out = cis.resolve_candidate_name(analyzed, "bob.jones@x.com")
    assert out == "Bob Jones"
