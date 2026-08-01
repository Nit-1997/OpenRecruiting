"""Stage 1: cheap Cortex context check."""

import json
from unittest.mock import AsyncMock, MagicMock
import pytest

from src.stages.check_context import check_context, Mode


def _make_mcp_response(json_payload: dict) -> MagicMock:
    """Return a sync-response mock matching real httpx.Response behaviour."""
    resp = MagicMock()
    resp.raise_for_status = MagicMock(return_value=None)
    resp.json = MagicMock(return_value=json_payload)
    return resp


def _envelope(rows: list[dict]) -> dict:
    """Wrap rows in the Cortex MCP response envelope the server actually sends:
    content[0].text is a JSON string of {status, data, row_count, error}."""
    text = json.dumps(
        {"status": "ok", "data": rows, "row_count": len(rows), "truncated": False, "error": None}
    )
    return {"result": {"content": [{"type": "text", "text": text}]}}


@pytest.mark.asyncio
async def test_mode_cold_when_org_empty():
    mcp = AsyncMock()
    mcp.post.return_value = _make_mcp_response(_envelope([{"has_any": False}]))
    out = await check_context(mcp_client=mcp, role_title="Senior BE")
    assert out["mode"] == Mode.COLD
    assert out["has_any"] is False
    assert out["similar_count"] == 0


@pytest.mark.asyncio
async def test_mode_org_only_when_no_similar():
    mcp = AsyncMock()
    # Sequence: has_any=true, similar_count=0
    mcp.post.side_effect = [
        _make_mcp_response(_envelope([{"has_any": True}])),
        _make_mcp_response(_envelope([{"similar_count": 0}])),
    ]
    out = await check_context(mcp_client=mcp, role_title="Senior BE")
    assert out["mode"] == Mode.ORG_ONLY


@pytest.mark.asyncio
async def test_mode_full_context_when_similar_present():
    mcp = AsyncMock()
    mcp.post.side_effect = [
        _make_mcp_response(_envelope([{"has_any": True}])),
        _make_mcp_response(_envelope([{"similar_count": 3}])),
    ]
    out = await check_context(mcp_client=mcp, role_title="Senior BE")
    assert out["mode"] == Mode.FULL_CONTEXT
    assert out["similar_count"] == 3


@pytest.mark.asyncio
async def test_rejected_query_treated_as_cold():
    """A status!=ok envelope must not be read as rows — fall back to COLD."""
    mcp = AsyncMock()
    rejected = {
        "result": {
            "content": [
                {"type": "text", "text": json.dumps(
                    {"status": "rejected", "data": None, "error": "bad query"}
                )}
            ]
        }
    }
    mcp.post.return_value = _make_mcp_response(rejected)
    out = await check_context(mcp_client=mcp, role_title="Senior BE")
    assert out["mode"] == Mode.COLD
    assert out["has_any"] is False
