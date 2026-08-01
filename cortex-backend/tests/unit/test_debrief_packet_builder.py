"""Unit tests for `PacketBuilder` (spec §4 render contract + invariants).

PURE behavior — no I/O, no async. `packet_id`/`generated_at` are passed IN, so a
fixed input yields a byte-for-byte fixed packet. Covers:
  * pre-ranking preserved (spine already ranked; index 0 == winner)
  * per-candidate snapshot mapping (headline/recommendation from prose, score_scale==4)
  * decision_matrix: missing cell value → candidate KEY OMITTED (never 0 / em-dash)
  * winner_ids = max-score candidate(s), ties included
  * theme label override from prose.theme_labels (tone/weight/evidence_count kept)
  * matrix note from prose.matrix_notes (fallback "")
  * initials/color derivation deterministic + stable per name
  * panel_members derived initials/color; panelist join to panel_members[].name
  * enum validation rejects a bad spine value (defensive, clear error)
  * full packet is `DebriefPacket.model_validate`-clean
"""

import pytest

from src.model.debrief import (
    CandidateSpine,
    CellScore,
    DebriefPacket,
    DebriefPanelVote,
    DebriefSourceStats,
    DebriefSpine,
    DebriefTheme,
    NextStep,
    PanelMember,
    ProseBundle,
    RoundRating,
)
from src.service.debrief.packet_builder import PacketBuilder

PACKET_ID = "11111111-1111-1111-1111-111111111111"
GENERATED_AT = "2026-06-07T12:00:00+00:00"


# --------------------------------------------------------------------------- #
# fixture builders
# --------------------------------------------------------------------------- #
def _cell(dimension: str, value: float | None, is_must_have: bool = False) -> CellScore:
    return CellScore(
        candidate_id="ignored",  # PacketBuilder keys on the CandidateSpine, not the cell
        dimension=dimension,
        value=value,
        is_must_have=is_must_have,
    )


def _candidate(
    candidate_id: str,
    name: str,
    rank: int,
    verdict: str = "hire",
    aggregate: float = 3.5,
    cells: list[CellScore] | None = None,
    panel_votes: list[DebriefPanelVote] | None = None,
) -> CandidateSpine:
    spine = CandidateSpine(
        candidate_id=candidate_id,
        name=name,
        rounds_completed=3,
        rounds_total=4,
        cells=cells or [],
        aggregate_score=aggregate,
        rank=rank,
        verdict=verdict,
        top_strengths=["product sense"],
        top_concerns=["scale"],
        panel_votes=panel_votes or [],
    )
    return spine


def _spine(
    candidates: list[CandidateSpine],
    dimensions: list[str],
    panel_members: list[PanelMember] | None = None,
    themes: list[DebriefTheme] | None = None,
    confidence: str = "high",
    overall_verdict: str = "hire",
    enrichment_tier: str = "graph_enriched",
) -> DebriefSpine:
    # These fixtures carry competency cells/dimensions, so they model a
    # graph-enriched packet (competency matrix). Baseline (round-matrix) packets
    # are covered by the dedicated round-matrix tests below.
    return DebriefSpine(
        org_id="org-1",
        requisition_id="req-1",
        role_title="Senior Product Manager",
        dimensions=dimensions,
        must_have_dimensions={dimensions[0]} if dimensions else set(),
        candidates=candidates,
        panel_members=panel_members or [],
        themes=themes or [],
        source_stats=DebriefSourceStats(scorecards=5, transcripts=4),
        confidence=confidence,
        overall_verdict=overall_verdict,
        risks=["seed risk"],
        enrichment_tier=enrichment_tier,
    )


def _prose(candidate_ids: list[str]) -> ProseBundle:
    return ProseBundle(
        per_candidate={
            cid: {"headline": f"headline {cid}", "recommendation": f"reco {cid}"}
            for cid in candidate_ids
        },
        headline_recommendation="Recommend the top candidate.",
        risks=["polished risk"],
        next_steps=[NextStep(label="Schedule offer call", owner="Dana", due="2026-06-10")],
        theme_labels={},
        matrix_notes={},
    )


def _two_candidate_spine() -> tuple[DebriefSpine, ProseBundle]:
    dimensions = ["Product Sense", "Platform Scale"]
    avery = _candidate(
        "c-avery",
        "Avery Stone",
        rank=1,
        aggregate=3.6,
        cells=[_cell("Product Sense", 4.0, True), _cell("Platform Scale", 2.5)],
        panel_votes=[
            DebriefPanelVote(
                panelist="Dana Lee",
                panelist_role="Hiring Manager",
                vote="yes",
                rationale="Clear strategic thinking.",
            )
        ],
    )
    blake = _candidate(
        "c-blake",
        "Blake Rivera",
        rank=2,
        verdict="mixed",
        aggregate=2.9,
        # Platform Scale value is None -> key MUST be omitted from that row's scores.
        cells=[_cell("Product Sense", 3.0, True), _cell("Platform Scale", None)],
    )
    panel = [PanelMember(name="Dana Lee", role="Hiring Manager", initials="", color="")]
    themes = [
        DebriefTheme(label="Strategic thinking", tone="pos", weight=0.9, evidence_count=3),
        DebriefTheme(label="Scale gap", tone="neg", weight=0.4, evidence_count=1),
    ]
    spine = _spine([avery, blake], dimensions, panel_members=panel, themes=themes)
    return spine, _prose(["c-avery", "c-blake"])


# --------------------------------------------------------------------------- #
# pre-ranking preserved
# --------------------------------------------------------------------------- #
def test_candidate_order_preserved_index_zero_is_winner():
    spine, prose = _two_candidate_spine()
    packet = PacketBuilder().build(spine, prose, PACKET_ID, GENERATED_AT)

    assert [c.candidate_id for c in packet.candidates] == ["c-avery", "c-blake"]
    assert packet.candidates[0].candidate_id == "c-avery"
    assert packet.candidates[0].rank == 1


def test_does_not_resort_when_spine_order_disagrees_with_rank():
    # The spine is the source of truth for order; PacketBuilder must NOT re-sort.
    spine, prose = _two_candidate_spine()
    spine.candidates.reverse()  # now [blake(rank2), avery(rank1)]
    packet = PacketBuilder().build(spine, prose, PACKET_ID, GENERATED_AT)
    assert [c.candidate_id for c in packet.candidates] == ["c-blake", "c-avery"]


# --------------------------------------------------------------------------- #
# per-candidate snapshot mapping
# --------------------------------------------------------------------------- #
def test_snapshot_pulls_prose_and_fixed_score_scale():
    spine, prose = _two_candidate_spine()
    packet = PacketBuilder().build(spine, prose, PACKET_ID, GENERATED_AT)

    avery = packet.candidates[0]
    assert avery.headline == "headline c-avery"
    assert avery.recommendation == "reco c-avery"
    assert avery.aggregate_score == 3.6
    assert avery.score_scale == 4
    assert avery.rounds_completed == 3
    assert avery.rounds_total == 4
    assert avery.top_strengths == ["product sense"]
    assert avery.top_concerns == ["scale"]
    assert avery.verdict == "hire"
    assert avery.rank == 1


def test_score_scale_always_four_for_every_candidate():
    spine, prose = _two_candidate_spine()
    packet = PacketBuilder().build(spine, prose, PACKET_ID, GENERATED_AT)
    assert all(c.score_scale == 4 for c in packet.candidates)


def test_missing_prose_for_candidate_falls_back_to_empty_strings():
    spine, prose = _two_candidate_spine()
    prose.per_candidate.pop("c-blake")  # no prose for blake
    packet = PacketBuilder().build(spine, prose, PACKET_ID, GENERATED_AT)
    blake = packet.candidates[1]
    assert blake.headline == ""
    assert blake.recommendation == ""


# --------------------------------------------------------------------------- #
# decision_matrix: missing cell -> key OMITTED, winner_ids, ties
# --------------------------------------------------------------------------- #
def test_missing_cell_value_omits_candidate_key_not_zero():
    spine, prose = _two_candidate_spine()
    packet = PacketBuilder().build(spine, prose, PACKET_ID, GENERATED_AT)

    scale_row = next(r for r in packet.decision_matrix if r.dimension == "Platform Scale")
    # Blake's Platform Scale cell is None -> key absent, NOT 0.
    assert "c-blake" not in scale_row.scores
    assert scale_row.scores.get("c-blake") != 0
    assert scale_row.scores == {"c-avery": 2.5}


def test_decision_matrix_one_row_per_dimension_in_order():
    spine, prose = _two_candidate_spine()
    packet = PacketBuilder().build(spine, prose, PACKET_ID, GENERATED_AT)
    assert [r.dimension for r in packet.decision_matrix] == ["Product Sense", "Platform Scale"]


def test_winner_ids_is_max_score_candidate():
    spine, prose = _two_candidate_spine()
    packet = PacketBuilder().build(spine, prose, PACKET_ID, GENERATED_AT)
    ps_row = next(r for r in packet.decision_matrix if r.dimension == "Product Sense")
    # avery 4.0 > blake 3.0
    assert ps_row.winner_ids == ["c-avery"]


def test_winner_ids_includes_ties():
    dimensions = ["Product Sense"]
    a = _candidate("c-a", "Ann Adams", rank=1, cells=[_cell("Product Sense", 3.5, True)])
    b = _candidate("c-b", "Bob Brown", rank=2, cells=[_cell("Product Sense", 3.5, True)])
    spine = _spine([a, b], dimensions)
    prose = _prose(["c-a", "c-b"])
    packet = PacketBuilder().build(spine, prose, PACKET_ID, GENERATED_AT)
    row = packet.decision_matrix[0]
    assert set(row.winner_ids) == {"c-a", "c-b"}


def test_winner_ids_empty_when_row_has_no_scores():
    dimensions = ["Ghost Dimension"]
    a = _candidate("c-a", "Ann Adams", rank=1, cells=[_cell("Ghost Dimension", None, True)])
    spine = _spine([a], dimensions)
    prose = _prose(["c-a"])
    packet = PacketBuilder().build(spine, prose, PACKET_ID, GENERATED_AT)
    row = packet.decision_matrix[0]
    assert row.scores == {}
    assert row.winner_ids == []


def test_matrix_note_from_prose_with_fallback():
    spine, prose = _two_candidate_spine()
    prose.matrix_notes = {"Product Sense": "Avery leads clearly."}
    packet = PacketBuilder().build(spine, prose, PACKET_ID, GENERATED_AT)
    ps_row = next(r for r in packet.decision_matrix if r.dimension == "Product Sense")
    scale_row = next(r for r in packet.decision_matrix if r.dimension == "Platform Scale")
    assert ps_row.note == "Avery leads clearly."
    assert scale_row.note == ""  # absent -> fallback


# --------------------------------------------------------------------------- #
# BASELINE tier: round-decision matrix (rows = rounds, cells = ratings) — §3
# --------------------------------------------------------------------------- #
def _baseline_spine() -> tuple[DebriefSpine, ProseBundle]:
    """Two candidates over the same two rounds, no graph signal → baseline tier.
    Avery: Technical 4.0 / HM 3.25 ; Blake: Technical 2.5 / (no HM round)."""
    avery = _candidate("c-avery", "Avery Stone", rank=1, aggregate=3.6)
    avery.round_ratings = [
        RoundRating(round_id="r1", round_name="Technical", value=4.0),
        RoundRating(round_id="r2", round_name="Hiring Manager", value=3.25),
    ]
    blake = _candidate("c-blake", "Blake Rivera", rank=2, aggregate=2.5)
    blake.round_ratings = [RoundRating(round_id="r1", round_name="Technical", value=2.5)]
    spine = _spine([avery, blake], dimensions=[], enrichment_tier="baseline")
    return spine, _prose(["c-avery", "c-blake"])


def test_baseline_matrix_rows_are_rounds_with_rating_cells():
    spine, prose = _baseline_spine()
    packet = PacketBuilder().build(spine, prose, PACKET_ID, GENERATED_AT)

    # Rows are the union of rounds, first-seen order (Technical then Hiring Manager).
    assert [r.dimension for r in packet.decision_matrix] == ["Technical", "Hiring Manager"]

    tech = packet.decision_matrix[0]
    assert tech.scores == {"c-avery": 4.0, "c-blake": 2.5}
    assert tech.winner_ids == ["c-avery"]

    # Blake never took the Hiring Manager round → his key is OMITTED (em-dash).
    hm = packet.decision_matrix[1]
    assert hm.scores == {"c-avery": 3.25}
    assert "c-blake" not in hm.scores


def test_baseline_matrix_dedupes_round_columns_by_round_id():
    # Both candidates share round r1 → ONE 'Technical' row, not two.
    spine, prose = _baseline_spine()
    packet = PacketBuilder().build(spine, prose, PACKET_ID, GENERATED_AT)
    tech_rows = [r for r in packet.decision_matrix if r.dimension == "Technical"]
    assert len(tech_rows) == 1


def test_baseline_matrix_unique_labels_for_duplicate_round_names():
    # Two DISTINCT rounds that happen to share a display name get de-collided.
    a = _candidate("c-a", "Ann Adams", rank=1, aggregate=3.0)
    a.round_ratings = [
        RoundRating(round_id="r1", round_name="Panel", value=4.0),
        RoundRating(round_id="r2", round_name="Panel", value=2.5),
    ]
    spine = _spine([a], dimensions=[], enrichment_tier="baseline")
    packet = PacketBuilder().build(spine, _prose(["c-a"]), PACKET_ID, GENERATED_AT)
    labels = [r.dimension for r in packet.decision_matrix]
    assert labels == ["Panel", "Panel (2)"]


# --------------------------------------------------------------------------- #
# themes: label override from prose, keep tone/weight/evidence_count
# --------------------------------------------------------------------------- #
def test_theme_label_override_applied_keeps_other_fields():
    spine, prose = _two_candidate_spine()
    prose.theme_labels = {0: "Sharp strategic instincts"}  # override theme 0 only
    packet = PacketBuilder().build(spine, prose, PACKET_ID, GENERATED_AT)

    assert packet.themes[0].label == "Sharp strategic instincts"
    assert packet.themes[0].tone == "pos"
    assert packet.themes[0].weight == 0.9
    assert packet.themes[0].evidence_count == 3
    # theme 1 had no override -> original label kept.
    assert packet.themes[1].label == "Scale gap"


def test_theme_label_override_absent_keeps_original():
    spine, prose = _two_candidate_spine()
    packet = PacketBuilder().build(spine, prose, PACKET_ID, GENERATED_AT)
    assert packet.themes[0].label == "Strategic thinking"


# --------------------------------------------------------------------------- #
# initials / color: deterministic + stable
# --------------------------------------------------------------------------- #
def test_initials_two_words():
    spine, prose = _two_candidate_spine()
    packet = PacketBuilder().build(spine, prose, PACKET_ID, GENERATED_AT)
    assert packet.candidates[0].initials == "AS"  # Avery Stone
    assert packet.candidates[1].initials == "BR"  # Blake Rivera


def test_initials_single_word_takes_two_letters():
    dimensions = ["D1"]
    a = _candidate("c-a", "Cher", rank=1, cells=[_cell("D1", 3.0, True)])
    spine = _spine([a], dimensions)
    packet = PacketBuilder().build(spine, _prose(["c-a"]), PACKET_ID, GENERATED_AT)
    assert packet.candidates[0].initials == "CH"


def test_initials_empty_name_fallback():
    dimensions = ["D1"]
    a = _candidate("c-a", "   ", rank=1, cells=[_cell("D1", 3.0, True)])
    spine = _spine([a], dimensions)
    packet = PacketBuilder().build(spine, _prose(["c-a"]), PACKET_ID, GENERATED_AT)
    assert packet.candidates[0].initials == "?"


def test_color_is_valid_hex():
    spine, prose = _two_candidate_spine()
    packet = PacketBuilder().build(spine, prose, PACKET_ID, GENERATED_AT)
    for c in packet.candidates:
        assert c.color.startswith("#")
        assert len(c.color) == 7
        int(c.color[1:], 16)  # parses as hex


def test_color_stable_for_same_name_across_builds():
    spine, prose = _two_candidate_spine()
    p1 = PacketBuilder().build(spine, prose, PACKET_ID, GENERATED_AT)
    spine2, prose2 = _two_candidate_spine()
    p2 = PacketBuilder().build(spine2, prose2, PACKET_ID, GENERATED_AT)
    assert p1.candidates[0].color == p2.candidates[0].color
    assert p1.candidates[0].name == p2.candidates[0].name


def test_color_differs_for_different_names_generally():
    # Not a hard guarantee, but the curated palette should separate two common names.
    spine, prose = _two_candidate_spine()
    packet = PacketBuilder().build(spine, prose, PACKET_ID, GENERATED_AT)
    assert packet.candidates[0].color != packet.candidates[1].color


# --------------------------------------------------------------------------- #
# panel members + panelist join
# --------------------------------------------------------------------------- #
def test_panel_members_get_derived_initials_and_color():
    spine, prose = _two_candidate_spine()
    packet = PacketBuilder().build(spine, prose, PACKET_ID, GENERATED_AT)
    pm = packet.panel_members[0]
    assert pm.name == "Dana Lee"
    assert pm.initials == "DL"
    assert pm.color.startswith("#")


def test_panel_vote_panelist_matches_a_panel_member_name():
    spine, prose = _two_candidate_spine()
    packet = PacketBuilder().build(spine, prose, PACKET_ID, GENERATED_AT)
    member_names = {pm.name for pm in packet.panel_members}
    for c in packet.candidates:
        for vote in c.panel_votes:
            assert vote.panelist in member_names


# --------------------------------------------------------------------------- #
# top-level fields
# --------------------------------------------------------------------------- #
def test_top_level_fields_assembled():
    spine, prose = _two_candidate_spine()
    packet = PacketBuilder().build(spine, prose, PACKET_ID, GENERATED_AT)

    assert packet.id == PACKET_ID
    assert packet.requisition_id == "req-1"
    assert packet.role_title == "Senior Product Manager"
    assert packet.generated_at == GENERATED_AT
    assert packet.generated_by == "Scout debrief agent"
    assert packet.status == "fresh"
    assert packet.confidence == "high"
    assert packet.verdict == "hire"  # overall_verdict
    assert packet.headline_recommendation == "Recommend the top candidate."
    assert packet.source_stats.scorecards == 5
    assert packet.source_stats.transcripts == 4
    assert packet.risks == ["polished risk"]
    assert packet.next_steps[0].label == "Schedule offer call"


def test_title_and_subtitle_derived():
    spine, prose = _two_candidate_spine()
    packet = PacketBuilder().build(spine, prose, PACKET_ID, GENERATED_AT)
    assert "Senior Product Manager" in packet.title
    assert "2" in packet.subtitle  # 2 candidates


def test_subtitle_singular_for_one_candidate():
    dimensions = ["D1"]
    a = _candidate("c-a", "Ann Adams", rank=1, cells=[_cell("D1", 3.0, True)])
    spine = _spine([a], dimensions)
    packet = PacketBuilder().build(spine, _prose(["c-a"]), PACKET_ID, GENERATED_AT)
    assert "candidate" in packet.subtitle.lower()
    assert "candidates" not in packet.subtitle.lower()


def test_subtitle_carries_baseline_enrichment_tier():
    # Addendum §2: a Supabase-only (baseline) packet labels its subtitle.
    spine, prose = _two_candidate_spine()
    spine.enrichment_tier = "baseline"
    packet = PacketBuilder().build(spine, prose, PACKET_ID, GENERATED_AT)
    assert packet.subtitle == "Baseline · 2 candidates compared"


def test_subtitle_carries_graph_enriched_tier():
    spine, prose = _two_candidate_spine()
    spine.enrichment_tier = "graph_enriched"
    packet = PacketBuilder().build(spine, prose, PACKET_ID, GENERATED_AT)
    assert packet.subtitle == "Graph-enriched · 2 candidates compared"


def test_subtitle_graph_enriched_singular_candidate():
    a = _candidate("c-a", "Ann Adams", rank=1, cells=[_cell("D1", 3.0, True)])
    spine = _spine([a], ["D1"])
    spine.enrichment_tier = "graph_enriched"
    packet = PacketBuilder().build(spine, _prose(["c-a"]), PACKET_ID, GENERATED_AT)
    assert packet.subtitle == "Graph-enriched · 1 candidate compared"


# --------------------------------------------------------------------------- #
# enum validation (defensive)
# --------------------------------------------------------------------------- #
def test_invalid_overall_verdict_raises_clear_error():
    spine, prose = _two_candidate_spine()
    spine.overall_verdict = "definitely_hire"  # not in the §4 literal set
    with pytest.raises(ValueError):
        PacketBuilder().build(spine, prose, PACKET_ID, GENERATED_AT)


def test_invalid_confidence_raises_clear_error():
    spine, prose = _two_candidate_spine()
    spine.confidence = "very_high"
    with pytest.raises(ValueError):
        PacketBuilder().build(spine, prose, PACKET_ID, GENERATED_AT)


def test_invalid_candidate_verdict_raises_clear_error():
    spine, prose = _two_candidate_spine()
    spine.candidates[0].verdict = "super_hire"
    with pytest.raises(ValueError):
        PacketBuilder().build(spine, prose, PACKET_ID, GENERATED_AT)


def test_invalid_theme_tone_raises_clear_error():
    spine, prose = _two_candidate_spine()
    # Bypass DebriefTheme literal validation by swapping in a bad tone post-build.
    object.__setattr__(spine.themes[0], "tone", "bad_tone")
    with pytest.raises(ValueError):
        PacketBuilder().build(spine, prose, PACKET_ID, GENERATED_AT)


def test_invalid_panel_vote_raises_clear_error():
    spine, prose = _two_candidate_spine()
    object.__setattr__(spine.candidates[0].panel_votes[0], "vote", "absolutely")
    with pytest.raises(ValueError):
        PacketBuilder().build(spine, prose, PACKET_ID, GENERATED_AT)


# --------------------------------------------------------------------------- #
# whole-packet validity
# --------------------------------------------------------------------------- #
def test_full_packet_is_model_validate_clean():
    spine, prose = _two_candidate_spine()
    prose.matrix_notes = {"Product Sense": "Avery leads."}
    prose.theme_labels = {0: "Strategic"}
    packet = PacketBuilder().build(spine, prose, PACKET_ID, GENERATED_AT)

    # Round-trips through Pydantic untouched (already a DebriefPacket, but re-validate
    # the serialized form to guarantee the emitted shape is contract-clean).
    reparsed = DebriefPacket.model_validate(packet.model_dump())
    assert reparsed == packet


def test_empty_candidate_set_produces_valid_packet():
    spine = _spine([], ["D1"], overall_verdict="mixed")
    packet = PacketBuilder().build(spine, ProseBundle(), PACKET_ID, GENERATED_AT)
    assert packet.candidates == []
    assert packet.decision_matrix[0].winner_ids == []
    DebriefPacket.model_validate(packet.model_dump())
