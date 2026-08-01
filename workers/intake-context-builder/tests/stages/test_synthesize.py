"""Stage 4: synthesize 9 prefilled answers."""

from unittest.mock import AsyncMock, MagicMock
import json
import pytest

from src.stages.synthesize import QUESTION_IDS, synthesize_answers


def _all_empty_except(qid: str, value) -> dict:
    """Build a full 9-key payload with empty answers except for one overridden key."""
    base = {q: {"text": None, "extraction_confidence": "none", "sources": []} for q in QUESTION_IDS}
    base[qid] = value
    return base


@pytest.mark.asyncio
async def test_synthesize_returns_all_nine_keys():
    client = AsyncMock()
    nine = {f"q{i}_x": {"text": f"a{i}", "confidence": "medium", "sources": ["jd"]} for i in range(1, 10)}
    # Make keys match real question IDs
    nine = {
        "q1_role_overview":    {"text": "x", "extraction_confidence": "high",   "sources": ["jd"]},
        "q2_rounds":           {"text": "x", "extraction_confidence": "medium", "sources": ["cortex"]},
        "q3_focus_areas":      {"text": "x", "extraction_confidence": "medium", "sources": ["cortex"]},
        "q4_must_haves":       {"text": "x", "extraction_confidence": "high",   "sources": ["jd", "cortex"]},
        "q5_nice_to_haves":    {"text": "x", "extraction_confidence": "low",    "sources": ["jd"]},
        "q6_cultural_fit":     {"text": "x", "extraction_confidence": "low",    "sources": ["cortex"]},
        "q7_team_structure":   {"text": None,"extraction_confidence": "none",   "sources": []},
        "q8_red_flags":        {"text": None,"extraction_confidence": "none",   "sources": []},
        "q9_anything_else":    {"text": None,"extraction_confidence": "none",   "sources": []},
    }
    client.messages.create.return_value = MagicMock(content=[MagicMock(text=json.dumps(nine))])
    out = await synthesize_answers(
        anthropic_client=client, model="x",
        form_data={"role_name": "Senior BE"},
        jd_facts={}, cortex_data={},
    )
    assert set(out.keys()) == set(nine.keys())
    assert out["q1_role_overview"]["extraction_confidence"] == "high"


@pytest.mark.asyncio
async def test_synthesize_returns_all_empty_on_malformed_response():
    client = AsyncMock()
    client.messages.create.return_value = MagicMock(content=[MagicMock(text="not json")])
    out = await synthesize_answers(
        anthropic_client=client, model="x",
        form_data={"role_name": "x"}, jd_facts={}, cortex_data={},
    )
    assert len(out) == 9
    assert all(a["extraction_confidence"] == "none" for a in out.values())


@pytest.mark.asyncio
async def test_synthesize_normalizes_legacy_confidence_key():
    """LLM emits old 'confidence' key — defensive rename should produce 'extraction_confidence'."""
    client = AsyncMock()
    legacy = {
        "q1_role_overview":    {"text": "x", "confidence": "high",   "sources": ["jd"]},
        "q2_rounds":           {"text": "x", "confidence": "medium", "sources": []},
        "q3_focus_areas":      {"text": "x", "confidence": "medium", "sources": []},
        "q4_must_haves":       {"text": "x", "confidence": "high",   "sources": []},
        "q5_nice_to_haves":    {"text": "x", "confidence": "low",    "sources": []},
        "q6_cultural_fit":     {"text": "x", "confidence": "low",    "sources": []},
        "q7_team_structure":   {"text": None,"confidence": "none",   "sources": []},
        "q8_red_flags":        {"text": None,"confidence": "none",   "sources": []},
        "q9_anything_else":    {"text": None,"confidence": "none",   "sources": []},
    }
    client.messages.create.return_value = MagicMock(content=[MagicMock(text=json.dumps(legacy))])
    out = await synthesize_answers(
        anthropic_client=client, model="x",
        form_data={"role_name": "x"}, jd_facts={}, cortex_data={},
    )
    assert out["q1_role_overview"]["extraction_confidence"] == "high"
    assert "confidence" not in out["q1_role_overview"]


@pytest.mark.asyncio
async def test_synthesize_normalizes_string_sources():
    """Sonnet returns sources as a bare string — should be coerced to empty list (not a list)."""
    client = AsyncMock()
    payload = _all_empty_except("q1_role_overview", {"text": "x", "extraction_confidence": "high", "sources": "jd"})
    client.messages.create.return_value = MagicMock(content=[MagicMock(text=json.dumps(payload))])
    out = await synthesize_answers(
        anthropic_client=client, model="x",
        form_data={"role_name": "x"}, jd_facts={}, cortex_data={},
    )
    assert isinstance(out["q1_role_overview"]["sources"], list)
    assert out["q1_role_overview"]["sources"] == []


@pytest.mark.asyncio
async def test_synthesize_rejects_invalid_confidence():
    """Sonnet returns 'very high' as confidence — should fall back to 'none'."""
    client = AsyncMock()
    payload = _all_empty_except("q1_role_overview", {"text": "x", "extraction_confidence": "very high", "sources": []})
    client.messages.create.return_value = MagicMock(content=[MagicMock(text=json.dumps(payload))])
    out = await synthesize_answers(
        anthropic_client=client, model="x",
        form_data={"role_name": "x"}, jd_facts={}, cortex_data={},
    )
    assert out["q1_role_overview"]["extraction_confidence"] == "none"


@pytest.mark.asyncio
async def test_synthesize_handles_non_dict_answer():
    """Sonnet returns a plain string for an answer — should be replaced with empty shape."""
    client = AsyncMock()
    payload = _all_empty_except("q1_role_overview", "just a string")
    client.messages.create.return_value = MagicMock(content=[MagicMock(text=json.dumps(payload))])
    out = await synthesize_answers(
        anthropic_client=client, model="x",
        form_data={"role_name": "x"}, jd_facts={}, cortex_data={},
    )
    assert out["q1_role_overview"] == {"text": None, "extraction_confidence": "none", "sources": []}
