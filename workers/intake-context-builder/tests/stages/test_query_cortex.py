"""Stage 3: parallel Cortex queries based on mode."""

from unittest.mock import AsyncMock, MagicMock
import json
import pytest

from src.stages.query_cortex import query_cortex
from src.stages.check_context import Mode


def _mcp_resp(rows: list[dict]) -> MagicMock:
    """Return a sync-response mock matching real httpx.Response behaviour.
    content[0].text is the Cortex envelope {status, data, ...}, not a bare list."""
    text = json.dumps(
        {"status": "ok", "data": rows, "row_count": len(rows), "truncated": False, "error": None}
    )
    payload = {"result": {"content": [{"type": "text", "text": text}]}}
    resp = MagicMock()
    resp.raise_for_status = MagicMock(return_value=None)
    resp.json = MagicMock(return_value=payload)
    return resp


@pytest.mark.asyncio
async def test_cold_mode_returns_empty():
    mcp = AsyncMock()
    out = await query_cortex(mcp_client=mcp, mode=Mode.COLD, role_title="x")
    assert out == {"similar_reqs": [], "skills_required": [], "skills_nice": [], "traits": [], "rounds": []}
    mcp.post.assert_not_called()


@pytest.mark.asyncio
async def test_full_context_queries_all():
    mcp = AsyncMock()
    mcp.post.side_effect = [
        _mcp_resp([{"role_title": "Senior BE", "experience_min_years": 5}]),
        _mcp_resp([{"name": "Python", "count": 3}, {"name": "PostgreSQL", "count": 2}]),
        _mcp_resp([{"name": "Kafka", "count": 1}]),
        _mcp_resp([{"name": "directness", "polarity": "positive", "count": 2}]),
        _mcp_resp([{"name": "Coding", "count": 3}]),
    ]
    out = await query_cortex(mcp_client=mcp, mode=Mode.FULL_CONTEXT, role_title="Senior BE")
    assert len(out["similar_reqs"]) == 1
    assert out["skills_required"][0]["name"] == "Python"
    assert out["traits"][0]["polarity"] == "positive"
    assert out["rounds"][0]["name"] == "Coding"


@pytest.mark.asyncio
async def test_org_only_skips_role_specific():
    mcp = AsyncMock()
    mcp.post.side_effect = [
        _mcp_resp([{"name": "ownership", "polarity": "positive"}]),  # only traits queried
    ]
    out = await query_cortex(mcp_client=mcp, mode=Mode.ORG_ONLY, role_title="Senior BE")
    assert out["similar_reqs"] == []
    assert out["skills_required"] == []
    assert out["traits"][0]["name"] == "ownership"
