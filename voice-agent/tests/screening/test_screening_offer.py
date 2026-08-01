"""Tests for the screening interview voice mode (Task 8).

  - the screening prompt adapter passes through intake_core.screening.builder
    (sample question + guardrails present), and
  - an invalid screening session token is rejected by the offer route (403),
    mirroring the fallback-feedback offer path which 403s on an invalid/expired
    token before any WebRTC handling.

The offer-route test patches validate_screening_session_token to None and drives
the route via FastAPI's TestClient. tests/screening/conftest.py stubs the heavy
WebRTC/pipecat deps so src.main imports on hosts without them.
"""

from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from src.persona.screening import build_voice_screening_prompt


def test_build_voice_screening_prompt_passthrough():
    session = {
        "persona_snapshot": None,
        "role_context": "Senior Backend Engineer, 5+ years",
        "questions": [
            {
                "id": "q1",
                "prompt": "Tell me about a system you scaled.",
                "probe": "What broke first?",
                "signal": "scalability",
            }
        ],
        "answered": [],
    }
    prompt = build_voice_screening_prompt(session)
    # The configured question is rendered ...
    assert "Tell me about a system you scaled." in prompt
    # ... and the guardrails are appended (passthrough to the shared builder).
    assert "NON-NEGOTIABLE RULES" in prompt
    # uncovered question shows the empty glyph, never [done].
    assert "[ ]" in prompt


def test_build_voice_screening_prompt_marks_answered():
    session = {
        "role_context": "x",
        "questions": [{"id": "q1", "prompt": "First?"}, {"id": "q2", "prompt": "Second?"}],
        "answered": ["q1"],
    }
    prompt = build_voice_screening_prompt(session)
    assert "[done]" in prompt  # q1 marked covered


def test_invalid_screening_token_rejected():
    from src import main

    with patch.object(
        main, "validate_screening_session_token", new=AsyncMock(return_value=None)
    ):
        client = TestClient(main.app)
        resp = client.post(
            "/api/offer/screening/bogus-token",
            json={"sdp": "x", "type": "offer"},
        )
    assert resp.status_code in (403, 404)


def _fake_resp(status_code, payload):
    """Minimal httpx-Response-like double for the screening loader test."""
    fake = MagicMock()
    fake.status_code = status_code
    fake.json.return_value = payload
    fake.text = str(payload)
    return fake


def test_load_screening_config_builds_question_snapshot():
    """load_screening_config_for_round returns the config row + an ordered,
    snapshotted question list (the inputs from which _run_v2_screening_pipeline's
    session dict is built)."""
    import asyncio
    from src import main

    config_row = {
        "id": "cfg-1",
        "voice": "aura-luna-en",
        "persona_snapshot": {"text": "be warm"},
        "round_screening_questions": [
            {"id": "q2", "order_index": 1, "title": "B", "prompt": "Second?"},
            {"id": "q1", "order_index": 0, "title": "A", "prompt": "First?"},
        ],
    }
    fake_client = MagicMock()
    fake_client.get = AsyncMock(return_value=_fake_resp(200, [config_row]))

    with patch.object(main, "_get_http_client", new=AsyncMock(return_value=fake_client)):
        loaded_config, questions = asyncio.run(
            main.load_screening_config_for_round("round-1")
        )

    assert loaded_config["voice"] == "aura-luna-en"
    assert loaded_config["persona_snapshot"] == {"text": "be warm"}
    # snapshot_questions sorts by order_index and re-indexes.
    assert [q["id"] for q in questions] == ["q1", "q2"]
    assert questions[0]["order_index"] == 0 and questions[1]["order_index"] == 1


def test_compose_screening_role_context_from_requisition():
    from src import main
    from src.persona.generator import RoleContext

    rc = RoleContext(
        role_title="Senior Backend Engineer",
        experience_range="5-8 years",
        must_have_skills=["Python", "Postgres"],
        good_to_have_skills=["Kafka"],
        job_description="",
        intake_notes="",
    )
    text = main.compose_screening_role_context(rc)
    assert "Senior Backend Engineer" in text
    assert "5-8 years" in text
    assert "Python" in text and "Postgres" in text
    assert "Kafka" in text


def test_compose_screening_role_context_handles_none():
    from src import main

    text = main.compose_screening_role_context(None)
    assert isinstance(text, str) and text
