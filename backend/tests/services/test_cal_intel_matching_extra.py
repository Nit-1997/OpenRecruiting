"""Characterization tests for cal_intel/matching pure helpers not yet covered:
_canonical_location, _location_similarity, _text_tokens, _description_overlap_ratio,
_fuzzy_round_match, _role_similarity, _coerce_timezone_name, _format_event_time,
format_event_time_for_email, _format_created_date.
"""

from datetime import datetime, timezone

from app.services.cal_intel import matching as m


# ----------------------- _canonical_location -----------------------

def test_canonical_location_empty():
    assert m._canonical_location("") == ""


def test_canonical_location_takes_first_part_and_tokenizes():
    out = m._canonical_location("San Francisco, CA, USA")
    assert "san" in out and "francisco" in out


# ----------------------- _location_similarity -----------------------

def test_location_similarity_empty():
    assert m._location_similarity("", "NYC") == 0.0


def test_location_similarity_exact_city():
    assert m._location_similarity("New York", "New York") == 1.0


def test_location_similarity_no_token_overlap():
    assert m._location_similarity("Tokyo", "Berlin") == 0.0


# ----------------------- _text_tokens / _description_overlap_ratio -----------------------

def test_text_tokens_filters_short_and_stopwords():
    toks = m._text_tokens("the Senior Backend Engineer role")
    assert "senior" in toks
    assert "the" not in toks  # stopword/short


def test_description_overlap_ratio():
    ratio = m._description_overlap_ratio("backend engineer python", "we need a backend engineer")
    assert 0 < ratio <= 1.0


def test_description_overlap_empty():
    assert m._description_overlap_ratio("", "anything") == 0.0


# ----------------------- _fuzzy_round_match -----------------------

def test_fuzzy_round_match_exact():
    assert m._fuzzy_round_match("Phone Screen", "Phone Screen") is True


def test_fuzzy_round_match_token_overlap():
    assert m._fuzzy_round_match("technical interview", "technical round") is True


def test_fuzzy_round_match_no_match():
    assert m._fuzzy_round_match("onsite", "phone screen") is False


# ----------------------- _role_similarity -----------------------

def test_role_similarity_identical():
    assert m._role_similarity("Software Engineer", "Software Engineer") >= 0.9


def test_role_similarity_unrelated():
    assert m._role_similarity("Chef", "Astronaut") < 0.5


# ----------------------- _coerce_timezone_name -----------------------

def test_coerce_tz_empty():
    assert m._coerce_timezone_name("") == ""


def test_coerce_tz_alias():
    assert m._coerce_timezone_name("EST") == "America/New_York"
    assert m._coerce_timezone_name("PST") == "America/Los_Angeles"


def test_coerce_tz_keyword():
    assert m._coerce_timezone_name("US Pacific Time") == "America/Los_Angeles"


def test_coerce_tz_ambiguous_slash_returns_empty():
    assert m._coerce_timezone_name("EST/PST") == ""


def test_coerce_tz_passthrough_unknown():
    assert m._coerce_timezone_name("Atlantis/Lost") == "Atlantis/Lost"


# ----------------------- _format_event_time -----------------------

def test_format_event_time_none():
    assert m._format_event_time(None) == "TBD"


def test_format_event_time_bad_string():
    assert m._format_event_time("not-a-date") == "TBD"


def test_format_event_time_datetime():
    dt = datetime(2025, 3, 15, 14, 30, tzinfo=timezone.utc)
    out = m._format_event_time(dt)
    assert "Mar 15" in out


def test_format_event_time_string_with_tz():
    out = m._format_event_time("2025-03-15T14:30:00Z", "EST")
    assert "Mar 15" in out


# ----------------------- format_event_time_for_email -----------------------

def test_format_event_time_for_email_includes_year():
    out = m.format_event_time_for_email("2025-03-15T14:30:00Z", "America/New_York")
    assert "2025" in out


def test_format_event_time_for_email_none():
    assert m.format_event_time_for_email(None) == "TBD"


# ----------------------- _format_created_date -----------------------

def test_format_created_date_ok():
    assert m._format_created_date("2025-03-15T00:00:00Z") == "Mar 15"


def test_format_created_date_empty_and_bad():
    assert m._format_created_date("") == ""
    assert m._format_created_date("garbage") == ""
