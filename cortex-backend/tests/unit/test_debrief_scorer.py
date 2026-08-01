"""Unit tests for `DebriefScorer`'s SUPPLEMENTAL competency cell + rank (spec
2026-06-08). The primary rating-based spine (aggregate/verdict/confidence) is
tested in `test_debrief_rating_scoring.py`.

PURE scorer — no I/O, no async. Covers:
- `score_cell`: each standing base, each evidence_status adjustment on a graph
  base, the assessment blend, the contradicted flag, clamping + 1-decimal
  rounding, and the R7 rule — evidence_status ALONE no longer bases a value (a
  cell with only a status and no graph standing / assessment is None).
- `rank`: sort desc by aggregate_score + every tie-break, in-place mutation.
"""

import pytest

from src.model.debrief import CandidateSpine, CellScore, CompetencyStanding
from src.service.debrief.scorer import DebriefScorer


@pytest.fixture
def scorer() -> DebriefScorer:
    return DebriefScorer()


def _standing(
    standing: str | None = None,
    evidence_status: str | None = None,
    candidate_id: str = "c1",
    dimension: str = "Python",
    weight: float | None = None,
) -> CompetencyStanding:
    return CompetencyStanding(
        candidate_id=candidate_id,
        dimension=dimension,
        standing=standing,
        evidence_status=evidence_status,
        assessment_score=None,  # score_cell takes assessment via its own arg
        weight=weight,
    )


def _cell(
    value: float | None,
    is_must_have: bool = False,
    contradicted: bool = False,
    candidate_id: str = "c1",
    dimension: str = "d",
) -> CellScore:
    return CellScore(
        candidate_id=candidate_id,
        dimension=dimension,
        value=value,
        is_must_have=is_must_have,
        contradicted=contradicted,
    )


def _candidate(
    aggregate: float = 0.0,
    must_have_coverage_pct: float = 0.0,
    corroboration_count: int = 0,
    contradiction_count: int = 0,
    cells: list[CellScore] | None = None,
    candidate_id: str = "c1",
) -> CandidateSpine:
    return CandidateSpine(
        candidate_id=candidate_id,
        name=candidate_id,
        rounds_completed=0,
        rounds_total=0,
        cells=cells if cells is not None else [],
        aggregate_score=aggregate,
        must_have_coverage_pct=must_have_coverage_pct,
        corroboration_count=corroboration_count,
        contradiction_count=contradiction_count,
    )


# ===========================================================================
# cell score: identity / metadata propagation
# ===========================================================================
def test_score_cell_propagates_identity_and_must_have(scorer):
    cell = scorer.score_cell(
        _standing("STRONG_IN", candidate_id="cand", dimension="System Design"),
        assessment_score=None,
        is_must_have=True,
    )
    assert cell.candidate_id == "cand"
    assert cell.dimension == "System Design"
    assert cell.is_must_have is True


def test_score_cell_identity_from_standing_when_assessment_only_is_none(scorer):
    cell = scorer.score_cell(
        _standing(None, candidate_id="cx", dimension="dy"),
        assessment_score=None,
        is_must_have=False,
    )
    assert cell.candidate_id == "cx"
    assert cell.dimension == "dy"
    assert cell.value is None


# ===========================================================================
# step 1 — every standing base value
# ===========================================================================
@pytest.mark.parametrize(
    "standing,expected_base",
    [
        ("STRONG_IN", 4.0),
        ("ASSESSED_ON", 2.5),
        ("WEAK_IN", 1.5),
        ("DEMONSTRATED", 3.5),  # STRONG-leaning skill edge
        ("CLAIMED", 2.0),  # ASSESSED-leaning skill edge
    ],
)
def test_score_cell_standing_base(scorer, standing, expected_base):
    cell = scorer.score_cell(_standing(standing), assessment_score=None, is_must_have=False)
    assert cell.value == expected_base
    assert cell.contradicted is False


def test_score_cell_unknown_standing_label_is_none(scorer):
    cell = scorer.score_cell(_standing("MYSTERY"), assessment_score=None, is_must_have=False)
    assert cell.value is None


# ===========================================================================
# step 2 — evidence_status adjustments (applied to the GRAPH base only)
# ===========================================================================
def test_evidence_verified_adds_half(scorer):
    # ASSESSED_ON 2.5 + verified 0.5 = 3.0
    cell = scorer.score_cell(
        _standing("ASSESSED_ON", "verified"), assessment_score=None, is_must_have=False
    )
    assert cell.value == 3.0
    assert cell.contradicted is False


def test_evidence_verified_capped_at_four(scorer):
    cell = scorer.score_cell(
        _standing("STRONG_IN", "verified"), assessment_score=None, is_must_have=False
    )
    assert cell.value == 4.0


def test_evidence_partial_no_change(scorer):
    cell = scorer.score_cell(
        _standing("ASSESSED_ON", "partial"), assessment_score=None, is_must_have=False
    )
    assert cell.value == 2.5


def test_evidence_none_subtracts_quarter(scorer):
    # ASSESSED_ON 2.5 - 0.25 = 2.25 -> 1 decimal 2.2 (round-half-to-even).
    cell = scorer.score_cell(
        _standing("ASSESSED_ON", "none"), assessment_score=None, is_must_have=False
    )
    assert cell.value == 2.2


def test_evidence_contradicted_subtracts_one_and_flags(scorer):
    cell = scorer.score_cell(
        _standing("STRONG_IN", "contradicted"), assessment_score=None, is_must_have=True
    )
    assert cell.value == 3.0
    assert cell.contradicted is True


def test_contradicted_clamps_floor_to_one(scorer):
    # WEAK_IN 1.5 - 1.0 = 0.5 -> clamped to floor 1.0.
    cell = scorer.score_cell(
        _standing("WEAK_IN", "contradicted"), assessment_score=None, is_must_have=False
    )
    assert cell.value == 1.0
    assert cell.contradicted is True


def test_supabase_contradicted_pulls_strong_cortex_cell_down_and_flags(scorer):
    # Addendum §4: a confident Cortex STRONG_IN (4.0) grounded by a Supabase
    # 'contradicted' is pulled down (4.0 - 1.0 = 3.0) AND flagged.
    cell = scorer.score_cell(
        _standing("STRONG_IN", "contradicted"), assessment_score=None, is_must_have=True
    )
    assert cell.value == 3.0
    assert cell.contradicted is True


def test_evidence_supported_adds_quarter_to_cortex_base(scorer):
    # Cortex lead ASSESSED_ON 2.5 + Supabase 'supported' +0.25 = 2.75 -> 2.8.
    cell = scorer.score_cell(
        _standing("ASSESSED_ON", "supported"), assessment_score=None, is_must_have=False
    )
    assert cell.value == 2.8
    assert cell.contradicted is False


def test_unknown_evidence_status_treated_as_partial_neutral(scorer):
    # Unrecognized status normalizes to 'partial' (neutral, 0 adjustment) on a
    # graph base. ASSESSED_ON 2.5 + 0.0 = 2.5.
    cell = scorer.score_cell(
        _standing("ASSESSED_ON", "weird_status"), assessment_score=None, is_must_have=False
    )
    assert cell.value == 2.5
    assert cell.contradicted is False


# ===========================================================================
# step 3 — assessment blend (normalize score*4/5, average with graph value)
# ===========================================================================
def test_assessment_only_no_standing(scorer):
    cell = scorer.score_cell(None, assessment_score=5.0, is_must_have=False)
    assert cell.value == 4.0
    assert cell.contradicted is False


def test_assessment_only_normalizes(scorer):
    cell = scorer.score_cell(None, assessment_score=3.0, is_must_have=False)
    assert cell.value == 2.4


def test_assessment_blend_averages_with_graph(scorer):
    cell = scorer.score_cell(_standing("STRONG_IN"), assessment_score=5.0, is_must_have=False)
    assert cell.value == 4.0


def test_assessment_blend_averages_distinct(scorer):
    # ASSESSED_ON 2.5 + assessment 5 (->4.0) -> average 3.25 -> 3.2.
    cell = scorer.score_cell(_standing("ASSESSED_ON"), assessment_score=5.0, is_must_have=False)
    assert cell.value == 3.2


def test_assessment_blend_after_evidence_adjustment(scorer):
    # WEAK_IN 1.5 + verified 0.5 = 2.0 graph; assessment 5 -> 4.0; average 3.0.
    cell = scorer.score_cell(
        _standing("WEAK_IN", "verified"), assessment_score=5.0, is_must_have=False
    )
    assert cell.value == 3.0


def test_assessment_only_below_floor_clamps(scorer):
    cell = scorer.score_cell(None, assessment_score=1.0, is_must_have=False)
    assert cell.value == 1.0


def test_contradicted_flag_set_even_with_assessment_present(scorer):
    # contradicted comes from the standing's evidence even when assessment exists.
    cell = scorer.score_cell(
        _standing("STRONG_IN", "contradicted"), assessment_score=4.0, is_must_have=True
    )
    # graph: 4.0 - 1.0 = 3.0 ; assessment 4 -> 3.2 ; average 3.1.
    assert cell.value == 3.1
    assert cell.contradicted is True


def test_cortex_base_grounds_with_supabase_then_blends_assessment(scorer):
    # Cortex leads (WEAK_IN base 1.5) + Supabase grounding 'verified' +0.5 = 2.0;
    # assessment 5 -> 4.0; average 3.0.
    cell = scorer.score_cell(
        _standing("WEAK_IN", "verified"), assessment_score=5.0, is_must_have=False
    )
    assert cell.value == 3.0


# ===========================================================================
# R7 (2026-06-08) — evidence_status ALONE no longer bases a value
# ===========================================================================
@pytest.mark.parametrize(
    "status",
    ["verified", "supported", "partial", "none", "contradicted", "mystery"],
)
def test_no_standing_evidence_status_only_is_none(scorer, status):
    # No graph standing label, an evidence_status, NO assessment → None (R7).
    # The old _SUPABASE_ONLY_BASE path is gone; a status alone is not a value.
    cell = scorer.score_cell(_standing(None, status), assessment_score=None, is_must_have=False)
    assert cell.value is None


def test_no_standing_contradicted_still_flags_even_when_value_none(scorer):
    # A Supabase 'contradicted' on a no-standing cell sets the flag (surfacing a
    # risk) even though the value is None under R7.
    cell = scorer.score_cell(
        _standing(None, "contradicted"), assessment_score=None, is_must_have=True
    )
    assert cell.value is None
    assert cell.contradicted is True


def test_no_standing_evidence_status_with_assessment_is_assessment_only(scorer):
    # No graph standing → evidence_status contributes no base; the value is the
    # normalized assessment alone (5 -> 4.0), NOT a blend with a status base.
    cell = scorer.score_cell(
        _standing(None, "verified"), assessment_score=5.0, is_must_have=False
    )
    assert cell.value == 4.0


def test_no_standing_contradicted_with_assessment_flags_but_no_penalty(scorer):
    # 'contradicted' no longer pulls the value down when there's no graph standing
    # (R7) — it only flags. assessment 5 -> 4.0, flagged.
    cell = scorer.score_cell(
        _standing(None, "contradicted"), assessment_score=5.0, is_must_have=True
    )
    assert cell.value == 4.0
    assert cell.contradicted is True


# ===========================================================================
# step 4 — sparse → None
# ===========================================================================
def test_no_evidence_either_store_is_none(scorer):
    cell = scorer.score_cell(None, assessment_score=None, is_must_have=False)
    assert cell.value is None
    assert cell.contradicted is False


def test_standing_none_label_no_evidence_no_assessment_is_none(scorer):
    cell = scorer.score_cell(_standing(None, None), assessment_score=None, is_must_have=False)
    assert cell.value is None


# ===========================================================================
# rank (sort desc + tie-breaks, in-place + returned)
# ===========================================================================
def test_rank_sorts_descending_and_mutates_in_place(scorer):
    a = _candidate(aggregate=2.0, candidate_id="a")
    b = _candidate(aggregate=3.5, candidate_id="b")
    c = _candidate(aggregate=3.0, candidate_id="c")
    out = scorer.rank([a, b, c])
    assert [x.candidate_id for x in out] == ["b", "c", "a"]
    assert out[0].rank == 1 and out[1].rank == 2 and out[2].rank == 3
    assert b.rank == 1 and c.rank == 2 and a.rank == 3


def test_rank_tiebreak_must_have_coverage(scorer):
    lo = _candidate(aggregate=3.0, must_have_coverage_pct=40.0, candidate_id="lo")
    hi = _candidate(aggregate=3.0, must_have_coverage_pct=90.0, candidate_id="hi")
    out = scorer.rank([lo, hi])
    assert [x.candidate_id for x in out] == ["hi", "lo"]


def test_rank_tiebreak_corroboration_when_coverage_equal(scorer):
    lo = _candidate(
        aggregate=3.0, must_have_coverage_pct=80.0, corroboration_count=1, candidate_id="lo"
    )
    hi = _candidate(
        aggregate=3.0, must_have_coverage_pct=80.0, corroboration_count=5, candidate_id="hi"
    )
    out = scorer.rank([lo, hi])
    assert [x.candidate_id for x in out] == ["hi", "lo"]


def test_rank_tiebreak_fewest_contradictions_last(scorer):
    many = _candidate(
        aggregate=3.0, must_have_coverage_pct=80.0, corroboration_count=2,
        contradiction_count=3, candidate_id="many",
    )
    few = _candidate(
        aggregate=3.0, must_have_coverage_pct=80.0, corroboration_count=2,
        contradiction_count=0, candidate_id="few",
    )
    out = scorer.rank([many, few])
    assert [x.candidate_id for x in out] == ["few", "many"]


def test_rank_full_tiebreak_chain_stable(scorer):
    a = _candidate(
        aggregate=3.0, must_have_coverage_pct=80.0, corroboration_count=2,
        contradiction_count=1, candidate_id="a",
    )
    b = _candidate(
        aggregate=3.0, must_have_coverage_pct=80.0, corroboration_count=2,
        contradiction_count=1, candidate_id="b",
    )
    out = scorer.rank([a, b])
    assert out[0].rank == 1 and out[1].rank == 2
    assert {x.candidate_id for x in out} == {"a", "b"}


def test_rank_empty_list(scorer):
    assert scorer.rank([]) == []
