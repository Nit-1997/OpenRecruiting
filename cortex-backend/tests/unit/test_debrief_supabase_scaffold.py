"""Unit tests for `SupabaseScaffold` (spec §5/§6.6).

The `SupabaseFetcher` is fully MOCKED (AsyncMock) — these tests never touch a real
Supabase. They assert that the scaffold:
  * assembles requisition identity + must/nice-to-have dimension seeds from the plan,
  * builds one `CandidateRoundFact` per completed round (rating/summary/interviewer,
    has_feedback / has_transcript),
  * maps assessment scores (category_name -> dimension) and evidence_status
    (feedback heading -> dimension) per candidate,
  * counts scorecards + transcripts,
  * tolerates a sparse candidate (no rounds / no signals) WITHOUT raising and with
    EMPTY maps for that candidate (D6).
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.model.packets import (
    PlanPacket,
    RequisitionData,
    RoundWithCompetenciesData,
)
from src.model.debrief import ScaffoldData
from src.service.debrief.supabase_scaffold import SupabaseScaffold

ORG_ID = "org-1"
REQ_ID = "req-1"
CAND_A = "cand-a"
CAND_B = "cand-b"
CAND_SPARSE = "cand-sparse"


def _plan_packet() -> PlanPacket:
    return PlanPacket(
        requisition=RequisitionData(
            id=REQ_ID,
            role_title="Staff Engineer",
            organization_id=ORG_ID,
            must_have_skills=["Distributed Systems", "Leadership"],
            nice_to_have_skills=["Go"],
        ),
        rounds=[
            RoundWithCompetenciesData(id="r1", name="Technical", category="technical", order=0),
            RoundWithCompetenciesData(id="r2", name="System Design", category="technical", order=1),
        ],
    )


def _candidate_round_rows() -> list[dict]:
    """Rows as returned by the new fetcher method: completed candidate_rounds joined
    to rounds for name/category. CAND_SPARSE intentionally absent (no rounds)."""
    return [
        {
            "id": "cr-a1",
            "candidate_id": CAND_A,
            "round_id": "r1",
            "rating": "strong_yes",
            "summary": "Excellent depth on distributed systems.",
            "interviewer_email": "alice@x.com",
            "interviewer_name": "Alice Eng",
            "rounds": {"name": "Technical", "category": "technical"},
        },
        {
            "id": "cr-a2",
            "candidate_id": CAND_A,
            "round_id": "r2",
            "rating": "yes",
            "summary": "Solid system design.",
            "interviewer_email": "bob@x.com",
            "interviewer_name": "Bob Arch",
            "rounds": {"name": "System Design", "category": "technical"},
        },
        {
            "id": "cr-b1",
            "candidate_id": CAND_B,
            "round_id": "r1",
            "rating": "maybe",
            "summary": "Mixed signal on leadership.",
            "interviewer_email": "alice@x.com",
            "interviewer_name": "Alice Eng",
            "rounds": {"name": "Technical", "category": "technical"},
        },
    ]


def _assessment_rows() -> list[dict]:
    return [
        {"candidate_round_id": "cr-a1", "category_name": "Distributed Systems", "score": 5},
        {"candidate_round_id": "cr-a2", "category_name": "Leadership", "score": 4},
        {"candidate_round_id": "cr-b1", "category_name": "Distributed Systems", "score": 3},
    ]


def _evidence_rows() -> list[dict]:
    """candidate_feedback joined to feedback_questions.heading; heading == dimension."""
    return [
        {"candidate_round_id": "cr-a1", "evidence_status": "verified",
         "feedback_questions": {"heading": "Distributed Systems"}},
        {"candidate_round_id": "cr-a2", "evidence_status": "partial",
         "feedback_questions": {"heading": "Leadership"}},
        {"candidate_round_id": "cr-b1", "evidence_status": "contradicted",
         "feedback_questions": {"heading": "Distributed Systems"}},
    ]


def _transcript_round_ids() -> list[str]:
    # cr-a1 + cr-b1 have transcripts; cr-a2 does not.
    return ["cr-a1", "cr-b1"]


def _candidate_names() -> dict[str, str]:
    return {CAND_A: "Ada Lovelace", CAND_B: "Brian May"}


def _make_fetcher(
    *,
    plan: PlanPacket | None = None,
    cr_rows: list[dict] | None = None,
    assessment_rows: list[dict] | None = None,
    evidence_rows: list[dict] | None = None,
    transcript_ids: list[str] | None = None,
    names: dict[str, str] | None = None,
) -> MagicMock:
    fetcher = MagicMock()
    fetcher.fetch_plan_packet = AsyncMock(return_value=plan if plan is not None else _plan_packet())
    fetcher.fetch_candidate_names = AsyncMock(
        return_value=names if names is not None else _candidate_names()
    )
    fetcher.fetch_candidate_rounds_for_requisition = AsyncMock(
        return_value=cr_rows if cr_rows is not None else _candidate_round_rows()
    )
    fetcher.fetch_assessment_scores = AsyncMock(
        return_value=assessment_rows if assessment_rows is not None else _assessment_rows()
    )
    fetcher.fetch_evidence_status_by_dimension = AsyncMock(
        return_value=evidence_rows if evidence_rows is not None else _evidence_rows()
    )
    fetcher.fetch_transcript_round_ids = AsyncMock(
        return_value=transcript_ids if transcript_ids is not None else _transcript_round_ids()
    )
    return fetcher


@pytest.mark.asyncio
async def test_build_returns_scaffold_data():
    scaffold = SupabaseScaffold(_make_fetcher())
    result = await scaffold.build(ORG_ID, REQ_ID, [CAND_A, CAND_B, CAND_SPARSE])
    assert isinstance(result, ScaffoldData)


@pytest.mark.asyncio
async def test_requisition_identity_and_skill_seeds():
    scaffold = SupabaseScaffold(_make_fetcher())
    result = await scaffold.build(ORG_ID, REQ_ID, [CAND_A, CAND_B])
    assert result.org_id == ORG_ID
    assert result.requisition_id == REQ_ID
    assert result.role_title == "Staff Engineer"
    assert result.must_have_skills == ["Distributed Systems", "Leadership"]
    assert result.nice_to_have_skills == ["Go"]


@pytest.mark.asyncio
async def test_candidate_names_populated():
    scaffold = SupabaseScaffold(_make_fetcher())
    result = await scaffold.build(ORG_ID, REQ_ID, [CAND_A, CAND_B])
    assert result.candidate_names[CAND_A] == "Ada Lovelace"
    assert result.candidate_names[CAND_B] == "Brian May"


@pytest.mark.asyncio
async def test_round_facts_one_per_completed_round():
    scaffold = SupabaseScaffold(_make_fetcher())
    result = await scaffold.build(ORG_ID, REQ_ID, [CAND_A, CAND_B])
    assert len(result.round_facts) == 3
    fact_a1 = next(f for f in result.round_facts if f.candidate_round_id == "cr-a1")
    assert fact_a1.candidate_id == CAND_A
    assert fact_a1.round_id == "r1"
    assert fact_a1.round_name == "Technical"
    assert fact_a1.round_category == "technical"
    assert fact_a1.rating == "strong_yes"
    assert fact_a1.summary == "Excellent depth on distributed systems."
    assert fact_a1.interviewer_email == "alice@x.com"
    assert fact_a1.interviewer_name == "Alice Eng"
    assert fact_a1.has_feedback is True   # cr-a1 has an evidence row
    assert fact_a1.has_transcript is True  # cr-a1 in transcript ids


@pytest.mark.asyncio
async def test_has_feedback_and_transcript_flags_reflect_presence():
    scaffold = SupabaseScaffold(_make_fetcher())
    result = await scaffold.build(ORG_ID, REQ_ID, [CAND_A, CAND_B])
    fact_a2 = next(f for f in result.round_facts if f.candidate_round_id == "cr-a2")
    # cr-a2 has an evidence (feedback) row but NO transcript.
    assert fact_a2.has_feedback is True
    assert fact_a2.has_transcript is False


@pytest.mark.asyncio
async def test_rounds_total_by_candidate_is_plan_round_count():
    scaffold = SupabaseScaffold(_make_fetcher())
    result = await scaffold.build(ORG_ID, REQ_ID, [CAND_A, CAND_B, CAND_SPARSE])
    # Plan has 2 rounds — total is the same per candidate, including the sparse one.
    assert result.rounds_total_by_candidate[CAND_A] == 2
    assert result.rounds_total_by_candidate[CAND_B] == 2
    assert result.rounds_total_by_candidate[CAND_SPARSE] == 2


@pytest.mark.asyncio
async def test_assessment_scores_map_category_to_dimension():
    scaffold = SupabaseScaffold(_make_fetcher())
    result = await scaffold.build(ORG_ID, REQ_ID, [CAND_A, CAND_B])
    assert result.assessment_scores[CAND_A]["Distributed Systems"] == 5.0
    assert result.assessment_scores[CAND_A]["Leadership"] == 4.0
    assert result.assessment_scores[CAND_B]["Distributed Systems"] == 3.0


@pytest.mark.asyncio
async def test_evidence_status_maps_heading_to_dimension():
    scaffold = SupabaseScaffold(_make_fetcher())
    result = await scaffold.build(ORG_ID, REQ_ID, [CAND_A, CAND_B])
    assert result.evidence_status[CAND_A]["Distributed Systems"] == "verified"
    assert result.evidence_status[CAND_A]["Leadership"] == "partial"
    assert result.evidence_status[CAND_B]["Distributed Systems"] == "contradicted"


@pytest.mark.asyncio
async def test_feedback_headings_distinct_and_trimmed():
    """Addendum §3 source 2: distinct feedback_question.heading set, trimmed."""
    rows = [
        {"candidate_round_id": "cr-a1", "evidence_status": "verified",
         "feedback_questions": {"heading": "User Empathy"}},
        {"candidate_round_id": "cr-a2", "evidence_status": "partial",
         "feedback_questions": {"heading": "  Pricing "}},  # whitespace → trimmed
        {"candidate_round_id": "cr-b1", "evidence_status": "supported",
         "feedback_questions": {"heading": "User Empathy"}},  # duplicate → deduped
    ]
    scaffold = SupabaseScaffold(_make_fetcher(evidence_rows=rows))
    result = await scaffold.build(ORG_ID, REQ_ID, [CAND_A, CAND_B])
    assert set(result.feedback_headings) == {"User Empathy", "Pricing"}
    assert "  Pricing " not in result.feedback_headings  # trimmed


@pytest.mark.asyncio
async def test_supported_status_outranks_weaker_on_same_heading():
    """BUG 1: `supported` is a real prod evidence_status that must rank ABOVE
    `partial`/`none` (and below `verified`). When a candidate has two feedback rows
    on the SAME heading, the stronger `supported` must win — never be masked by a
    weaker later row."""
    rows = [
        # CAND_A, heading "Empathy": supported then none -> supported must win.
        {"candidate_round_id": "cr-a1", "evidence_status": "supported",
         "feedback_questions": {"heading": "Empathy"}},
        {"candidate_round_id": "cr-a2", "evidence_status": "none",
         "feedback_questions": {"heading": "Empathy"}},
        # CAND_B, heading "Pricing": partial then supported -> supported must win.
        {"candidate_round_id": "cr-b1", "evidence_status": "partial",
         "feedback_questions": {"heading": "Pricing"}},
        {"candidate_round_id": "cr-b2", "evidence_status": "supported",
         "feedback_questions": {"heading": "Pricing"}},
    ]
    cr_rows = [
        {"id": "cr-a1", "candidate_id": CAND_A, "round_id": "r1", "rating": "yes",
         "summary": None, "interviewer_email": None, "interviewer_name": None,
         "rounds": {"name": "Technical", "category": "technical"}},
        {"id": "cr-a2", "candidate_id": CAND_A, "round_id": "r2", "rating": "yes",
         "summary": None, "interviewer_email": None, "interviewer_name": None,
         "rounds": {"name": "System Design", "category": "technical"}},
        {"id": "cr-b1", "candidate_id": CAND_B, "round_id": "r1", "rating": "yes",
         "summary": None, "interviewer_email": None, "interviewer_name": None,
         "rounds": {"name": "Technical", "category": "technical"}},
        {"id": "cr-b2", "candidate_id": CAND_B, "round_id": "r2", "rating": "yes",
         "summary": None, "interviewer_email": None, "interviewer_name": None,
         "rounds": {"name": "System Design", "category": "technical"}},
    ]
    scaffold = SupabaseScaffold(_make_fetcher(cr_rows=cr_rows, evidence_rows=rows))
    result = await scaffold.build(ORG_ID, REQ_ID, [CAND_A, CAND_B])
    assert result.evidence_status[CAND_A]["Empathy"] == "supported"  # not "none"
    assert result.evidence_status[CAND_B]["Pricing"] == "supported"  # not "partial"


@pytest.mark.asyncio
async def test_feedback_headings_empty_when_no_feedback():
    scaffold = SupabaseScaffold(_make_fetcher(evidence_rows=[]))
    result = await scaffold.build(ORG_ID, REQ_ID, [CAND_A, CAND_B])
    assert result.feedback_headings == []


@pytest.mark.asyncio
async def test_latest_rating_by_candidate_is_most_recent_completed_round():
    """Addendum §5 verdict fallback: the per-candidate rating from the most-recent
    completed round (ordered by the fetcher; last row for a candidate wins)."""
    scaffold = SupabaseScaffold(_make_fetcher())
    result = await scaffold.build(ORG_ID, REQ_ID, [CAND_A, CAND_B])
    # CAND_A has two rounds (cr-a1 strong_yes, cr-a2 yes); the later row wins.
    assert result.latest_rating_by_candidate[CAND_A] == "yes"
    assert result.latest_rating_by_candidate[CAND_B] == "maybe"


@pytest.mark.asyncio
async def test_latest_rating_ignores_unknown_rating():
    rows = [
        {"id": "cr-a1", "candidate_id": CAND_A, "round_id": "r1", "rating": None,
         "summary": None, "interviewer_email": None, "interviewer_name": None,
         "rounds": {"name": "Technical", "category": "technical"}},
    ]
    scaffold = SupabaseScaffold(_make_fetcher(cr_rows=rows))
    result = await scaffold.build(ORG_ID, REQ_ID, [CAND_A])
    assert CAND_A not in result.latest_rating_by_candidate


@pytest.mark.asyncio
async def test_counts_correct():
    scaffold = SupabaseScaffold(_make_fetcher())
    result = await scaffold.build(ORG_ID, REQ_ID, [CAND_A, CAND_B])
    # 3 completed rounds all have feedback -> 3 scorecards; 2 transcripts.
    assert result.scorecard_count == 3
    assert result.transcript_count == 2


@pytest.mark.asyncio
async def test_sparse_candidate_yields_empty_maps_no_raise():
    scaffold = SupabaseScaffold(_make_fetcher())
    result = await scaffold.build(ORG_ID, REQ_ID, [CAND_A, CAND_B, CAND_SPARSE])
    # CAND_SPARSE has no rounds -> no facts, no assessment/evidence keys.
    assert all(f.candidate_id != CAND_SPARSE for f in result.round_facts)
    assert result.assessment_scores.get(CAND_SPARSE, {}) == {}
    assert result.evidence_status.get(CAND_SPARSE, {}) == {}
    # name still present (sparse candidates fall back to a placeholder, never raise)
    assert CAND_SPARSE in result.candidate_names
    assert isinstance(result.candidate_names[CAND_SPARSE], str)
    assert result.candidate_names[CAND_SPARSE]  # non-empty placeholder


@pytest.mark.asyncio
async def test_no_rounds_at_all_returns_empty_facts_no_raise():
    fetcher = _make_fetcher(
        cr_rows=[], assessment_rows=[], evidence_rows=[], transcript_ids=[]
    )
    scaffold = SupabaseScaffold(fetcher)
    result = await scaffold.build(ORG_ID, REQ_ID, [CAND_A])
    assert result.round_facts == []
    assert result.scorecard_count == 0
    assert result.transcript_count == 0
    assert result.assessment_scores == {} or result.assessment_scores.get(CAND_A, {}) == {}


@pytest.mark.asyncio
async def test_no_feedback_row_means_has_feedback_false():
    # A completed round with NO matching evidence row -> has_feedback False, not a scorecard.
    scaffold = SupabaseScaffold(
        _make_fetcher(evidence_rows=[])  # zero feedback rows
    )
    result = await scaffold.build(ORG_ID, REQ_ID, [CAND_A, CAND_B])
    assert all(f.has_feedback is False for f in result.round_facts)
    assert result.scorecard_count == 0


@pytest.mark.asyncio
async def test_duplicate_assessment_category_takes_max_score():
    rows = [
        {"candidate_round_id": "cr-a1", "category_name": "Distributed Systems", "score": 3},
        {"candidate_round_id": "cr-a2", "category_name": "Distributed Systems", "score": 5},
    ]
    scaffold = SupabaseScaffold(_make_fetcher(assessment_rows=rows))
    result = await scaffold.build(ORG_ID, REQ_ID, [CAND_A])
    assert result.assessment_scores[CAND_A]["Distributed Systems"] == 5.0


@pytest.mark.asyncio
async def test_fetcher_called_with_candidate_set():
    fetcher = _make_fetcher()
    scaffold = SupabaseScaffold(fetcher)
    await scaffold.build(ORG_ID, REQ_ID, [CAND_A, CAND_B])
    fetcher.fetch_candidate_rounds_for_requisition.assert_awaited_once()
    args, kwargs = fetcher.fetch_candidate_rounds_for_requisition.call_args
    passed = list(args) + list(kwargs.values())
    assert REQ_ID in passed
    assert [CAND_A, CAND_B] in passed
