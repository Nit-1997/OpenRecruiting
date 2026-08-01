"""Characterization tests for the pure partial_feedback decision helpers."""

import json

from app.services.recall_webhook import partial_feedback as pf
from app.services.recall_webhook.partial_feedback import is_meaningful_partial_feedback


def _seg(pid, name, is_host, text, rel=20.0):
    return {
        "participant": {"id": pid, "name": name, "is_host": is_host},
        "words": [{"text": w, "start_timestamp": {"relative": rel}} for w in text.split()],
    }


# ----------------------- feedback_start_offset_seconds -----------------------

def test_offset_none_when_missing_inputs():
    assert pf.feedback_start_offset_seconds(None, "2025-01-01T00:00:00Z") is None
    assert pf.feedback_start_offset_seconds("2025-01-01T00:00:00Z", None) is None


def test_offset_computes_delta():
    out = pf.feedback_start_offset_seconds(
        "2025-01-01T00:10:00Z", "2025-01-01T00:00:00Z"
    )
    assert out == 600.0


def test_offset_bad_format_returns_none():
    assert pf.feedback_start_offset_seconds("not-a-date", "also-bad") is None


# ----------------------- is_meaningful_partial_feedback -----------------------

def test_feedback_transcript_ready():
    text = "interviewer: " + ("Strong candidate, communicated very well. " * 5)
    ready, source, turns, chars = pf.is_meaningful_partial_feedback(text, None, None)
    assert ready is True
    assert source == "feedback_transcript"
    assert turns == 1
    assert chars >= 150


def test_feedback_transcript_too_short_not_ready():
    text = "interviewer: ok"
    ready, source, turns, chars = pf.is_meaningful_partial_feedback(text, None, None)
    assert ready is False
    assert source == "feedback_transcript"
    assert turns == 1
    assert chars < 150


def test_feedback_transcript_no_interviewer_lines_falls_through():
    text = "candidate: I think I did well"
    ready, source, turns, chars = pf.is_meaningful_partial_feedback(text, None, None)
    # No interviewer lines -> falls through to segments path (none) -> not ready
    assert ready is False
    assert source == "segments_secondary"


def test_segments_fallback_without_offset_not_ready():
    # Long interviewer content but NO offset -> BE-A4a keeps it not-ready.
    segs = [{"participant": {"name": "Bob"}, "text": "x" * 300}]
    ready, source, turns, chars = pf.is_meaningful_partial_feedback(None, segs, None)
    assert ready is False
    assert source == "segments_fallback"
    assert chars >= 150  # metrics still surfaced for logging


def test_segments_ready_with_offset():
    segs = [{
        "participant": {"name": "Bob"},
        "text": "x" * 300,
        "start_timestamp": {"relative": 700.0},
    }]
    ready, source, turns, chars = pf.is_meaningful_partial_feedback(None, segs, 600.0)
    assert ready is True
    assert turns == 1
    assert chars >= 150


def test_segments_excludes_candidate_and_bot():
    segs = [
        {"participant": {"name": "Alice"}, "text": "candidate words " * 30, "start": 700},
        {"participant": {"name": "Scout"}, "text": "bot words " * 30, "start": 700},
        {"participant": {"name": "Bob"}, "text": "y" * 200, "start": 700},
    ]
    ready, source, turns, chars = pf.is_meaningful_partial_feedback(
        None, segs, 600.0, candidate_names={"alice"}
    )
    assert turns == 1  # only Bob counts
    assert ready is True


def test_segments_as_json_string():
    segs = [{"participant": {"name": "Bob"}, "text": "z" * 200, "start": 700}]
    ready, source, turns, chars = pf.is_meaningful_partial_feedback(
        None, json.dumps(segs), 600.0
    )
    assert ready is True


def test_segments_invalid_json_string_returns_zero():
    ready, source, turns, chars = pf.is_meaningful_partial_feedback(None, "{bad json", 600.0)
    assert (turns, chars) == (0, 0)
    assert ready is False


def test_segments_non_list_returns_zero():
    ready, source, turns, chars = pf.is_meaningful_partial_feedback(None, {"a": 1}, 600.0)
    assert (turns, chars) == (0, 0)


def test_word_level_offset_filtering():
    segs = [{
        "participant": {"name": "Bob"},
        "words": [
            {"text": "early", "start_timestamp": {"relative": 100.0}},  # before offset, dropped
            {"text": "w" * 200, "start_timestamp": {"relative": 700.0}},  # after, kept
        ],
    }]
    ready, source, turns, chars = pf.is_meaningful_partial_feedback(None, segs, 600.0)
    assert "early" not in str(chars)  # sanity
    assert chars >= 150
    assert ready is True


def test_segment_speaker_shapes():
    assert pf._segment_speaker({"participant": {"display_name": "Bob"}}) == "bob"
    assert pf._segment_speaker({"speaker": "Carol"}) == "carol"
    assert pf._segment_speaker({"speaker": {"name": "Dan"}}) == "dan"
    assert pf._segment_speaker({}) == ""


def test_relative_word_ts_shapes():
    assert pf._relative_word_ts({"start_timestamp": {"relative": 5.0}}) == 5.0
    assert pf._relative_word_ts({"start_timestamp": 9}) == 9.0
    assert pf._relative_word_ts({"start_timestamp": "x"}) is None


# ------------- host-signal / participant-id interviewer detection -------------

def test_host_feedback_counts_even_when_name_equals_candidate():
    # interviewer (host) shares the candidate's name "Nitin Bhat", candidate no-show
    long_text = (
        "strong no the candidate did not join no scalability reasoning no trade off "
        "analysis no design communication no system understanding it is a strong no "
        "from my end overall here"
    )
    segments = [_seg(100, "Nitin Bhat", True, long_text)]
    ready, source, turns, chars = is_meaningful_partial_feedback(
        feedback_transcript=None,
        fallback_segments=segments,
        feedback_start_seconds=8.0,
        candidate_participant_id=None,          # detection never completed
        candidate_names={"nitin bhat"},
    )
    assert turns == 1
    assert chars >= 150
    assert ready is True


def test_candidate_segment_excluded_by_participant_id():
    segments = [_seg(200, "Alice", False, "i think my approach would be to use a hash map and then iterate")]
    ready, source, turns, chars = is_meaningful_partial_feedback(
        feedback_transcript=None,
        fallback_segments=segments,
        feedback_start_seconds=8.0,
        candidate_participant_id=200,           # this is the candidate
        candidate_names={"alice"},
    )
    assert turns == 0
    assert ready is False
