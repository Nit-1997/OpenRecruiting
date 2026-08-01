"""Test SupabaseFetcher.fetch_intake_v2_session."""
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from src.service.supabase_fetcher import SupabaseFetcher


@pytest.mark.asyncio
async def test_fetch_intake_v2_session_assembles_packet():
    row = {
        "id": "s1",
        "requisition_id": "r1",
        "organization_id": "o1",
        "user_id": "u1",
        "form_data": {
            "role_name": "Senior BE",
            "location": "NYC",
            "experience_min": 5,
            "experience_max": 8,
        },
        "current_answers": {
            "q4_must_haves": {"text": "Python, PG", "status": "validated"},
            "q5_nice_to_haves": {"text": "Kafka", "status": "validated"},
            "q6_cultural_fit": {"text": "ownership, directness", "status": "validated"},
        },
        "turns": [{"role": "user", "content": "hi", "modality": "voice"}],
        "modalities_used": ["voice"],
        "duration_min": 4.5,
        "questions_version": "v1-2026-05-27",
        "interview_plan": {
            "rounds": [
                {
                    "name": "Coding",
                    "category": "coding",
                    "feedback_questions": [{"heading": "Code Quality", "description": "x"}],
                },
            ]
        },
    }

    mock_client = MagicMock()
    execute_mock = AsyncMock(return_value=MagicMock(data=[row]))
    eq_mock = MagicMock()
    eq_mock.execute = execute_mock
    select_mock = MagicMock()
    select_mock.eq = MagicMock(return_value=eq_mock)
    table_mock = MagicMock()
    table_mock.select = MagicMock(return_value=select_mock)
    mock_client.table = MagicMock(return_value=table_mock)

    fetcher = SupabaseFetcher()
    with patch.object(fetcher, "_get_client", AsyncMock(return_value=mock_client)):
        packet = await fetcher.fetch_intake_v2_session(session_id="s1")

    assert packet.session_id == "s1"
    assert packet.requisition_id == "r1"
    assert packet.organization_id == "o1"
    assert packet.role_title == "Senior BE"
    assert packet.role_location == "NYC"
    assert packet.experience_min_years == 5
    assert packet.current_answers["q4_must_haves"]["text"] == "Python, PG"
    assert len(packet.rounds) == 1
    assert packet.rounds[0]["name"] == "Coding"
    assert packet.modalities_used == ["voice"]
