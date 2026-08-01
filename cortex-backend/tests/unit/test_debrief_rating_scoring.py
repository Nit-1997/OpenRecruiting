"""Unit tests for the rating-based scoring spine (spec 2026-06-08 §2/§4).

The debrief score is now driven by `candidate_rounds.rating` (a 5-point panel
decision per round), averaged across a candidate's rated rounds and rescaled onto
the FE 1–4 contract. Cortex/competency is supplemental. These tests pin the pure
scorer surface that replaces the competency `aggregate`/`verdict`/`confidence`.
"""

import pytest

from src.service.debrief.scorer import DebriefScorer


@pytest.fixture
def scorer() -> DebriefScorer:
    return DebriefScorer()


# ---------------------------------------------------------------------------
# R2 — point mapping + average
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "rating,points",
    [("strong_no", 1), ("no", 2), ("maybe", 3), ("yes", 4), ("strong_yes", 5)],
)
def test_rating_points_maps_each_vote(scorer, rating, points):
    assert scorer.rating_points(rating) == points


def test_rating_points_unknown_or_none_is_none(scorer):
    assert scorer.rating_points("garbage") is None
    assert scorer.rating_points(None) is None


def test_rating_average_of_valid_ratings(scorer):
    # (strong_yes 5 + yes 4) / 2 = 4.5
    assert scorer.rating_average(["strong_yes", "yes"]) == 4.5


def test_rating_average_single(scorer):
    assert scorer.rating_average(["maybe"]) == 3.0


def test_rating_average_empty_is_none(scorer):
    assert scorer.rating_average([]) is None


def test_rating_average_ignores_unrated_rounds(scorer):
    # None / unknown ratings are excluded from the mean (not scorable).
    assert scorer.rating_average(["yes", None, "garbage"]) == 4.0


def test_rating_average_all_invalid_is_none(scorer):
    assert scorer.rating_average([None, "nope"]) is None


# ---------------------------------------------------------------------------
# R4 — rescale 1..5 → the FE 1..4 contract
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "avg_five,expected_four",
    [
        (5.0, 4.0),   # strong_yes anchors the top of the scale
        (1.0, 1.0),   # strong_no anchors the floor
        (3.0, 2.5),   # 1 + 2*0.75
        (4.0, 3.2),  # 1 + 3*0.75 = 3.25 → 3.2 (round to 1 decimal, as cells do)
        (4.5, 3.6),   # 1 + 3.5*0.75 = 3.625 → 3.6 (1-decimal)
        (4.25, 3.4),  # 1 + 3.25*0.75 = 3.4375 → 3.4
    ],
)
def test_rescale_to_four(scorer, avg_five, expected_four):
    assert scorer.rescale_to_four(avg_five) == expected_four


# ---------------------------------------------------------------------------
# §4 — verdict bands from the 1..5 average
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "avg_five,verdict",
    [
        (4.5, "strong_hire"),
        (4.25, "strong_hire"),   # boundary inclusive
        (4.24, "hire"),
        (3.5, "hire"),           # boundary inclusive
        (3.49, "mixed"),
        (2.5, "mixed"),          # boundary inclusive
        (2.49, "no_hire"),
        (1.0, "no_hire"),
    ],
)
def test_verdict_from_average_bands(scorer, avg_five, verdict):
    assert scorer.verdict_from_average(avg_five) == verdict


def test_verdict_from_average_none_is_mixed(scorer):
    # No rated rounds → honest 'mixed', never a fabricated hire/no_hire.
    assert scorer.verdict_from_average(None) == "mixed"


# ---------------------------------------------------------------------------
# §4 — confidence from rating volume + disagreement (+ corroboration when present)
# ---------------------------------------------------------------------------
def test_confidence_high_when_many_agreeing_rounds_and_corroborated(scorer):
    # 3 rated rounds, spread 1 (5..4), corroboration ≥ ceil(2/2)=1 → high.
    out = scorer.confidence_from_ratings(
        ["strong_yes", "yes", "yes"], corroboration_count=1, must_have_count=2
    )
    assert out == "high"


def test_confidence_high_with_no_must_haves_skips_corroboration(scorer):
    # must_have_count 0 → the corroboration clause is vacuously satisfied.
    out = scorer.confidence_from_ratings(
        ["yes", "yes", "yes"], corroboration_count=0, must_have_count=0
    )
    assert out == "high"


def test_confidence_low_single_round(scorer):
    assert scorer.confidence_from_ratings(["yes"], 5, 2) == "low"


def test_confidence_low_split_panel(scorer):
    # A strong_yes next to a strong_no (spread 4) → low, even with 3 rounds.
    out = scorer.confidence_from_ratings(
        ["strong_yes", "strong_no", "yes"], corroboration_count=5, must_have_count=2
    )
    assert out == "low"


def test_confidence_medium_two_rounds(scorer):
    assert scorer.confidence_from_ratings(["yes", "yes"], 2, 0) == "medium"


def test_confidence_medium_when_corroboration_insufficient(scorer):
    # 3 agreeing rounds but corroboration 1 < ceil(4/2)=2 → can't reach high.
    out = scorer.confidence_from_ratings(
        ["yes", "yes", "yes"], corroboration_count=1, must_have_count=4
    )
    assert out == "medium"


def test_confidence_low_empty(scorer):
    assert scorer.confidence_from_ratings([], 0, 0) == "low"
