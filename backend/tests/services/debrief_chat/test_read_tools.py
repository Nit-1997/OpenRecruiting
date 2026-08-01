"""Unit tests for DebriefReadTools — the three templated in-loop read tools.

The Supabase boundary is a fluent MagicMock; the Cortex seam is an injected async
callable that adapts CortexGapReader into (cypher, params) -> rows. The hard
guardrail: any candidate_id the model passes is validated against the packet body's
candidates[].candidate_id before any query runs — an out-of-packet id returns a
structured error, never a query.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.debrief_chat.prompt import build_system_prompt
from app.services.debrief_chat.read_tools import DebriefReadTools

ORG_ID = "00000000-0000-0000-0000-000000000010"
CAND_A = "00000000-0000-0000-0000-0000000000a1"
CAND_B = "00000000-0000-0000-0000-0000000000a2"
FOREIGN = "00000000-0000-0000-0000-0000000000ff"
CR_1 = "00000000-0000-0000-0000-0000000000c1"
CR_2 = "00000000-0000-0000-0000-0000000000c2"


def _packet():
    return {
        "role_title": "PM",
        "candidates": [
            {"candidate_id": CAND_A, "name": "Ada"},
            {"candidate_id": CAND_B, "name": "Bob"},
        ],
    }


def _supa():
    """A fluent builder whose execute_async return value is set per-test.

    Each .table("x") call returns the same builder; tests set
    builder.execute_async.side_effect to script multi-query tools.
    """
    builder = MagicMock()
    for m in ("table", "select", "eq", "in_", "single", "limit", "order"):
        getattr(builder, m).return_value = builder
    builder.execute_async = AsyncMock()
    supa = MagicMock()
    supa.table.return_value = builder
    return supa, builder


def _tools(supa, cortex_query):
    return DebriefReadTools(
        supabase=supa, cortex_query=cortex_query, packet=_packet(), org_id=ORG_ID
    )


# ---------------------------------------------------------------------------
# Membership guardrail
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_candidate_detail_rejects_candidate_not_in_packet():
    supa, builder = _supa()
    tools = _tools(supa, AsyncMock())
    out = await tools.dispatch("get_candidate_detail", {"candidate_id": FOREIGN})
    assert "error" in out
    builder.execute_async.assert_not_awaited()  # no query ran


@pytest.mark.asyncio
async def test_transcript_evidence_rejects_candidate_not_in_packet():
    supa, builder = _supa()
    tools = _tools(supa, AsyncMock())
    out = await tools.dispatch(
        "get_transcript_evidence", {"candidate_id": FOREIGN, "topic": "design"}
    )
    assert "error" in out
    builder.execute_async.assert_not_awaited()


# ---------------------------------------------------------------------------
# get_candidate_detail
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_candidate_detail_returns_rounds_for_valid_candidate():
    supa, builder = _supa()
    rounds = [
        {
            "id": CR_1,
            "status": "completed",
            "rating": "strong_yes",
            "summary": "Excellent system design.",
            "outcome": "advance",
            "rounds": {"name": "Technical Screen"},
        }
    ]
    builder.execute_async.return_value = MagicMock(data=rounds)
    tools = _tools(supa, AsyncMock())
    out = await tools.dispatch("get_candidate_detail", {"candidate_id": CAND_A})
    assert out["candidate_id"] == CAND_A
    assert len(out["rounds"]) == 1
    r = out["rounds"][0]
    assert r["rating"] == "strong_yes"
    assert r["round_name"] == "Technical Screen"
    builder.eq.assert_any_call("candidate_id", CAND_A)


@pytest.mark.asyncio
async def test_candidate_detail_handles_no_rounds():
    supa, builder = _supa()
    builder.execute_async.return_value = MagicMock(data=[])
    tools = _tools(supa, AsyncMock())
    out = await tools.dispatch("get_candidate_detail", {"candidate_id": CAND_A})
    assert out["rounds"] == []


# ---------------------------------------------------------------------------
# get_transcript_evidence
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_transcript_evidence_returns_matching_excerpts():
    supa, builder = _supa()
    # First query: candidate's rounds -> ids; second: transcripts.segments.
    rounds = [{"id": CR_1}, {"id": CR_2}]
    transcripts = [
        {
            "candidate_round_id": CR_1,
            "segments": [
                {"speaker": "Interviewer", "text": "Walk me through the system design."},
                {"speaker": "Candidate", "text": "I would shard the database."},
                {"speaker": "Candidate", "text": "Unrelated small talk."},
            ],
        }
    ]
    builder.execute_async.side_effect = [
        MagicMock(data=rounds),
        MagicMock(data=transcripts),
    ]
    tools = _tools(supa, AsyncMock())
    out = await tools.dispatch(
        "get_transcript_evidence", {"candidate_id": CAND_A, "topic": "design"}
    )
    assert out["candidate_id"] == CAND_A
    texts = [e["text"] for e in out["excerpts"]]
    assert any("system design" in t.lower() for t in texts)
    assert all("small talk" not in t.lower() for t in texts)


@pytest.mark.asyncio
async def test_transcript_evidence_caps_excerpt_count():
    supa, builder = _supa()
    rounds = [{"id": CR_1}]
    many = [
        {"speaker": "Candidate", "text": f"design point number {i}"}
        for i in range(50)
    ]
    transcripts = [{"candidate_round_id": CR_1, "segments": many}]
    builder.execute_async.side_effect = [
        MagicMock(data=rounds),
        MagicMock(data=transcripts),
    ]
    tools = _tools(supa, AsyncMock())
    out = await tools.dispatch(
        "get_transcript_evidence", {"candidate_id": CAND_A, "topic": "design"}
    )
    assert len(out["excerpts"]) <= 8


@pytest.mark.asyncio
async def test_transcript_evidence_empty_when_no_rounds():
    supa, builder = _supa()
    builder.execute_async.return_value = MagicMock(data=[])
    tools = _tools(supa, AsyncMock())
    out = await tools.dispatch(
        "get_transcript_evidence", {"candidate_id": CAND_A, "topic": "design"}
    )
    assert out["excerpts"] == []


# ---------------------------------------------------------------------------
# get_graph_standing — best-effort
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_graph_standing_returns_rows_from_seam():
    rows = [{"competency": "System Design", "candidate": "Ada", "standing": 2}]
    cortex_query = AsyncMock(return_value=rows)
    supa, _ = _supa()
    tools = _tools(supa, cortex_query)
    out = await tools.dispatch("get_graph_standing", {"competency": "System Design"})
    assert out["standings"] == rows
    # The Cypher is templated by read_tools; org is bound as a param, never the LLM.
    cypher, params = cortex_query.call_args.args
    assert "$org_id" in cypher
    assert params["org_id"] == ORG_ID


@pytest.mark.asyncio
async def test_graph_standing_validates_candidate_filter():
    """A candidate_id filter that isn't in the packet is rejected before any query."""
    cortex_query = AsyncMock()
    supa, _ = _supa()
    tools = _tools(supa, cortex_query)
    out = await tools.dispatch("get_graph_standing", {"candidate_id": FOREIGN})
    assert "error" in out
    cortex_query.assert_not_awaited()


@pytest.mark.asyncio
async def test_graph_standing_returns_empty_on_seam_exception():
    cortex_query = AsyncMock(side_effect=RuntimeError("cortex down"))
    supa, _ = _supa()
    tools = _tools(supa, cortex_query)
    out = await tools.dispatch("get_graph_standing", {})
    assert out == {"standings": []}


# ---------------------------------------------------------------------------
# Requisition scoping — a candidate in two pipelines only surfaces THIS role's rounds
# ---------------------------------------------------------------------------
REQ_THIS = "00000000-0000-0000-0000-0000000000d1"
REQ_OTHER = "00000000-0000-0000-0000-0000000000d2"


def _scoped_tools(supa, cortex_query):
    return DebriefReadTools(
        supabase=supa,
        cortex_query=cortex_query,
        packet=_packet(),
        org_id=ORG_ID,
        requisition_id=REQ_THIS,
    )


@pytest.mark.asyncio
async def test_candidate_detail_filters_other_requisitions_rounds():
    supa, builder = _supa()
    rows = [
        {
            "id": CR_1,
            "status": "completed",
            "rating": "yes3",
            "summary": "this role",
            "outcome": None,
            "rounds": {"name": "Screen", "requisition_id": REQ_THIS},
        },
        {
            "id": CR_2,
            "status": "completed",
            "rating": "strong_yes",
            "summary": "OTHER role",
            "outcome": None,
            "rounds": {"name": "Panel", "requisition_id": REQ_OTHER},
        },
    ]
    builder.execute_async.return_value = MagicMock(data=rows)
    tools = _scoped_tools(supa, AsyncMock())
    out = await tools.dispatch("get_candidate_detail", {"candidate_id": CAND_A})
    assert [r["summary"] for r in out["rounds"]] == ["this role"]


@pytest.mark.asyncio
async def test_transcript_evidence_scoped_to_this_requisitions_rounds():
    supa, builder = _supa()
    rounds = [
        {"id": CR_1, "rounds": {"name": "Screen", "requisition_id": REQ_THIS}},
        {"id": CR_2, "rounds": {"name": "Panel", "requisition_id": REQ_OTHER}},
    ]
    builder.execute_async.side_effect = [
        MagicMock(data=rounds),
        MagicMock(data=[]),
    ]
    tools = _scoped_tools(supa, AsyncMock())
    await tools.dispatch(
        "get_transcript_evidence", {"candidate_id": CAND_A, "topic": "design"}
    )
    builder.in_.assert_called_once_with("candidate_round_id", [CR_1])


@pytest.mark.asyncio
async def test_unscoped_tools_keep_every_round():
    """Legacy packets without a requisition_id keep the old unscoped behavior."""
    supa, builder = _supa()
    rows = [
        {"id": CR_1, "status": "completed", "rating": "yes3", "summary": "a",
         "outcome": None, "rounds": {"name": "Screen", "requisition_id": REQ_OTHER}},
    ]
    builder.execute_async.return_value = MagicMock(data=rows)
    tools = _tools(supa, AsyncMock())
    out = await tools.dispatch("get_candidate_detail", {"candidate_id": CAND_A})
    assert len(out["rounds"]) == 1


# ---------------------------------------------------------------------------
# Transcript keyword matching + round filter + no-match hint
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_transcript_evidence_matches_any_keyword_of_topic():
    supa, builder = _supa()
    rounds = [{"id": CR_1, "rounds": {"name": "Screen", "requisition_id": REQ_THIS}}]
    transcripts = [
        {
            "candidate_round_id": CR_1,
            "segments": [
                {"speaker": "Candidate", "text": "I would shard by design here."},
                {"speaker": "Candidate", "text": "Unrelated chatter."},
            ],
        }
    ]
    builder.execute_async.side_effect = [
        MagicMock(data=rounds),
        MagicMock(data=transcripts),
    ]
    tools = _scoped_tools(supa, AsyncMock())
    # Whole phrase never appears verbatim — the 'design' keyword still matches.
    out = await tools.dispatch(
        "get_transcript_evidence",
        {"candidate_id": CAND_A, "topic": "system design tradeoffs"},
    )
    assert len(out["excerpts"]) == 1
    assert out["excerpts"][0]["round_name"] == "Screen"


@pytest.mark.asyncio
async def test_transcript_evidence_round_ref_filters_rounds():
    supa, builder = _supa()
    rounds = [
        {"id": CR_1, "rounds": {"name": "Screen", "requisition_id": REQ_THIS}},
        {"id": CR_2, "rounds": {"name": "Panel", "requisition_id": REQ_THIS}},
    ]
    builder.execute_async.side_effect = [
        MagicMock(data=rounds),
        MagicMock(data=[]),
    ]
    tools = _scoped_tools(supa, AsyncMock())
    await tools.dispatch(
        "get_transcript_evidence",
        {"candidate_id": CAND_A, "topic": "design", "round_ref": "panel"},
    )
    builder.in_.assert_called_once_with("candidate_round_id", [CR_2])


@pytest.mark.asyncio
async def test_transcript_evidence_no_match_returns_hint():
    supa, builder = _supa()
    rounds = [{"id": CR_1, "rounds": {"name": "Screen", "requisition_id": REQ_THIS}}]
    transcripts = [
        {
            "candidate_round_id": CR_1,
            "segments": [{"speaker": "Candidate", "text": "Nothing relevant."}],
        }
    ]
    builder.execute_async.side_effect = [
        MagicMock(data=rounds),
        MagicMock(data=transcripts),
    ]
    tools = _scoped_tools(supa, AsyncMock())
    out = await tools.dispatch(
        "get_transcript_evidence", {"candidate_id": CAND_A, "topic": "kubernetes"}
    )
    assert out["excerpts"] == []
    assert "hint" in out


# ---------------------------------------------------------------------------
# dispatch routing
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_dispatch_unknown_tool_returns_error():
    supa, _ = _supa()
    tools = _tools(supa, AsyncMock())
    out = await tools.dispatch("nonexistent_tool", {})
    assert "error" in out


# ---------------------------------------------------------------------------
# Single-object contract: read-tools and the prompt agree on one body shape
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_single_body_object_satisfies_read_tools_and_prompt():
    """One realistic packet-body dict drives BOTH the read-tools membership guard
    AND build_system_prompt — proving the two modules read the same shape."""
    body = _packet()
    supa, builder = _supa()
    builder.execute_async.return_value = MagicMock(data=[])
    tools = DebriefReadTools(
        supabase=supa, cortex_query=AsyncMock(), packet=body, org_id=ORG_ID
    )

    in_packet = await tools.dispatch("get_candidate_detail", {"candidate_id": CAND_A})
    assert "error" not in in_packet
    out_of_packet = await tools.dispatch(
        "get_candidate_detail", {"candidate_id": FOREIGN}
    )
    assert "error" in out_of_packet

    prompt = build_system_prompt(body)
    assert "Ada" in prompt
    assert "Bob" in prompt
