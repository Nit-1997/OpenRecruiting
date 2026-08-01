"""Test the coverage tracker prompt builder + JSON patch parser."""

import json
import pytest

from intake_core.prompts.tracker import (
    build_tracker_prompt,
    parse_tracker_response,
    TRACKER_SYSTEM_PROMPT,
)


def test_system_prompt_demands_json_only():
    assert "JSON" in TRACKER_SYSTEM_PROMPT
    assert "ONLY" in TRACKER_SYSTEM_PROMPT or "only" in TRACKER_SYSTEM_PROMPT


def test_build_tracker_prompt_includes_state_and_turn():
    state = {"q4_must_haves": {"status": "untouched", "text": None}}
    prompt = build_tracker_prompt(
        current_answers=state,
        last_user_turn="we use Python and Postgres",
        recent_turns=[{"role": "assistant", "content": "what are the must-haves?"}],
    )
    assert "Python" in prompt
    assert "q4_must_haves" in prompt
    assert "must-haves" in prompt


def test_parse_tracker_response_extracts_valid_patch():
    raw = json.dumps({
        "q4_must_haves": {"status": "discussed", "extraction_confidence": "high", "text": "Python, PG"}
    })
    out = parse_tracker_response(raw)
    assert "q4_must_haves" in out
    assert out["q4_must_haves"]["status"] == "discussed"


def test_parse_tracker_response_returns_empty_on_garbage():
    out = parse_tracker_response("not json at all")
    assert out == {}


def test_parse_tracker_response_filters_unknown_qids():
    raw = json.dumps({
        "q4_must_haves": {"status": "discussed"},
        "q99_nonsense": {"status": "validated"},
        "garbage": "value",
    })
    out = parse_tracker_response(raw)
    assert "q4_must_haves" in out
    assert "q99_nonsense" not in out
    assert "garbage" not in out


def test_parse_tracker_response_filters_invalid_status():
    raw = json.dumps({
        "q4_must_haves": {"status": "totally-discussed", "text": "x"},
    })
    out = parse_tracker_response(raw)
    # Either the whole entry is dropped or status is dropped
    assert "q4_must_haves" not in out or out["q4_must_haves"].get("status") != "totally-discussed"


def test_parse_tracker_response_strips_markdown_fence():
    raw = "```json\n{\"q4_must_haves\": {\"status\": \"validated\"}}\n```"
    out = parse_tracker_response(raw)
    assert out.get("q4_must_haves", {}).get("status") == "validated"
