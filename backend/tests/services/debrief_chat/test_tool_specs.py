"""Unit tests for the debrief chat tool specs — OpenAI function shape.

Eleven tools: three grounded read tools the runner executes in-loop, and eight
propose_* tools the runner intercepts without executing. The assertions below are
the ones that were here before the phase-3 shape change, re-pointed at
["function"]["parameters"]; nothing about the schemas themselves changed, which
is proven separately by parsing both revisions (see the plan's Task 3 Step 6).
"""

from llm_core.emulation import validate_tool_shape

from app.services.debrief_chat.tool_specs import PROPOSE_TOOL_SPECS, READ_TOOL_SPECS


def _fn(spec: dict) -> dict:
    return spec["function"]


def _by_name():
    return {_fn(spec)["name"]: spec for spec in READ_TOOL_SPECS}


def _propose_by_name():
    return {_fn(spec)["name"]: spec for spec in PROPOSE_TOOL_SPECS}


def test_read_tools_present():
    names = {_fn(spec)["name"] for spec in READ_TOOL_SPECS}
    assert names == {
        "get_candidate_detail",
        "get_transcript_evidence",
        "get_graph_standing",
    }


def test_every_spec_has_description_and_object_schema():
    for spec in READ_TOOL_SPECS:
        assert _fn(spec)["description"].strip()
        schema = _fn(spec)["parameters"]
        assert schema["type"] == "object"
        assert isinstance(schema["properties"], dict)


def test_get_candidate_detail_requires_candidate_id():
    spec = _by_name()["get_candidate_detail"]
    assert _fn(spec)["parameters"]["required"] == ["candidate_id"]
    assert "candidate_id" in _fn(spec)["parameters"]["properties"]


def test_get_transcript_evidence_requires_candidate_id_and_topic():
    spec = _by_name()["get_transcript_evidence"]
    assert set(_fn(spec)["parameters"]["required"]) == {"candidate_id", "topic"}
    props = _fn(spec)["parameters"]["properties"]
    assert "candidate_id" in props
    assert "topic" in props


def test_get_graph_standing_has_no_required_fields():
    spec = _by_name()["get_graph_standing"]
    assert _fn(spec)["parameters"].get("required", []) == []
    props = _fn(spec)["parameters"]["properties"]
    assert "candidate_id" in props
    assert "competency" in props


def test_no_propose_tools_in_read_specs():
    names = {_fn(spec)["name"] for spec in READ_TOOL_SPECS}
    assert not any(n.startswith("propose_") for n in names)


# ---------------------------------------------------------------------------
# Propose tool specs (Phase 2 — 5 action tools, log_insight is Phase 3)
# ---------------------------------------------------------------------------
def test_propose_tools_present():
    names = {_fn(spec)["name"] for spec in PROPOSE_TOOL_SPECS}
    assert names == {
        "propose_add_round",
        "propose_open_scheduler",
        "propose_request_feedback",
        "propose_record_decision",
        "propose_advance_reject",
        "propose_log_insight",
        "propose_new_debrief",
        "propose_quick_replies",
    }


def test_log_insight_registered():
    names = {_fn(spec)["name"] for spec in PROPOSE_TOOL_SPECS}
    assert "propose_log_insight" in names


def test_every_propose_spec_requires_summary_rationale():
    # All ACTION propose tools require summary + rationale; every kind except
    # log_insight also requires candidate_ids (log_insight allows an org-level
    # insight). The UI intents execute nothing and carry minimal inputs:
    # propose_new_debrief restarts the picker (just `scope`);
    # propose_open_scheduler opens a candidate's packet/scheduler (just ids);
    # propose_quick_replies attaches tappable pills (just `options`).
    for spec in PROPOSE_TOOL_SPECS:
        schema = _fn(spec)["parameters"]
        assert schema["type"] == "object"
        required = set(schema["required"])
        if _fn(spec)["name"] == "propose_new_debrief":
            assert required == {"scope"}
            continue
        if _fn(spec)["name"] == "propose_open_scheduler":
            assert required == {"candidate_ids"}
            continue
        if _fn(spec)["name"] == "propose_quick_replies":
            assert required == {"options"}
            continue
        assert {"summary", "rationale"} <= required
        props = schema["properties"]
        assert props["candidate_ids"]["type"] == "array"
        assert props["candidate_ids"]["items"]["type"] == "string"
        if _fn(spec)["name"] != "propose_log_insight":
            assert "candidate_ids" in required
        else:
            assert "candidate_ids" not in required


def test_propose_new_debrief_fields():
    spec = _propose_by_name()["propose_new_debrief"]
    schema = _fn(spec)["parameters"]
    assert set(schema["required"]) == {"scope"}
    assert set(schema["properties"]["scope"]["enum"]) == {"same_role", "different_role"}
    # The runner intercepts it like every propose tool — never executes it.
    lowered = _fn(spec)["description"].lower()
    assert "picker" in lowered


def test_propose_log_insight_fields():
    spec = _propose_by_name()["propose_log_insight"]
    schema = _fn(spec)["parameters"]
    required = set(schema["required"])
    assert {"summary", "rationale", "insight_kind", "text"} == required
    props = schema["properties"]
    assert set(props["insight_kind"]["enum"]) == {
        "decision_rationale",
        "recruiter_preference",
    }
    assert "text" in props
    assert props["triplet"]["type"] == "object"
    assert set(props["triplet"]["properties"]) == {"subject", "predicate", "object"}


def test_every_propose_description_says_not_executed():
    # The UI intents (new_debrief, open_scheduler) are exempt: the FE acts on
    # them directly — both just open app UI (picker / scheduler), nothing is
    # written, so their descriptions promise the UI, not a confirm.
    for spec in PROPOSE_TOOL_SPECS:
        if _fn(spec)["name"] in (
            "propose_new_debrief",
            "propose_open_scheduler",
            "propose_quick_replies",
        ):
            continue
        desc = _fn(spec)["description"].lower()
        assert "propose" in desc
        assert "confirm" in desc


def test_propose_add_round_kind_specific_fields():
    spec = _propose_by_name()["propose_add_round"]
    props = _fn(spec)["parameters"]["properties"]
    assert "name" in props
    assert "name" in _fn(spec)["parameters"]["required"]
    for opt in ("category", "duration_minutes", "skills"):
        assert opt in props


def test_propose_open_scheduler_fields():
    spec = _propose_by_name()["propose_open_scheduler"]
    schema = _fn(spec)["parameters"]
    assert set(schema["required"]) == {"candidate_ids"}
    assert "round_ref" in schema["properties"]
    lowered = _fn(spec)["description"].lower()
    # Scheduling happens in the app UI — the tool must forbid chat date-collection.
    assert "schedul" in lowered
    assert "never" in lowered


def test_propose_request_feedback_requires_interviewer_email():
    spec = _propose_by_name()["propose_request_feedback"]
    schema = _fn(spec)["parameters"]
    assert "interviewer_email" in schema["required"]
    assert "round_ref" in schema["properties"]
    assert "interviewer_name" in schema["properties"]


def test_propose_record_decision_verdict_enum():
    spec = _propose_by_name()["propose_record_decision"]
    schema = _fn(spec)["parameters"]
    assert "verdict" in schema["required"]
    assert set(schema["properties"]["verdict"]["enum"]) == {
        "strong_hire",
        "hire",
        "no_hire",
        "strong_no_hire",
    }
    assert set(schema["properties"]["status"]["enum"]) == {
        "active",
        "hired",
        "rejected",
        "withdrawn",
    }


def test_propose_advance_reject_outcome_enum():
    spec = _propose_by_name()["propose_advance_reject"]
    schema = _fn(spec)["parameters"]
    assert "outcome" in schema["required"]
    assert "round_ref" in schema["properties"]
    assert set(schema["properties"]["outcome"]["enum"]) == {"advance", "reject", "hold"}


def test_propose_quick_replies_fields():
    spec = _propose_by_name()["propose_quick_replies"]
    schema = _fn(spec)["parameters"]
    assert set(schema["required"]) == {"options"}
    assert schema["properties"]["options"]["items"]["type"] == "string"
    lowered = _fn(spec)["description"].lower()
    # Pills replace prose enumerations — the description must say so.
    assert "instead of" in lowered


def test_every_spec_is_accepted_by_llm_core():
    """The gateway path REJECTS Anthropic-shaped specs rather than translating
    them, so a spec that survived the phase-3 envelope change in the old shape
    would fail as an opaque provider 400 at request time. validate_tool_shape is
    the same function llm_core runs before dispatch."""
    entries = validate_tool_shape(READ_TOOL_SPECS + PROPOSE_TOOL_SPECS)
    assert len(entries) == 11
    assert all(name for name, _description, _schema in entries)
