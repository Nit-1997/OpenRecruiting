"""Integration-style unit tests for the REAL `DebriefService` orchestrator (spec §8).

These wire the REAL `DebriefScorer`, `ThemeBuilder`, `PacketBuilder` and
`ProseSynthesizer` together with a MOCKED `SupabaseScaffold` (canned `ScaffoldData`),
a MOCKED `DebriefGraphReader` (canned standings / trait observations / corroboration)
and a MOCKED `ConceptExtractor` (AsyncMock — both the LLM-success path and the
`{}`-fallback path). This exercises the end-to-end wiring the pinned skeletons hid:
field names the orchestrator reads, CellScore identity, panel-vote construction and
ranking-before-snapshot ordering.

Assertions cover:
  * `generate()` returns a `DebriefPacket` that round-trips
    `DebriefPacket.model_validate(packet.model_dump())`.
  * candidates pre-ranked (index 0 = highest aggregate), `score_scale == 4`,
    decision_matrix OMITS keys for None cells, every enum valid.
  * a SPARSE candidate (no rounds / no graph signal) → blank matrix cells + lowered
    confidence, and `generate` does NOT raise (§D6).
  * a multi-candidate comparative packet has the right shape (panel_votes joined,
    themes present, assessment-only cells still rendered).
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.model.debrief import (
    CandidateRoundFact,
    CompetencyStanding,
    DebriefPacket,
    ScaffoldData,
    TraitObservation,
)
from src.service.concept_extractor import ConceptExtractor
from src.service.debrief.debrief_service import DebriefService
from src.service.debrief.graph_reader import DebriefGraphReader
from src.service.debrief.packet_builder import PacketBuilder
from src.service.debrief.prose_synthesizer import ProseSynthesizer
from src.service.debrief.scorer import DebriefScorer
from src.service.debrief.supabase_scaffold import SupabaseScaffold
from src.service.debrief.theme_builder import ThemeBuilder

ORG_ID = "org-1"
REQ_ID = "req-1"
CAND_TOP = "cand-top"  # strongest signal across the board
CAND_MID = "cand-mid"  # solid but weaker
CAND_SPARSE = "cand-sparse"  # no rounds, no graph signal (§D6)

MUST_HAVE = ["Distributed Systems", "Leadership"]
NICE_TO_HAVE = ["Go"]


# ---------------------------------------------------------------------------
# Canned scaffold / graph fixtures
# ---------------------------------------------------------------------------
def _round_fact(
    cr_id: str,
    candidate_id: str,
    *,
    round_id: str = "r1",
    round_name: str = "Technical",
    round_category: str | None = "technical",
    rating: str | None = "yes",
    summary: str | None = "Solid round.",
    interviewer_name: str | None = "Alice Eng",
    interviewer_email: str | None = "alice@x.com",
    has_feedback: bool = True,
    has_transcript: bool = True,
) -> CandidateRoundFact:
    return CandidateRoundFact(
        candidate_round_id=cr_id,
        candidate_id=candidate_id,
        round_id=round_id,
        round_name=round_name,
        round_category=round_category,
        rating=rating,
        summary=summary,
        interviewer_email=interviewer_email,
        interviewer_name=interviewer_name,
        has_feedback=has_feedback,
        has_transcript=has_transcript,
    )


def _scaffold(candidate_ids: list[str]) -> ScaffoldData:
    """A canned scaffold: two scored candidates with rounds + an assessment-only
    dimension, and (optionally) a sparse candidate with no rounds/signals."""
    round_facts = [
        _round_fact("cr-top-1", CAND_TOP, round_name="Technical", rating="strong_yes",
                    interviewer_name="Alice Eng", summary="Excellent depth."),
        _round_fact("cr-top-2", CAND_TOP, round_id="r2", round_name="System Design",
                    rating="yes", interviewer_name="Bob Arch", interviewer_email="bob@x.com",
                    summary="Strong design."),
        _round_fact("cr-mid-1", CAND_MID, round_name="Technical", rating="maybe",
                    interviewer_name="Alice Eng", summary="Mixed signal."),
    ]
    round_facts = [f for f in round_facts if f.candidate_id in candidate_ids]

    # assessment_scores: CAND_TOP has a "Go" (nice-to-have) score with NO graph
    # standing — this exercises the assessment-only cell path.
    assessment_scores: dict[str, dict[str, float]] = {}
    if CAND_TOP in candidate_ids:
        assessment_scores[CAND_TOP] = {"Go": 4.0}

    rounds_total = {
        CAND_TOP: 2,
        CAND_MID: 2,
        CAND_SPARSE: 2,
    }
    return ScaffoldData(
        org_id=ORG_ID,
        requisition_id=REQ_ID,
        role_title="Staff Engineer",
        must_have_skills=list(MUST_HAVE),
        nice_to_have_skills=list(NICE_TO_HAVE),
        candidate_names={
            CAND_TOP: "Ada Lovelace",
            CAND_MID: "Grace Hopper",
            CAND_SPARSE: "Carl Sparse",
        },
        round_facts=round_facts,
        rounds_total_by_candidate={cid: rounds_total.get(cid, 0) for cid in candidate_ids},
        assessment_scores=assessment_scores,
        evidence_status={},  # graph reader carries evidence_status on the standing
        scorecard_count=sum(1 for f in round_facts if f.has_feedback),
        transcript_count=sum(1 for f in round_facts if f.has_transcript),
    )


def _standings(candidate_ids: list[str]) -> list[CompetencyStanding]:
    """Graph competency standings: CAND_TOP strong on both must-haves, CAND_MID
    weaker. CAND_SPARSE gets nothing. CAND_TOP has NO graph standing on 'Go'
    (assessment-only)."""
    rows: list[CompetencyStanding] = []
    if CAND_TOP in candidate_ids:
        rows += [
            CompetencyStanding(CAND_TOP, "Distributed Systems", "STRONG_IN", "verified", None, 0.9),
            CompetencyStanding(CAND_TOP, "Leadership", "STRONG_IN", "verified", None, 0.8),
        ]
    if CAND_MID in candidate_ids:
        rows += [
            CompetencyStanding(CAND_MID, "Distributed Systems", "ASSESSED_ON", "partial", None, 0.5),
            CompetencyStanding(CAND_MID, "Leadership", "WEAK_IN", "none", None, 0.3),
        ]
    return rows


def _traits(candidate_ids: list[str]) -> list[TraitObservation]:
    rows: list[TraitObservation] = []
    if CAND_TOP in candidate_ids:
        rows += [
            TraitObservation(CAND_TOP, "Ownership", "positive", 0.9, "cr-top-1", "Alice Eng"),
            TraitObservation(CAND_TOP, "Ownership", "positive", 0.7, "cr-top-2", "Bob Arch"),
            TraitObservation(CAND_TOP, "Indecisive", "negative", 0.4, "cr-top-1", "Alice Eng"),
        ]
    if CAND_MID in candidate_ids:
        rows += [
            TraitObservation(CAND_MID, "Ownership", "positive", 0.5, "cr-mid-1", "Alice Eng"),
        ]
    return rows


def _corroboration(candidate_ids: list[str]) -> dict[str, int]:
    base = {CAND_TOP: 2, CAND_MID: 0, CAND_SPARSE: 0}
    return {cid: base.get(cid, 0) for cid in candidate_ids}


# ---------------------------------------------------------------------------
# Service assembly (real components, mocked I/O boundaries)
# ---------------------------------------------------------------------------
def _build_service(
    candidate_ids: list[str],
    *,
    extractor_returns: dict | Exception | None = None,
    dimensions: list[str] | None = None,
) -> DebriefService:
    scaffold = MagicMock(spec=SupabaseScaffold)
    scaffold.build = AsyncMock(return_value=_scaffold(candidate_ids))

    graph = MagicMock(spec=DebriefGraphReader)
    # dimensions resolved by the orchestrator come from scaffold seeds ∪ graph dims;
    # default to no extra graph-only dimensions so the matrix rows are predictable.
    graph.fetch_dimensions = AsyncMock(return_value=dimensions or [])
    graph.fetch_competency_standings = AsyncMock(return_value=_standings(candidate_ids))
    graph.fetch_trait_observations = AsyncMock(return_value=_traits(candidate_ids))
    graph.fetch_corroboration = AsyncMock(return_value=_corroboration(candidate_ids))

    extractor = MagicMock(spec=ConceptExtractor)
    if isinstance(extractor_returns, Exception):
        extractor.extract = AsyncMock(side_effect=extractor_returns)
    else:
        extractor.extract = AsyncMock(return_value=extractor_returns if extractor_returns is not None else {})

    return DebriefService(
        scaffold=scaffold,
        graph_reader=graph,
        scorer=DebriefScorer(),
        theme_builder=ThemeBuilder(),
        prose_synthesizer=ProseSynthesizer(extractor),
        packet_builder=PacketBuilder(),
    )


# Allowed FE-contract literal sets (mirror src/model/debrief.py / FE TS unions).
_VALID_VERDICTS = {"strong_hire", "hire", "mixed", "no_hire"}
_VALID_VOTES = {"strong_yes", "yes", "maybe", "no", "strong_no"}
_VALID_TONES = {"pos", "neg", "neu"}
_VALID_CONFIDENCE = {"low", "medium", "high"}
_VALID_STATUS = {"fresh", "superseded"}


def _assert_packet_valid(packet: DebriefPacket) -> None:
    """Round-trip the packet through Pydantic and assert every enum is in-bounds."""
    # Full re-validation: a serialized packet must reconstruct without error.
    DebriefPacket.model_validate(packet.model_dump())

    assert packet.status in _VALID_STATUS
    assert packet.confidence in _VALID_CONFIDENCE
    assert packet.verdict in _VALID_VERDICTS
    assert packet.generated_by == "Scout debrief agent"

    for cand in packet.candidates:
        assert cand.verdict in _VALID_VERDICTS
        assert cand.score_scale == 4
        for vote in cand.panel_votes:
            assert vote.vote in _VALID_VOTES
    for theme in packet.themes:
        assert theme.tone in _VALID_TONES
    for member in packet.panel_members:
        assert member.initials  # derived, non-empty
        assert member.color.startswith("#")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_generate_returns_valid_round_trippable_packet():
    """End-to-end: real scorer/themes/prose/packet over mocked I/O → a packet that
    survives a full Pydantic round-trip (the FE render contract)."""
    service = _build_service([CAND_TOP, CAND_MID])
    packet = await service.generate(ORG_ID, REQ_ID, [CAND_TOP, CAND_MID])

    assert isinstance(packet, DebriefPacket)
    _assert_packet_valid(packet)
    assert packet.requisition_id == REQ_ID
    assert packet.role_title == "Staff Engineer"
    assert packet.id  # uuid stamped by the orchestrator
    assert packet.generated_at  # iso stamped by the orchestrator


@pytest.mark.asyncio
async def test_high_confidence_for_three_agreeing_rounds_with_corroboration():
    """2026-06-08 §4 (rating-based confidence): ≥3 rated rounds with low panel
    disagreement (spread ≤ 1) AND Cortex corroboration on ≥ half the must-haves →
    overall `high`. A thin (≤1 round) or split panel cannot reach high."""
    cand_ids = [CAND_TOP, CAND_MID]
    scaffold_data = _scaffold(cand_ids)
    # CAND_TOP gets a 3rd agreeing round (now strong_yes/yes/yes, spread 1).
    scaffold_data.round_facts.append(
        _round_fact("cr-top-3", CAND_TOP, round_id="r3", round_name="Founder",
                    rating="yes", interviewer_name="Eve Founder", interviewer_email="eve@x.com")
    )
    scaffold = MagicMock(spec=SupabaseScaffold)
    scaffold.build = AsyncMock(return_value=scaffold_data)
    graph = MagicMock(spec=DebriefGraphReader)
    graph.fetch_dimensions = AsyncMock(return_value=[])
    graph.fetch_competency_standings = AsyncMock(return_value=_standings(cand_ids))
    graph.fetch_trait_observations = AsyncMock(return_value=_traits(cand_ids))
    graph.fetch_corroboration = AsyncMock(return_value=_corroboration(cand_ids))
    extractor = MagicMock(spec=ConceptExtractor)
    extractor.extract = AsyncMock(return_value={})
    service = DebriefService(
        scaffold=scaffold, graph_reader=graph, scorer=DebriefScorer(),
        theme_builder=ThemeBuilder(), prose_synthesizer=ProseSynthesizer(extractor),
        packet_builder=PacketBuilder(),
    )
    packet = await service.generate(ORG_ID, REQ_ID, cand_ids)

    assert packet.candidates[0].candidate_id == CAND_TOP
    assert packet.confidence == "high"


@pytest.mark.asyncio
async def test_confidence_medium_for_two_round_candidate():
    """A strong but THIN (2-round) panel can no longer reach high — the rating
    model requires ≥3 rated rounds. CAND_TOP (strong_yes + yes) → medium."""
    service = _build_service([CAND_TOP, CAND_MID])
    packet = await service.generate(ORG_ID, REQ_ID, [CAND_TOP, CAND_MID])
    assert packet.candidates[0].candidate_id == CAND_TOP
    assert packet.confidence == "medium"


@pytest.mark.asyncio
async def test_corroboration_fetch_is_must_have_scoped():
    """FIX 1 wiring: the service threads the resolved must-have set into
    `fetch_corroboration` (apples-to-apples with the scorer's ceil(n/2))."""
    service = _build_service([CAND_TOP, CAND_MID])
    await service.generate(ORG_ID, REQ_ID, [CAND_TOP, CAND_MID])

    call = service._graph.fetch_corroboration.await_args
    passed_must_have = call.args[2] if len(call.args) > 2 else call.kwargs["must_have_names"]
    assert set(passed_must_have) == set(MUST_HAVE)


@pytest.mark.asyncio
async def test_candidates_pre_ranked_and_scale_four():
    """index 0 == highest aggregate; ranks are 1-based and contiguous;
    score_scale is ALWAYS 4."""
    service = _build_service([CAND_MID, CAND_TOP])  # deliberately mid-first input
    packet = await service.generate(ORG_ID, REQ_ID, [CAND_MID, CAND_TOP])

    assert [c.rank for c in packet.candidates] == [1, 2]
    # CAND_TOP (STRONG_IN/STRONG_IN, verified) must outrank CAND_MID.
    assert packet.candidates[0].candidate_id == CAND_TOP
    assert packet.candidates[0].aggregate_score >= packet.candidates[1].aggregate_score
    assert all(c.score_scale == 4 for c in packet.candidates)
    # Overall packet verdict mirrors the top candidate's verdict (§6.4).
    assert packet.verdict == packet.candidates[0].verdict


@pytest.mark.asyncio
async def test_decision_matrix_omits_none_cells_but_keeps_scored():
    """A must-have row keys ONLY scored candidates; an assessment-only cell (no
    graph standing) is still rendered (catches the CellScore identity wiring)."""
    service = _build_service([CAND_TOP, CAND_MID])
    packet = await service.generate(ORG_ID, REQ_ID, [CAND_TOP, CAND_MID])

    by_dim = {row.dimension: row for row in packet.decision_matrix}
    # Must-have rows present, ordered first.
    assert packet.decision_matrix[0].dimension in MUST_HAVE
    assert packet.decision_matrix[1].dimension in MUST_HAVE

    ds = by_dim["Distributed Systems"]
    assert set(ds.scores.keys()) == {CAND_TOP, CAND_MID}
    # winner is the higher-scored candidate (STRONG_IN > ASSESSED_ON).
    assert ds.winner_ids == [CAND_TOP]

    # 'Go' is a nice-to-have with ONLY an assessment score for CAND_TOP and no
    # graph standing — it must still appear in the matrix and be keyed to CAND_TOP.
    go = by_dim["Go"]
    assert CAND_TOP in go.scores
    # assessment 4 on the 1..5 scale normalizes to 4*4/5 = 3.2 on the 1..4 cell scale.
    assert go.scores[CAND_TOP] == pytest.approx(3.2)
    assert CAND_MID not in go.scores  # no signal for mid → omitted (em-dash)


@pytest.mark.asyncio
async def test_multi_candidate_comparative_shape():
    """Comparative packet: panel votes joined to panel members, themes clustered,
    source stats counted."""
    service = _build_service([CAND_TOP, CAND_MID])
    packet = await service.generate(ORG_ID, REQ_ID, [CAND_TOP, CAND_MID])

    # Panel members are the union of distinct interviewers across rounds.
    member_names = {m.name for m in packet.panel_members}
    assert {"Alice Eng", "Bob Arch"}.issubset(member_names)

    # Every panel vote references a real panel member name (join key, §6.6).
    for cand in packet.candidates:
        for vote in cand.panel_votes:
            assert vote.panelist in member_names

    # CAND_TOP has two completed rounds → two panel votes.
    top = next(c for c in packet.candidates if c.candidate_id == CAND_TOP)
    assert len(top.panel_votes) == 2
    assert {v.vote for v in top.panel_votes} == {"strong_yes", "yes"}

    # Themes cluster the org-singleton traits; "Ownership" leads (heaviest weight).
    assert packet.themes
    labels = [t.label for t in packet.themes]
    assert "Ownership" in labels
    ownership = next(t for t in packet.themes if t.label == "Ownership")
    assert ownership.tone == "pos"
    assert ownership.evidence_count >= 2  # distinct rounds cr-top-1 / cr-top-2

    assert packet.source_stats.scorecards == 3
    assert packet.source_stats.transcripts == 3
    # Graph-enriched (standings + themes + corroboration present) → tiered subtitle.
    assert packet.subtitle == "Graph-enriched · 2 candidates compared"


@pytest.mark.asyncio
async def test_sparse_candidate_blanks_and_lowered_confidence():
    """§D6: a candidate with no rounds and no graph signal → blank matrix cells
    (missing keys), low confidence, and `generate` does NOT raise."""
    service = _build_service([CAND_TOP, CAND_SPARSE])
    packet = await service.generate(ORG_ID, REQ_ID, [CAND_TOP, CAND_SPARSE])

    _assert_packet_valid(packet)

    sparse = next(c for c in packet.candidates if c.candidate_id == CAND_SPARSE)
    # No rounds completed; total preserved from scaffold.
    assert sparse.rounds_completed == 0
    assert sparse.aggregate_score == 0.0
    assert sparse.panel_votes == []

    # Sparse candidate's key is OMITTED from every must-have matrix row (em-dash).
    for row in packet.decision_matrix:
        if row.dimension in MUST_HAVE:
            assert CAND_SPARSE not in row.scores

    # Sparse candidate ranks last; the strong candidate leads.
    assert packet.candidates[0].candidate_id == CAND_TOP
    assert sparse.rank == 2


@pytest.mark.asyncio
async def test_assessment_only_contradicted_cell_flagged_and_risk():
    """R7 (2026-06-08): a cell with NO graph standing but a Supabase `contradicted`
    evidence_status is scored by the assessment alone (no Supabase-only base), and
    still flags the contradiction as a risk — evidence_status grounds a risk flag,
    not a fabricated competency value."""
    # Build a custom service whose scaffold has a Supabase-side contradicted
    # evidence_status on an assessment-only dimension for CAND_MID, with NO graph
    # standing for it (graph standings come from `_standings`, which has none on
    # the nice-to-have 'Go'). We attach the score + status via 'Go'.
    cand_ids = [CAND_TOP, CAND_MID]
    scaffold_data = _scaffold(cand_ids)
    # CAND_MID gets an assessment-only 'Go' score + a Supabase contradicted status.
    scaffold_data.assessment_scores.setdefault(CAND_MID, {})["Go"] = 5.0
    scaffold_data.evidence_status.setdefault(CAND_MID, {})["Go"] = "contradicted"

    scaffold = MagicMock(spec=SupabaseScaffold)
    scaffold.build = AsyncMock(return_value=scaffold_data)
    graph = MagicMock(spec=DebriefGraphReader)
    graph.fetch_dimensions = AsyncMock(return_value=[])
    graph.fetch_competency_standings = AsyncMock(return_value=_standings(cand_ids))
    graph.fetch_trait_observations = AsyncMock(return_value=_traits(cand_ids))
    graph.fetch_corroboration = AsyncMock(return_value=_corroboration(cand_ids))
    extractor = MagicMock(spec=ConceptExtractor)
    extractor.extract = AsyncMock(return_value={})

    service = DebriefService(
        scaffold=scaffold,
        graph_reader=graph,
        scorer=DebriefScorer(),
        theme_builder=ThemeBuilder(),
        prose_synthesizer=ProseSynthesizer(extractor),
        packet_builder=PacketBuilder(),
    )
    packet = await service.generate(ORG_ID, REQ_ID, cand_ids)
    _assert_packet_valid(packet)

    go = next(row for row in packet.decision_matrix if row.dimension == "Go")
    # R7 (2026-06-08): with NO graph standing, evidence_status no longer bases a
    # value, so 'contradicted' does not numerically penalise — the cell is the
    # assessment alone (5 -> 4.0). It STILL flags the contradiction as a risk.
    assert go.scores[CAND_MID] == pytest.approx(4.0)

    # A contradiction risk for CAND_MID on 'Go' surfaces (proves contradicted=True
    # reached the cell from the Supabase evidence_status even though value survived).
    mid_name = scaffold_data.candidate_names[CAND_MID]
    assert any("Go" in r and mid_name in r and "Contradicted" in r for r in packet.risks)


@pytest.mark.asyncio
async def test_supabase_contradicted_grounds_strong_cortex_cell_and_surfaces_risk():
    """Addendum §4 (Cortex leads, Supabase grounds): a Supabase `contradicted` on a
    must-have CAND_TOP has a graph STRONG_IN standing for PULLS THE CELL DOWN
    (4.0 -> 3.0), flags it, and surfaces a contradiction risk — the graph is
    grounded in transcript truth, never overriding a real contradiction. (This
    REVERSES the prior 'graph evidence wins' behavior per the addendum.)"""
    cand_ids = [CAND_TOP, CAND_MID]
    scaffold_data = _scaffold(cand_ids)
    # Supabase says 'contradicted' on a must-have CAND_TOP has a STRONG_IN graph
    # standing for. Supabase grounds → cell pulled down + risk surfaces.
    scaffold_data.evidence_status.setdefault(CAND_TOP, {})["Distributed Systems"] = "contradicted"

    scaffold = MagicMock(spec=SupabaseScaffold)
    scaffold.build = AsyncMock(return_value=scaffold_data)
    graph = MagicMock(spec=DebriefGraphReader)
    graph.fetch_dimensions = AsyncMock(return_value=[])
    graph.fetch_competency_standings = AsyncMock(return_value=_standings(cand_ids))
    graph.fetch_trait_observations = AsyncMock(return_value=_traits(cand_ids))
    graph.fetch_corroboration = AsyncMock(return_value=_corroboration(cand_ids))
    extractor = MagicMock(spec=ConceptExtractor)
    extractor.extract = AsyncMock(return_value={})

    service = DebriefService(
        scaffold=scaffold,
        graph_reader=graph,
        scorer=DebriefScorer(),
        theme_builder=ThemeBuilder(),
        prose_synthesizer=ProseSynthesizer(extractor),
        packet_builder=PacketBuilder(),
    )
    packet = await service.generate(ORG_ID, REQ_ID, cand_ids)

    ds = next(row for row in packet.decision_matrix if row.dimension == "Distributed Systems")
    # Cortex STRONG_IN base 4.0 + Supabase 'contradicted' -1.0 = 3.0 (pulled down).
    assert ds.scores[CAND_TOP] == pytest.approx(3.0)

    top_name = scaffold_data.candidate_names[CAND_TOP]
    # The contradiction risk DOES surface — Supabase grounds the Cortex lead.
    assert any(
        "Distributed Systems" in r and top_name in r and "Contradicted" in r
        for r in packet.risks
    )


@pytest.mark.asyncio
async def test_llm_success_path_uses_prose():
    """LLM-success path: the synthesizer maps returned prose onto the packet
    without altering any deterministic score/rank/verdict."""
    llm = {
        "per_candidate": {
            CAND_TOP: {"headline": "Top pick for the role.",
                       "recommendation": "Move to offer."},
            CAND_MID: {"headline": "Borderline.", "recommendation": "Hold."},
        },
        "headline_recommendation": "Recommend Ada Lovelace.",
        "risks": ["Confirm leadership scope in references."],
        "next_steps": [{"label": "Schedule offer call", "owner": "Recruiter", "due": "2026-06-10"}],
        "theme_labels": {"0": "Strong ownership"},
        "matrix_notes": {"Distributed Systems": "Ada clearly leads."},
    }
    service = _build_service([CAND_TOP, CAND_MID], extractor_returns=llm)
    packet = await service.generate(ORG_ID, REQ_ID, [CAND_TOP, CAND_MID])

    _assert_packet_valid(packet)
    top = next(c for c in packet.candidates if c.candidate_id == CAND_TOP)
    assert top.headline == "Top pick for the role."
    assert top.recommendation == "Move to offer."
    assert packet.headline_recommendation == "Recommend Ada Lovelace."
    assert "Confirm leadership scope in references." in packet.risks
    assert any(s.label == "Schedule offer call" for s in packet.next_steps)
    # theme_labels[0] overrides the first theme's label.
    assert packet.themes[0].label == "Strong ownership"


@pytest.mark.asyncio
async def test_llm_empty_fallback_still_valid_packet():
    """`{}` from the extractor → deterministic template prose for EVERY prose field;
    packet is still complete + valid (fail-soft, §7)."""
    service = _build_service([CAND_TOP, CAND_MID], extractor_returns={})
    packet = await service.generate(ORG_ID, REQ_ID, [CAND_TOP, CAND_MID])

    _assert_packet_valid(packet)
    # Templated headline/recommendation are non-empty for every candidate.
    for cand in packet.candidates:
        assert cand.headline
        assert cand.recommendation
    assert packet.headline_recommendation
    assert packet.next_steps  # template seeds at least one next step


@pytest.mark.asyncio
async def test_llm_exception_fallback_does_not_raise():
    """An exception inside the LLM call degrades to the deterministic fallback —
    `generate` returns a complete valid packet, never propagates the error."""
    service = _build_service(
        [CAND_TOP, CAND_MID], extractor_returns=RuntimeError("llm down")
    )
    packet = await service.generate(ORG_ID, REQ_ID, [CAND_TOP, CAND_MID])

    _assert_packet_valid(packet)
    for cand in packet.candidates:
        assert cand.headline
        assert cand.recommendation


# ===========================================================================
# Addendum: tiered data sourcing (DimensionResolver wiring + enrichment tier)
# ===========================================================================
def _empty_graph_service(scaffold_data, cand_ids):
    """A service over a Supabase-only scaffold with NO graph signal at all —
    mirrors the live run where the graph had no edges for the org."""
    scaffold = MagicMock(spec=SupabaseScaffold)
    scaffold.build = AsyncMock(return_value=scaffold_data)
    graph = MagicMock(spec=DebriefGraphReader)
    graph.fetch_dimensions = AsyncMock(return_value=[])
    graph.fetch_competency_standings = AsyncMock(return_value=[])
    graph.fetch_trait_observations = AsyncMock(return_value=[])
    graph.fetch_corroboration = AsyncMock(return_value={cid: 0 for cid in cand_ids})
    extractor = MagicMock(spec=ConceptExtractor)
    extractor.extract = AsyncMock(return_value={})
    return DebriefService(
        scaffold=scaffold,
        graph_reader=graph,
        scorer=DebriefScorer(),
        theme_builder=ThemeBuilder(),
        prose_synthesizer=ProseSynthesizer(extractor),
        packet_builder=PacketBuilder(),
    )


def _live_run_scaffold(cand_ids: list[str], ratings: dict[str, str]) -> ScaffoldData:
    """The live-run shape: NO configured skills, NO graph — only per-competency
    feedback headings (User Empathy / Pricing / Product Sense) with evidence_status
    + panel ratings. This is exactly the data that produced an EMPTY packet."""
    headings = ["User Empathy", "Pricing", "Product Sense"]
    round_facts = []
    evidence_status: dict[str, dict[str, str]] = {}
    for cid in cand_ids:
        round_facts.append(
            _round_fact(f"cr-{cid}", cid, round_name="PM Screen", rating=ratings[cid],
                        interviewer_name="Dana PM", summary="Screen complete.")
        )
        # Each candidate has feedback on all three competencies (varied statuses).
        evidence_status[cid] = {
            "User Empathy": "verified",
            "Pricing": "supported",
            "Product Sense": "partial",
        }
    return ScaffoldData(
        org_id=ORG_ID,
        requisition_id=REQ_ID,
        role_title="Product Manager",
        must_have_skills=[],   # none configured (the live-run condition)
        nice_to_have_skills=[],
        candidate_names={cid: f"Cand {cid}" for cid in cand_ids},
        round_facts=round_facts,
        rounds_total_by_candidate={cid: 1 for cid in cand_ids},
        assessment_scores={},
        evidence_status=evidence_status,
        feedback_headings=headings,
        latest_rating_by_candidate=dict(ratings),
        scorecard_count=len(cand_ids),
        transcript_count=len(cand_ids),
    )


@pytest.mark.asyncio
async def test_regression_empty_graph_feedback_headings_populate_matrix():
    """CRITICAL regression (live run): 3 candidates with feedback on User Empathy /
    Pricing / Product Sense and NO graph → a 3-dimension matrix (not empty), a
    `yes`-rated candidate is NOT no_hire, and the tier is `baseline`."""
    cand_ids = ["govind", "asha", "ravi"]
    ratings = {"govind": "yes", "asha": "maybe", "ravi": "no"}
    scaffold_data = _live_run_scaffold(cand_ids, ratings)
    service = _empty_graph_service(scaffold_data, cand_ids)
    packet = await service.generate(ORG_ID, REQ_ID, cand_ids)

    _assert_packet_valid(packet)

    # Baseline tier (no graph) → the matrix is the ROUND-decision grid: one row per
    # round (here the single "PM Screen"), cells = each candidate's rating.
    dims = {row.dimension for row in packet.decision_matrix}
    assert dims == {"PM Screen"}

    # Every candidate took (and was rated on) the round → all keyed in the row.
    for row in packet.decision_matrix:
        assert set(row.scores.keys()) == set(cand_ids)

    # Govind (rated `yes` → 4/5 → hire), Ravi (`no` → 2/5 → no_hire): ratings drive
    # the verdict and they DIFFER (no more "everything the same value").
    govind = next(c for c in packet.candidates if c.candidate_id == "govind")
    ravi = next(c for c in packet.candidates if c.candidate_id == "ravi")
    assert govind.verdict == "hire"
    assert ravi.verdict == "no_hire"
    assert govind.aggregate_score > ravi.aggregate_score

    # BUG 2: candidates WITH scorable cells are not insufficient.
    assert all(c.aggregate_insufficient is False for c in packet.candidates)

    # Supabase-only packet → baseline tier (surfaced in the subtitle).
    assert packet.subtitle.startswith("Baseline")


@pytest.mark.asyncio
async def test_rating_scores_candidate_with_no_competency_cells():
    """2026-06-08 §2: with no graph/skills/assessments the candidate has zero
    competency cells, but the per-round RATING still scores them — `yes` → 4/5 →
    3.2/4, a real score (NOT the old insufficient 0.0 sentinel), verdict hire."""
    cand_ids = ["solo"]
    scaffold_data = ScaffoldData(
        org_id=ORG_ID,
        requisition_id=REQ_ID,
        role_title="Product Manager",
        candidate_names={"solo": "Solo Cand"},
        round_facts=[_round_fact("cr-solo", "solo", rating="yes", interviewer_name="Dana PM")],
        rounds_total_by_candidate={"solo": 1},
        feedback_headings=[],
        latest_rating_by_candidate={"solo": "yes"},
        scorecard_count=1,
        transcript_count=1,
    )
    service = _empty_graph_service(scaffold_data, cand_ids)
    packet = await service.generate(ORG_ID, REQ_ID, cand_ids)

    _assert_packet_valid(packet)
    solo = packet.candidates[0]
    assert solo.aggregate_score == pytest.approx(3.2)  # yes → 4/5 → 3.2/4
    assert solo.aggregate_insufficient is False  # has a rated round → scorable
    assert solo.verdict == "hire"


@pytest.mark.asyncio
async def test_verdict_from_rating_strong_no_is_no_hire_not_strong():
    """A `no`/`strong_no` rating with zero cells → no_hire (never strong_hire)."""
    scaffold_data = ScaffoldData(
        org_id=ORG_ID, requisition_id=REQ_ID, role_title="PM",
        candidate_names={"x": "X"},
        round_facts=[_round_fact("cr-x", "x", rating="strong_no", interviewer_name="Dana")],
        rounds_total_by_candidate={"x": 1},
        latest_rating_by_candidate={"x": "strong_no"},
        scorecard_count=1, transcript_count=1,
    )
    service = _empty_graph_service(scaffold_data, ["x"])
    packet = await service.generate(ORG_ID, REQ_ID, ["x"])
    assert packet.candidates[0].verdict == "no_hire"


@pytest.mark.asyncio
async def test_no_rating_zero_cells_defaults_mixed():
    """Zero cells AND no usable rating → honest `mixed` (not a fabricated hire)."""
    scaffold_data = ScaffoldData(
        org_id=ORG_ID, requisition_id=REQ_ID, role_title="PM",
        candidate_names={"x": "X"},
        round_facts=[_round_fact("cr-x", "x", rating=None, interviewer_name="Dana")],
        rounds_total_by_candidate={"x": 1},
        latest_rating_by_candidate={},
        scorecard_count=0, transcript_count=0,
    )
    service = _empty_graph_service(scaffold_data, ["x"])
    packet = await service.generate(ORG_ID, REQ_ID, ["x"])
    assert packet.candidates[0].verdict == "mixed"


@pytest.mark.asyncio
async def test_enrichment_tier_graph_enriched_when_cortex_present():
    """A packet with real graph standings + themes + corroboration → graph_enriched
    tier in the subtitle."""
    service = _build_service([CAND_TOP, CAND_MID])  # has standings/traits/corroboration
    packet = await service.generate(ORG_ID, REQ_ID, [CAND_TOP, CAND_MID])
    assert packet.subtitle.startswith("Graph-enriched")


@pytest.mark.asyncio
async def test_baseline_round_matrix_differentiates_candidates_by_rating():
    """The core fix: in the baseline tier the SAME round shows DIFFERENT per-cell
    values for candidates with different ratings (no more "everything the same
    value"). Two candidates on one round, strong_yes vs strong_no → 4.0 vs 1.0."""
    cand_ids = ["good", "bad"]
    scaffold_data = ScaffoldData(
        org_id=ORG_ID, requisition_id=REQ_ID, role_title="PM",
        candidate_names={"good": "Good Cand", "bad": "Bad Cand"},
        round_facts=[
            _round_fact("cr-good", "good", round_id="r1", round_name="Screen",
                        rating="strong_yes", interviewer_name="Dana"),
            _round_fact("cr-bad", "bad", round_id="r1", round_name="Screen",
                        rating="strong_no", interviewer_name="Dana"),
        ],
        rounds_total_by_candidate={"good": 1, "bad": 1},
        latest_rating_by_candidate={"good": "strong_yes", "bad": "strong_no"},
        scorecard_count=2, transcript_count=2,
    )
    service = _empty_graph_service(scaffold_data, cand_ids)
    packet = await service.generate(ORG_ID, REQ_ID, cand_ids)

    screen = next(r for r in packet.decision_matrix if r.dimension == "Screen")
    assert screen.scores["good"] == pytest.approx(4.0)  # strong_yes
    assert screen.scores["bad"] == pytest.approx(1.0)   # strong_no
    assert screen.winner_ids == ["good"]
    assert packet.candidates[0].candidate_id == "good"  # ranked above by rating
