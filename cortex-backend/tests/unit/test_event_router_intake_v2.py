"""Test that the EventRouter routes intake_v2_completed to IntakeV2Handler."""
from unittest.mock import MagicMock
from src.service.event_router import EventRouter
from src.service.handlers.intake_v2_handler import IntakeV2Handler


def test_router_routes_intake_v2_completed():
    v2_handler = MagicMock(spec=IntakeV2Handler)
    router = EventRouter(
        feedback_handler=MagicMock(),
        plan_handler=MagicMock(),
        decision_handler=MagicMock(),
        intake_v2_completed=v2_handler,
    )
    assert router.get_handler("intake_v2_completed") is v2_handler
    assert "intake_v2_completed" in router.supported_events


def test_router_v2_independent_from_v1_intake():
    v1 = MagicMock()
    v2 = MagicMock(spec=IntakeV2Handler)
    router = EventRouter(
        feedback_handler=MagicMock(),
        plan_handler=MagicMock(),
        decision_handler=MagicMock(),
        intake_transcript_available=v1,
        intake_v2_completed=v2,
    )
    assert router.get_handler("intake_transcript_available") is v1
    assert router.get_handler("intake_v2_completed") is v2


def test_router_omits_v2_when_not_provided():
    router = EventRouter(
        feedback_handler=MagicMock(),
        plan_handler=MagicMock(),
        decision_handler=MagicMock(),
    )
    assert "intake_v2_completed" not in router.supported_events
    assert router.get_handler("intake_v2_completed") is None
