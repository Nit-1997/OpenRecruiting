"""Tests for the deterministic ai_screenable eligibility fallback.

OpenRecruiting hosts an actual *screen* — a first/early conversational recruiter-style
round. A round is screenable when EITHER its name/category names a screen, OR it
is the first round and its category is conversational (and not an exercise). An
explicit stored `True` always wins. Later behavioral / technical / hiring-manager
rounds are NOT screenable.
"""

import pytest

from app.api.v2.services.plan_service import _derive_screenable


# --------------------------------------------------------------------------- #
# _derive_screenable — pure helper                                            #
# --------------------------------------------------------------------------- #


def test_first_conversational_with_screen_name_is_true():
    assert _derive_screenable(False, "culture", 1, "Recruiter Screen") is True


def test_first_conversational_behavioral_is_true():
    # First round + conversational category, even without a screen keyword.
    assert _derive_screenable(False, "behavioral", 1, "Behavioral Screen") is True


def test_later_behavioral_round_is_false():
    # Round 3 hiring-manager behavioral is NOT a screen.
    assert (
        _derive_screenable(False, "behavioral", 3, "Hiring Manager Behavioral")
        is False
    )


def test_later_design_round_is_false():
    assert _derive_screenable(False, "design", 2, "Product Sense") is False


def test_later_case_study_round_is_false():
    assert _derive_screenable(False, "domain", 4, "Case Study") is False


def test_first_exercise_round_is_false():
    # First round but an exercise category — a voice agent cannot run it.
    assert _derive_screenable(False, "technical", 1, "Coding Interview") is False


def test_screen_keyword_wins_regardless_of_position():
    # A phone screen at round 2 is still a screen by name.
    assert (
        _derive_screenable(False, "culture", 2, "Recruiter Phone Screen") is True
    )


def test_explicit_stored_true_wins():
    assert _derive_screenable(True, "design", 2, "Whatever") is True


# --------------------------------------------------------------------------- #
# screen-by-name / category keyword matches                                   #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "name",
    [
        "Recruiter Screen",
        "Recruiter Call",
        "Phone Screen",
        "Phone Screening",
        "Initial Screen",
        "Intro Call",
        "Technical Screening",  # 'screening' substring, even with exercise-y word
    ],
)
def test_screen_name_keywords_match(name):
    # These names mark a screen regardless of round position/category.
    assert _derive_screenable(False, "behavioral", 5, name) is True


def test_bare_screen_word_matches_as_token():
    assert _derive_screenable(False, "behavioral", 5, "Recruiter Screen") is True


def test_substring_screen_does_not_falsely_match():
    # 'screen' must be a whole word — 'Screenwriter Panel' must NOT match.
    assert _derive_screenable(False, "design", 2, "Screenwriter Panel") is False


@pytest.mark.parametrize("category", ["screening", "recruiter"])
def test_screen_category_keyword_matches(category):
    # A screening/recruiter category names a screen on its own.
    assert _derive_screenable(False, category, 5, "Anything") is True


# --------------------------------------------------------------------------- #
# first-round detection via order_index fallback                              #
# --------------------------------------------------------------------------- #


def test_order_index_zero_is_first_when_round_number_absent():
    # round_number absent → order_index 0 counts as the first round.
    assert _derive_screenable(False, "culture", 0, "Culture Fit") is True


def test_missing_or_blank_category_is_false():
    assert _derive_screenable(False, None, 1, "Some Round") is False
    assert _derive_screenable(None, None, 1, "Some Round") is False
    assert _derive_screenable(False, "", 1, "Some Round") is False


def test_first_motivation_round_is_true():
    assert _derive_screenable(False, "motivation", 1, "Motivation Chat") is True
