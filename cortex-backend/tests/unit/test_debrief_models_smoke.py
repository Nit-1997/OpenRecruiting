"""Smoke test for the debrief skill foundation.

Asserts the whole `src.service.debrief` package imports cleanly (skeletons +
orchestrator + controller wire-up) and that a hand-built `DebriefPacket` fixture
round-trips through Pydantic. Per-class behavior tests come later (plan Phase 1).
"""

import pytest
from pydantic import ValidationError

# Importing the package pulls in every skeleton class + the orchestrator +
# controller (via main wiring imports), so this also guards against import-time
# syntax/wiring errors across the foundation.
import src.service.debrief  # noqa: F401
from src.controller.debrief_controller import router, set_debrief_service  # noqa: F401
from src.model.debrief import (
    DebriefCandidateSnapshot,
    DebriefDecisionRow,
    DebriefPacket,
    DebriefPanelVote,
    DebriefRequest,
    DebriefSourceStats,
    DebriefTheme,
    NextStep,
    PanelMember,
    ProseBundle,
    ScaffoldData,
    DebriefSpine,
)


def _fixture_packet_dict() -> dict:
    return {
        "id": "11111111-1111-1111-1111-111111111111",
        "requisition_id": "22222222-2222-2222-2222-222222222222",
        "role_title": "Senior Product Manager",
        "title": "PM Finalists Debrief",
        "subtitle": "2 candidates compared",
        "generated_at": "2026-06-07T12:00:00+00:00",
        "generated_by": "Scout debrief agent",
        "status": "fresh",
        "confidence": "high",
        "verdict": "hire",
        "headline_recommendation": "Recommend Avery over Blake on stronger product sense.",
        "panel_members": [
            {"name": "Dana Lee", "role": "Hiring Manager", "initials": "DL", "color": "#2563eb"},
        ],
        "candidates": [
            {
                "candidate_id": "c-avery",
                "name": "Avery Stone",
                "initials": "AS",
                "color": "#16a34a",
                "rank": 1,
                "verdict": "hire",
                "headline": "Strong product instincts, light on scale.",
                "aggregate_score": 3.6,
                "score_scale": 4,
                "rounds_completed": 3,
                "rounds_total": 4,
                "top_strengths": ["product sense", "stakeholder management"],
                "top_concerns": ["limited platform scale"],
                "recommendation": "Advance to offer.",
                "panel_votes": [
                    {
                        "panelist": "Dana Lee",
                        "panelist_role": "Hiring Manager",
                        "vote": "yes",
                        "rationale": "Clear strategic thinking.",
                    }
                ],
            },
            {
                "candidate_id": "c-blake",
                "name": "Blake Rivera",
                "initials": "BR",
                "color": "#dc2626",
                "rank": 2,
                "verdict": "mixed",
                "headline": "Solid execution, weaker vision.",
                "aggregate_score": 2.9,
                "score_scale": 4,
                "rounds_completed": 2,
                "rounds_total": 4,
                "top_strengths": ["execution"],
                "top_concerns": ["product vision"],
                "recommendation": "Hold pending more signal.",
                "panel_votes": [],
            },
        ],
        "source_stats": {"scorecards": 5, "transcripts": 4},
        "themes": [
            {"label": "Strategic thinking", "tone": "pos", "weight": 0.9, "evidence_count": 3},
            {"label": "Scale experience gap", "tone": "neg", "weight": 0.4, "evidence_count": 1},
        ],
        "decision_matrix": [
            {
                "dimension": "Product Sense",
                "scores": {"c-avery": 4.0, "c-blake": 3.0},
                "winner_ids": ["c-avery"],
                "note": "Avery leads clearly.",
            },
            {
                # c-blake omitted -> renders em-dash (no evidence). Must NOT be 0.
                "dimension": "Platform Scale",
                "scores": {"c-avery": 2.5},
                "winner_ids": ["c-avery"],
                "note": "Sparse evidence for Blake.",
            },
        ],
        "risks": ["Blake has only 2 of 4 rounds complete."],
        "next_steps": [
            {"label": "Schedule offer call with Avery", "owner": "Dana Lee", "due": "2026-06-10"},
        ],
    }


def test_packet_roundtrips():
    data = _fixture_packet_dict()
    packet = DebriefPacket.model_validate(data)

    assert packet.status == "fresh"
    assert packet.confidence == "high"
    assert packet.candidates[0].rank == 1
    assert packet.candidates[0].score_scale == 4
    # Em-dash semantics: omitted candidate key, never a 0.
    assert "c-blake" not in packet.decision_matrix[1].scores

    dumped = packet.model_dump()
    reparsed = DebriefPacket.model_validate(dumped)
    assert reparsed == packet


def test_invalid_verdict_enum_raises():
    data = _fixture_packet_dict()
    data["verdict"] = "definitely_hire"  # not in the FE literal set
    with pytest.raises(ValidationError):
        DebriefPacket.model_validate(data)


def test_invalid_vote_enum_raises():
    data = _fixture_packet_dict()
    data["candidates"][0]["panel_votes"][0]["vote"] = "absolutely"
    with pytest.raises(ValidationError):
        DebriefPacket.model_validate(data)


def test_request_model_requires_candidate_ids():
    with pytest.raises(ValidationError):
        DebriefRequest(org_id="o", requisition_id="r", candidate_ids=[])

    req = DebriefRequest(org_id="o", requisition_id="r", candidate_ids=["c1"])
    assert req.candidate_ids == ["c1"]


def test_spine_dataclasses_instantiable():
    # The internal spine + prose bundle construct without error (defaults wired).
    scaffold = ScaffoldData(org_id="o", requisition_id="r", role_title="PM")
    spine = DebriefSpine(org_id="o", requisition_id="r", role_title="PM")
    bundle = ProseBundle()
    assert scaffold.scorecard_count == 0
    assert spine.confidence == "medium"
    assert bundle.per_candidate == {}


def test_subcomponent_models_construct():
    PanelMember(name="A", role="HM", initials="A", color="#000")
    DebriefPanelVote(panelist="A", panelist_role="HM", vote="strong_yes")
    DebriefTheme(label="t", tone="neu", weight=0.5, evidence_count=2)
    DebriefDecisionRow(dimension="d", scores={"c": 3.0}, winner_ids=["c"], note="n")
    DebriefSourceStats(scorecards=1, transcripts=1)
    NextStep(label="do x")
    DebriefCandidateSnapshot(
        candidate_id="c",
        name="n",
        initials="N",
        color="#000",
        rank=1,
        verdict="strong_hire",
        headline="h",
        aggregate_score=4.0,
        rounds_completed=1,
        rounds_total=1,
        recommendation="r",
    )
