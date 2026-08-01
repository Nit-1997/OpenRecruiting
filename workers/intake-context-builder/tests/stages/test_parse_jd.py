"""Stage 2: parse JD into structured facts."""

from unittest.mock import AsyncMock, MagicMock
import json
import pytest

from src.stages.parse_jd import parse_jd


@pytest.mark.asyncio
async def test_parse_jd_returns_skipped_when_no_jd():
    out = await parse_jd(anthropic_client=AsyncMock(), model="x", jd_text=None)
    assert out["skipped"] is True


@pytest.mark.asyncio
async def test_parse_jd_extracts_structured_facts():
    client = AsyncMock()
    client.messages.create.return_value = MagicMock(
        content=[MagicMock(text=json.dumps({
            "must_have_skills": ["Python", "PostgreSQL"],
            "nice_to_have_skills": ["Kafka"],
            "responsibilities": ["build payment infra"],
            "team_signals": ["senior IC role"],
        }))]
    )
    out = await parse_jd(anthropic_client=client, model="claude-sonnet-4-6", jd_text="...long JD text...")
    assert out["skipped"] is False
    assert out["facts"]["must_have_skills"] == ["Python", "PostgreSQL"]


@pytest.mark.asyncio
async def test_parse_jd_handles_malformed_response():
    client = AsyncMock()
    client.messages.create.return_value = MagicMock(content=[MagicMock(text="not json")])
    out = await parse_jd(anthropic_client=client, model="x", jd_text="JD")
    assert out["skipped"] is False
    assert out["facts"] == {}  # graceful fallback
