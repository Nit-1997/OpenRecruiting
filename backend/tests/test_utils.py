"""Characterization tests for app/utils.py pure helpers."""

from datetime import timezone

import pytest

from app.utils import names_match, parse_iso_datetime, parse_json_response, utc_now


def test_utc_now_is_aware():
    dt = utc_now()
    assert dt.tzinfo == timezone.utc


def test_parse_iso_datetime_with_z():
    dt = parse_iso_datetime("2025-01-15T10:00:00Z")
    assert dt.tzinfo is not None
    assert dt.year == 2025


def test_parse_iso_datetime_with_offset():
    dt = parse_iso_datetime("2025-01-15T10:00:00+05:30")
    assert dt.utcoffset().total_seconds() == 5.5 * 3600


def test_parse_iso_datetime_empty_raises():
    with pytest.raises(ValueError, match="Empty"):
        parse_iso_datetime("")


def test_parse_iso_datetime_naive_raises():
    with pytest.raises(ValueError, match="Naive"):
        parse_iso_datetime("2025-01-15T10:00:00")


@pytest.mark.parametrize("a,b,expected", [
    ("Alice Smith", "alice smith", True),       # case-insensitive exact
    ("Alice", "Alice Smith", True),             # substring
    ("Alice Smith", "Alice Jones", True),       # shared first name
    ("Alice  Smith", "alice smith", True),      # whitespace normalized
    ("Bob", "Carol", False),
    ("", "Alice", False),
    ("Alice", "", False),
])
def test_names_match(a, b, expected):
    assert names_match(a, b) is expected


def test_parse_json_response_plain():
    assert parse_json_response('{"a": 1}') == {"a": 1}


def test_parse_json_response_fenced_json():
    raw = '```json\n{"a": 1}\n```'
    assert parse_json_response(raw) == {"a": 1}


def test_parse_json_response_fenced_plain():
    raw = '```\n{"b": 2}\n```'
    assert parse_json_response(raw) == {"b": 2}


def test_parse_json_response_embedded_in_prose():
    raw = 'Here you go: {"c": 3} hope that helps'
    assert parse_json_response(raw) == {"c": 3}


def test_parse_json_response_unrecoverable_raises():
    with pytest.raises(Exception):
        parse_json_response("not json at all")
