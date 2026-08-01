"""Unit tests for the debrief-action contract (Phase 2).

`ProposedAction` is the uniform shape every propose_* tool emits and the
`/actions` endpoint consumes. `build_proposed_action(tool_name, args)` maps a
propose tool call -> a validated ProposedAction, packing the kind-specific fields
into `params`. Unknown tool names raise.
"""

import pytest

from app.services.debrief_chat.contracts import (
    ActionKind,
    ProposedAction,
    build_proposed_action,
)


def test_action_kind_members():
    assert {k.value for k in ActionKind} == {
        "add_round",
        "request_feedback",
        "record_decision",
        "advance_reject",
        "log_insight",
    }


def test_proposed_action_defaults():
    action = ProposedAction(kind=ActionKind.record_decision, summary="s", rationale="r")
    assert action.candidate_ids == []
    assert action.round_ref is None
    assert action.params == {}


def test_build_add_round_packs_params():
    action = build_proposed_action(
        "propose_add_round",
        {
            "candidate_ids": ["c1"],
            "summary": "Add a system-design round for Ada",
            "rationale": "Ada's depth is unproven.",
            "name": "System Design",
            "category": "technical",
            "duration_minutes": 60,
            "skills": ["architecture"],
        },
    )
    assert action.kind == ActionKind.add_round
    assert action.candidate_ids == ["c1"]
    assert action.round_ref is None
    assert action.summary == "Add a system-design round for Ada"
    assert action.rationale == "Ada's depth is unproven."
    assert action.params == {
        "name": "System Design",
        "category": "technical",
        "duration_minutes": 60,
        "skills": ["architecture"],
    }


def test_build_schedule_round_rejected_as_retired():
    # schedule_round was retired (scheduling is a FE-handled UI intent that opens
    # the candidate's pipeline packet) — /actions must reject it like any unknown.
    with pytest.raises(ValueError):
        build_proposed_action(
            "propose_schedule_round",
            {"candidate_ids": ["c1"], "summary": "s", "rationale": "r"},
        )


def test_build_request_feedback_params():
    action = build_proposed_action(
        "propose_request_feedback",
        {
            "candidate_ids": ["c1"],
            "round_ref": "abc-round-id",
            "summary": "Ask Bob for feedback",
            "rationale": "Round done, no feedback yet.",
            "interviewer_email": "bob@x.com",
            "interviewer_name": "Bob",
        },
    )
    assert action.kind == ActionKind.request_feedback
    assert action.round_ref == "abc-round-id"
    assert action.params == {
        "interviewer_email": "bob@x.com",
        "interviewer_name": "Bob",
    }


def test_build_record_decision_params():
    action = build_proposed_action(
        "propose_record_decision",
        {
            "candidate_ids": ["c1"],
            "summary": "Hire Ada",
            "rationale": "Strongest on system design.",
            "verdict": "strong_hire",
            "status": "hired",
        },
    )
    assert action.kind == ActionKind.record_decision
    assert action.params == {"verdict": "strong_hire", "status": "hired"}


def test_build_advance_reject_params():
    action = build_proposed_action(
        "propose_advance_reject",
        {
            "candidate_ids": ["c2"],
            "round_ref": "Onsite",
            "summary": "Reject Bob",
            "rationale": "Weak on comms.",
            "outcome": "reject",
        },
    )
    assert action.kind == ActionKind.advance_reject
    assert action.round_ref == "Onsite"
    assert action.params == {"outcome": "reject"}


def test_build_log_insight_packs_params():
    action = build_proposed_action(
        "propose_log_insight",
        {
            "candidate_ids": ["c1"],
            "summary": "Log why Ada won",
            "rationale": "Durable signal worth compounding.",
            "insight_kind": "decision_rationale",
            "text": "Ada won on system-design depth.",
        },
    )
    assert action.kind == ActionKind.log_insight
    assert action.candidate_ids == ["c1"]
    assert action.params == {
        "insight_kind": "decision_rationale",
        "text": "Ada won on system-design depth.",
    }


def test_build_log_insight_allows_empty_candidate_ids():
    # An org/requisition-level insight has no candidate.
    action = build_proposed_action(
        "propose_log_insight",
        {
            "summary": "Team weights system design",
            "rationale": "Recurring theme across rounds.",
            "insight_kind": "recruiter_preference",
            "text": "This team weights system design over speed.",
            "triplet": {"subject": "PM", "predicate": "values", "object": "system design"},
        },
    )
    assert action.candidate_ids == []
    assert action.params["insight_kind"] == "recruiter_preference"
    assert action.params["triplet"] == {
        "subject": "PM",
        "predicate": "values",
        "object": "system design",
    }


def test_build_unknown_tool_name_raises():
    with pytest.raises(ValueError):
        build_proposed_action("propose_teleport", {"summary": "s", "rationale": "r"})
    with pytest.raises(ValueError):
        build_proposed_action("get_candidate_detail", {})


def test_build_missing_summary_or_rationale_raises():
    # ProposedAction requires summary + rationale; the mapper surfaces that as a
    # ValueError (pydantic ValidationError is a ValueError subclass).
    with pytest.raises(ValueError):
        build_proposed_action("propose_add_round", {"candidate_ids": ["c1"]})
