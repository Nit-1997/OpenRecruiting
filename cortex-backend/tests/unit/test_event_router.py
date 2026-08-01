from unittest.mock import MagicMock
from src.service.event_router import EventRouter


def test_event_router_supports_episodic_events():
    router = EventRouter(
        feedback_handler=MagicMock(),
        plan_handler=MagicMock(),
        decision_handler=MagicMock(),
        question_summaries_available=MagicMock(),
        intake_transcript_available=MagicMock(),
        feedback_debrief_available=MagicMock(),
        interview_transcript_available=MagicMock(),
        jd_available=MagicMock(),
    )
    assert router.get_handler("question_summaries_available") is not None
    assert router.get_handler("intake_transcript_available") is not None
    assert router.get_handler("feedback_debrief_available") is not None
    assert router.get_handler("interview_transcript_available") is not None
    assert router.get_handler("jd_available") is not None
    assert router.get_handler("nonexistent") is None


def test_event_router_backward_compatible():
    router = EventRouter(
        feedback_handler=MagicMock(),
        plan_handler=MagicMock(),
        decision_handler=MagicMock(),
    )
    assert router.get_handler("feedback_completed") is not None
    assert router.get_handler("question_summaries_available") is None
    assert len(router.supported_events) == 3
