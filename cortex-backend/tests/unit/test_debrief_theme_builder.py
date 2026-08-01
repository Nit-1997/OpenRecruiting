"""Unit tests for `ThemeBuilder` (spec §6.6).

PURE behavior — no I/O, no async. Covers:
  * polarity→tone mapping (all 4 polarities + None)
  * cross-candidate clustering by trait name (org-singleton concept node)
  * evidence_count = distinct observing rounds
  * weight normalization into [0, 1]
  * top_n cap + weight-desc ordering
  * strengths/concerns derivation (positive vs negative/contradicted)
  * risks_and_gaps: contradiction surfaced + uncovered must-have surfaced
  * candidate_cells_for_dimension lookup
  * empty inputs
"""

from src.model.debrief import (
    CandidateSpine,
    CellScore,
    TraitObservation,
)
from src.service.debrief.theme_builder import ThemeBuilder


def _obs(
    candidate_id: str,
    trait: str,
    polarity: str | None = "positive",
    weight: float | None = 1.0,
    source_round_id: str | None = "r1",
    interviewer_name: str | None = "Dana",
) -> TraitObservation:
    return TraitObservation(
        candidate_id=candidate_id,
        trait=trait,
        polarity=polarity,
        weight=weight,
        source_round_id=source_round_id,
        interviewer_name=interviewer_name,
    )


def _cell(
    candidate_id: str,
    dimension: str,
    value: float | None,
    is_must_have: bool = False,
    contradicted: bool = False,
) -> CellScore:
    return CellScore(
        candidate_id=candidate_id,
        dimension=dimension,
        value=value,
        is_must_have=is_must_have,
        contradicted=contradicted,
    )


# --------------------------------------------------------------------------- #
# build_themes
# --------------------------------------------------------------------------- #
def test_build_themes_empty_returns_empty():
    assert ThemeBuilder().build_themes([]) == []


def test_polarity_to_tone_mapping_all_polarities():
    obs = [
        _obs("c1", "Positive trait", polarity="positive"),
        _obs("c1", "Negative trait", polarity="negative"),
        _obs("c1", "Neutral trait", polarity="neutral"),
        _obs("c1", "Contextual trait", polarity="contextual"),
        _obs("c1", "Unknown trait", polarity=None),
    ]
    themes = ThemeBuilder().build_themes(obs)
    tone_by_label = {t.label: t.tone for t in themes}
    assert tone_by_label["Positive trait"] == "pos"
    assert tone_by_label["Negative trait"] == "neg"
    assert tone_by_label["Neutral trait"] == "neu"
    assert tone_by_label["Contextual trait"] == "neu"
    assert tone_by_label["Unknown trait"] == "neu"


def test_clusters_same_trait_across_candidates():
    # Same trait name from two different candidates -> ONE theme cluster.
    obs = [
        _obs("c1", "Leadership", source_round_id="r1"),
        _obs("c2", "Leadership", source_round_id="r2"),
    ]
    themes = ThemeBuilder().build_themes(obs)
    leadership = [t for t in themes if t.label == "Leadership"]
    assert len(leadership) == 1


def test_evidence_count_is_distinct_rounds():
    # Three observations but only two DISTINCT source_round_ids -> evidence_count 2.
    obs = [
        _obs("c1", "Leadership", source_round_id="r1"),
        _obs("c2", "Leadership", source_round_id="r1"),  # duplicate round
        _obs("c2", "Leadership", source_round_id="r2"),
    ]
    themes = ThemeBuilder().build_themes(obs)
    leadership = next(t for t in themes if t.label == "Leadership")
    assert leadership.evidence_count == 2


def test_evidence_count_falls_back_when_no_round_ids():
    # Real observations but no round attribution -> never report 0 for a live theme.
    obs = [
        _obs("c1", "Leadership", source_round_id=None),
        _obs("c2", "Leadership", source_round_id=None),
    ]
    themes = ThemeBuilder().build_themes(obs)
    leadership = next(t for t in themes if t.label == "Leadership")
    assert leadership.evidence_count >= 1


def test_weight_normalized_into_0_1():
    obs = [
        _obs("c1", "Heavy", weight=10.0, source_round_id="r1"),
        _obs("c2", "Light", weight=2.0, source_round_id="r2"),
    ]
    themes = ThemeBuilder().build_themes(obs)
    weights = {t.label: t.weight for t in themes}
    # All weights in [0, 1]; the heaviest cluster normalizes to 1.0.
    for w in weights.values():
        assert 0.0 <= w <= 1.0
    assert weights["Heavy"] == 1.0
    assert weights["Light"] < weights["Heavy"]


def test_none_weight_treated_as_evidence():
    # A cluster whose observations all have weight=None still gets a positive weight.
    obs = [_obs("c1", "Curiosity", weight=None, source_round_id="r1")]
    themes = ThemeBuilder().build_themes(obs)
    curiosity = next(t for t in themes if t.label == "Curiosity")
    assert curiosity.weight > 0.0


def test_top_n_cap_and_weight_desc_order():
    obs = [
        _obs("c1", f"T{i}", weight=float(i), source_round_id=f"r{i}")
        for i in range(1, 11)  # T1..T10
    ]
    themes = ThemeBuilder().build_themes(obs, top_n=3)
    assert len(themes) == 3
    # Sorted by weight desc -> the three heaviest traits.
    labels = [t.label for t in themes]
    assert labels == ["T10", "T9", "T8"]
    assert themes[0].weight >= themes[1].weight >= themes[2].weight


def test_top_n_does_not_pad_when_fewer_clusters():
    obs = [_obs("c1", "Only", source_round_id="r1")]
    themes = ThemeBuilder().build_themes(obs, top_n=8)
    assert len(themes) == 1


# --------------------------------------------------------------------------- #
# strengths_and_concerns
# --------------------------------------------------------------------------- #
def test_strengths_and_concerns_splits_by_polarity():
    spine = CandidateSpine(
        candidate_id="c1",
        name="Avery",
        rounds_completed=2,
        rounds_total=3,
        trait_observations=[
            _obs("c1", "Product sense", polarity="positive", weight=5.0),
            _obs("c1", "Stakeholder mgmt", polarity="positive", weight=3.0),
            _obs("c1", "Impatience", polarity="negative", weight=4.0),
        ],
    )
    strengths, concerns = ThemeBuilder().strengths_and_concerns(spine)
    assert "Product sense" in strengths
    assert "Stakeholder mgmt" in strengths
    assert "Impatience" in concerns
    # Strengths sorted by weight desc.
    assert strengths.index("Product sense") < strengths.index("Stakeholder mgmt")


def test_strengths_and_concerns_contradicted_cell_is_concern():
    spine = CandidateSpine(
        candidate_id="c1",
        name="Avery",
        rounds_completed=1,
        rounds_total=1,
        cells=[_cell("c1", "System design", value=1.5, contradicted=True)],
        trait_observations=[],
    )
    strengths, concerns = ThemeBuilder().strengths_and_concerns(spine)
    assert strengths == []
    assert any("System design" in c for c in concerns)


def test_strengths_and_concerns_caps_lists():
    obs = [
        _obs("c1", f"Pos{i}", polarity="positive", weight=float(i))
        for i in range(1, 8)
    ]
    spine = CandidateSpine(
        candidate_id="c1",
        name="Avery",
        rounds_completed=1,
        rounds_total=1,
        trait_observations=obs,
    )
    strengths, _ = ThemeBuilder().strengths_and_concerns(spine)
    assert len(strengths) <= 3


def test_strengths_and_concerns_empty_candidate():
    spine = CandidateSpine(
        candidate_id="c1", name="Avery", rounds_completed=0, rounds_total=0
    )
    strengths, concerns = ThemeBuilder().strengths_and_concerns(spine)
    assert strengths == []
    assert concerns == []


# --------------------------------------------------------------------------- #
# risks_and_gaps
# --------------------------------------------------------------------------- #
def test_risk_contradiction_surfaced():
    spine = CandidateSpine(
        candidate_id="c1",
        name="Avery",
        rounds_completed=1,
        rounds_total=1,
        cells=[_cell("c1", "Leadership", value=1.5, is_must_have=True, contradicted=True)],
    )
    risks = ThemeBuilder().risks_and_gaps([spine], {"Leadership"})
    assert any("Leadership" in r and "Avery" in r for r in risks)


def test_uncovered_must_have_surfaced_as_gap():
    # Must-have dimension with a None cell -> gap.
    spine = CandidateSpine(
        candidate_id="c1",
        name="Avery",
        rounds_completed=1,
        rounds_total=1,
        cells=[_cell("c1", "Scale", value=None, is_must_have=True)],
    )
    risks = ThemeBuilder().risks_and_gaps([spine], {"Scale"})
    assert any("Scale" in r for r in risks)


def test_missing_must_have_cell_surfaced_as_gap():
    # Must-have dimension with NO cell at all -> still a gap.
    spine = CandidateSpine(
        candidate_id="c1",
        name="Avery",
        rounds_completed=1,
        rounds_total=1,
        cells=[],
    )
    risks = ThemeBuilder().risks_and_gaps([spine], {"Scale"})
    assert any("Scale" in r for r in risks)


def test_covered_must_have_is_not_a_gap():
    spine = CandidateSpine(
        candidate_id="c1",
        name="Avery",
        rounds_completed=1,
        rounds_total=1,
        cells=[_cell("c1", "Scale", value=3.5, is_must_have=True)],
    )
    risks = ThemeBuilder().risks_and_gaps([spine], {"Scale"})
    assert risks == []


def test_risks_and_gaps_empty_inputs():
    assert ThemeBuilder().risks_and_gaps([], set()) == []


def test_risks_and_gaps_dedupes():
    # Same gap should not appear twice.
    spine = CandidateSpine(
        candidate_id="c1",
        name="Avery",
        rounds_completed=1,
        rounds_total=1,
        cells=[_cell("c1", "Scale", value=None, is_must_have=True)],
    )
    risks = ThemeBuilder().risks_and_gaps([spine], {"Scale"})
    assert len(risks) == len(set(risks))


# --------------------------------------------------------------------------- #
# candidate_cells_for_dimension
# --------------------------------------------------------------------------- #
def test_candidate_cells_for_dimension_found():
    cell = _cell("c1", "Leadership", value=3.0)
    spine = CandidateSpine(
        candidate_id="c1",
        name="Avery",
        rounds_completed=1,
        rounds_total=1,
        cells=[cell, _cell("c1", "Scale", value=2.0)],
    )
    found = ThemeBuilder().candidate_cells_for_dimension(spine, "Leadership")
    assert found is cell


def test_candidate_cells_for_dimension_missing_returns_none():
    spine = CandidateSpine(
        candidate_id="c1",
        name="Avery",
        rounds_completed=1,
        rounds_total=1,
        cells=[_cell("c1", "Scale", value=2.0)],
    )
    assert ThemeBuilder().candidate_cells_for_dimension(spine, "Leadership") is None
