"""Unit tests for build_system_prompt — a pure packet -> system-string renderer.

Asserts the prompt carries every section the runner needs to ground the model
(role, candidate one-liners, decision-matrix dimensions, themes, risks) plus the
non-negotiable guardrails (never invent; cite the packet; to act, call a propose_*
tool; you cannot execute; do not coach). No I/O is touched.
"""

from app.services.debrief_chat.prompt import build_system_prompt


def _packet():
    return {
        "role_title": "Senior Product Manager",
        "candidates": [
            {
                "candidate_id": "cand-a",
                "name": "Ada Lovelace",
                "rank": 1,
                "verdict": "strong_hire",
                "aggregate_score": 3.6,
                "score_scale": 4,
                "headline": "Edges on systems thinking",
            },
            {
                "candidate_id": "cand-b",
                "name": "Bob Stone",
                "rank": 2,
                "verdict": "hire",
                "aggregate_score": 3.1,
                "score_scale": 4,
                "headline": "Strong comms, lighter on depth",
            },
        ],
        "decision_matrix": [
            {
                "dimension": "Systems Design",
                "scores": {"cand-a": 4.0, "cand-b": 2.5},
                "winner_ids": ["cand-a"],
            },
            {"dimension": "Communication", "scores": {}, "winner_ids": []},
        ],
        "themes": [
            {"label": "Cross-functional collaboration", "tone": "pos", "weight": 0.8},
        ],
        "risks": ["Limited pricing experience"],
        "next_steps": [{"label": "Schedule the final loop", "owner": "Jess"}],
    }


def test_prompt_contains_role_title():
    out = build_system_prompt(_packet())
    assert "Senior Product Manager" in out


def test_prompt_contains_each_candidate_one_liner():
    out = build_system_prompt(_packet())
    for name in ("Ada Lovelace", "Bob Stone"):
        assert name in out
    # rank, verdict and aggregate score appear for the candidates
    assert "strong_hire" in out
    assert "hire" in out
    assert "3.6" in out
    assert "3.1" in out


def test_prompt_exposes_candidate_ids_for_tool_calls():
    """The model needs each candidate's REAL id to call read/propose tools; the
    prompt must surface it verbatim and instruct the model to use it.

    Regression: without ids in the prompt the model guessed name-slugs and every
    tool call hit the 'candidate not in this debrief' membership guard, so it asked
    the recruiter for ids instead of answering.
    """
    out = build_system_prompt(_packet())
    assert "cand-a" in out
    assert "cand-b" in out
    assert "[id:" in out
    lowered = out.lower()
    assert "exact id" in lowered  # instruction to pass the id verbatim
    assert "never ask the recruiter for ids" in lowered


def test_prompt_contains_decision_matrix_dimensions():
    out = build_system_prompt(_packet())
    assert "Systems Design" in out
    assert "Communication" in out


def test_prompt_contains_themes_and_risks():
    out = build_system_prompt(_packet())
    assert "Cross-functional collaboration" in out
    assert "Limited pricing experience" in out


def test_prompt_contains_guardrails():
    out = build_system_prompt(_packet())
    lowered = out.lower()
    assert "never invent" in lowered or "do not invent" in lowered
    assert "propose_" in out  # must call a propose_* tool to act
    assert "cannot" in lowered  # you cannot execute actions yourself
    assert "coach" in lowered  # do not coach


def test_prompt_does_not_dump_raw_json():
    """Candidates are summarized as lines, not dumped as raw JSON blobs."""
    out = build_system_prompt(_packet())
    assert "candidate_ids" not in out
    assert '"aggregate_score"' not in out


def test_prompt_contains_matrix_cell_scores():
    """The model must see per-dimension scores (with names, compact floats, and
    the leader) so 'why is X 2.5 on Y' is answerable without a tool call."""
    out = build_system_prompt(_packet())
    assert "Systems Design: Ada Lovelace 4, Bob Stone 2.5" in out
    assert "leads: Ada Lovelace" in out


def test_prompt_contains_next_steps():
    out = build_system_prompt(_packet())
    assert "Schedule the final loop" in out


def test_prompt_pins_the_complete_capability_set_and_out_of_scope_rule():
    """The agent serves a FIXED set of capabilities; anything else must be
    declined in prose (no tool call) with a pointer to the closest capability.
    Regression: an out-of-scope question ('what is the learning from this
    loop?') made the model fire propose_open_scheduler with no text."""
    out = build_system_prompt(_packet())
    lowered = out.lower()
    assert "complete set" in lowered
    assert "out-of-scope" in lowered
    assert "do not call any action tool" in lowered
    # Option enumerations render as tappable pills, never prose lists.
    assert "propose_quick_replies" in out
    assert "never write a numbered" in lowered
    # Reflection/learning asks route to the insight tool, not a random one.
    assert "what did we learn" in lowered
    # And no turn may be a bare tool call (the empty-bubble regression).
    assert "never\n  reply with a bare tool call" in lowered or "bare tool call" in lowered


def test_prompt_routes_scheduling_to_the_scheduler_ui():
    """Scheduling is picked in the app's scheduler UI (the candidate's pipeline
    packet) — the guardrails must route the intent to propose_open_scheduler and
    forbid collecting dates/times/timezones in chat."""
    out = build_system_prompt(_packet())
    assert "propose_open_scheduler" in out
    lowered = out.lower()
    assert "never collect dates" in lowered


def test_prompt_routes_new_debrief_intent_to_the_workflow_tool():
    """'Debrief another round/role' is a workflow restart, not an add-round —
    the guardrails must route that intent to propose_new_debrief."""
    out = build_system_prompt(_packet())
    assert "propose_new_debrief" in out
    assert "debrief another round" in out.lower()


def test_prompt_contains_response_style_contract():
    """Replies render in a narrow chat bubble — the style contract must forbid
    headings/emoji/process narration and cap the default length."""
    out = build_system_prompt(_packet())
    lowered = out.lower()
    assert "response style" in lowered
    assert "lead with the answer" in lowered
    assert "never use headings" in lowered
    assert "emoji" in lowered
    assert "do not narrate" in lowered


def test_prompt_handles_empty_packet():
    """A sparse packet (no candidates/themes/risks) renders without raising."""
    out = build_system_prompt({"role_title": "Role", "candidates": []})
    assert "Role" in out
    assert isinstance(out, str)


def test_prompt_score_uses_snapshot_scale():
    """The score denominator comes from the snapshot's own score_scale, not a
    hardcoded /4. With scale==4 the output is unchanged (3.6/4)."""
    out = build_system_prompt(_packet())
    assert "3.6/4" in out

    scaled = {
        "role_title": "Role",
        "candidates": [
            {
                "candidate_id": "cand-x",
                "name": "Xena",
                "rank": 1,
                "verdict": "hire",
                "aggregate_score": 7.5,
                "score_scale": 10,
                "headline": "",
            }
        ],
    }
    assert "7.5/10" in build_system_prompt(scaled)
