"""Schema tests for the source_context and claim_strength fields."""
from src.models.pydantic_models import (
    EnrichedFeedbackItem,
    FeedbackBullet,
    FeedbackItem,
)


def test_feedback_item_has_source_context_with_default():
    item = FeedbackItem(feedback="x", antifeedback="y", sentiment="positive")
    assert item.source_context == ""


def test_feedback_item_accepts_source_context():
    item = FeedbackItem(
        feedback="x", antifeedback="y", sentiment="positive",
        source_context="surrounding sentences from the monologue",
    )
    assert item.source_context == "surrounding sentences from the monologue"


def test_enriched_feedback_item_has_source_context_with_default():
    item = EnrichedFeedbackItem(
        topic_id="T1", topic_heading="H",
        feedback="x", antifeedback="y", sentiment="positive",
        feedback_evidence=[], antifeedback_evidence=[], reasoning="r",
    )
    assert item.source_context == ""


def test_feedback_bullet_has_source_context_with_default():
    b = FeedbackBullet(feedback_bullet="x", antifeedback_bullet="y")
    assert b.source_context == ""
    assert b.sentiment == "neutral"


def test_feedback_item_has_claim_strength_with_default():
    item = FeedbackItem(feedback="x", antifeedback="y", sentiment="positive")
    assert item.claim_strength == "primary"


def test_feedback_item_accepts_claim_strength_passing():
    item = FeedbackItem(
        feedback="x", antifeedback="y", sentiment="positive",
        claim_strength="passing",
    )
    assert item.claim_strength == "passing"
