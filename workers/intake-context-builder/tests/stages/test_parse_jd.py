"""Stage 2: parse JD into structured facts."""

from unittest.mock import AsyncMock, MagicMock
import json
import pytest

from src.stages.parse_jd import parse_jd


@pytest.mark.asyncio
async def test_parse_jd_returns_skipped_when_no_jd():
    out = await parse_jd(llm=AsyncMock(), model="x", jd_text=None)
    assert out["skipped"] is True


@pytest.mark.asyncio
async def test_parse_jd_extracts_structured_facts():
    client = AsyncMock()
    client.complete.return_value = MagicMock(
        text=(json.dumps({
            "must_have_skills": ["Python", "PostgreSQL"],
            "nice_to_have_skills": ["Kafka"],
            "responsibilities": ["build payment infra"],
            "team_signals": ["senior IC role"],
        }))
    )
    out = await parse_jd(llm=client, model="context-parse-jd", jd_text="...long JD text...")
    assert out["skipped"] is False
    assert out["facts"]["must_have_skills"] == ["Python", "PostgreSQL"]


@pytest.mark.asyncio
async def test_parse_jd_handles_malformed_response():
    client = AsyncMock()
    client.complete.return_value = MagicMock(text="not json")
    out = await parse_jd(llm=client, model="x", jd_text="JD")
    assert out["skipped"] is False
    assert out["facts"] == {}  # graceful fallback


@pytest.mark.asyncio
async def test_parse_jd_distinguishes_an_empty_reply_from_bad_json():
    """An empty completion used to reach json.loads("") and be logged as
    "unparseable" with an empty `raw` — reading as a model that answered badly
    rather than one that did not answer at all. Different causes, different fixes."""
    client = AsyncMock()
    client.complete.return_value = MagicMock(text="")

    out = await parse_jd(llm=client, model="context-parse-jd", jd_text="a real JD")

    assert out == {"skipped": False, "facts": {}}


@pytest.mark.asyncio
async def test_parse_jd_handles_a_markdown_fenced_object():
    """Found by running it live, not by unit tests: the model wraps its object in
    ```json, and without stripping that, json.loads fails, facts come back empty,
    and the JD contributes NOTHING to the intake context — logged as
    "unparseable" while the pipeline carries on."""
    client = AsyncMock()
    client.complete.return_value = MagicMock(
        text='```json\n{"must_have_skills": ["Python"], "seniority": "senior"}\n```'
    )

    out = await parse_jd(llm=client, model="context-parse-jd", jd_text="a real JD")

    assert out["skipped"] is False
    assert out["facts"]["must_have_skills"] == ["Python"]
