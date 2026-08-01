"""Unit tests for READ_TOOL_SPECS — the Anthropic read-tool definitions.

Asserts the three read tools exist with valid object input_schemas and the
required-field contract each tool's dispatcher relies on. Propose tools are a
later phase and intentionally absent here.
"""

from app.services.debrief_chat.tool_specs import PROPOSE_TOOL_SPECS, READ_TOOL_SPECS


def _by_name():
    return {spec["name"]: spec for spec in READ_TOOL_SPECS}


def _propose_by_name():
    return {spec["name"]: spec for spec in PROPOSE_TOOL_SPECS}


def test_read_tools_present():
    names = {spec["name"] for spec in READ_TOOL_SPECS}
    assert names == {
        "get_candidate_detail",
        "get_transcript_evidence",
        "get_graph_standing",
    }


def test_every_spec_has_description_and_object_schema():
    for spec in READ_TOOL_SPECS:
        assert spec["description"].strip()
        schema = spec["input_schema"]
        assert schema["type"] == "object"
        assert isinstance(schema["properties"], dict)


def test_get_candidate_detail_requires_candidate_id():
    spec = _by_name()["get_candidate_detail"]
    assert spec["input_schema"]["required"] == ["candidate_id"]
    assert "candidate_id" in spec["input_schema"]["properties"]


def test_get_transcript_evidence_requires_candidate_id_and_topic():
    spec = _by_name()["get_transcript_evidence"]
    assert set(spec["input_schema"]["required"]) == {"candidate_id", "topic"}
    props = spec["input_schema"]["properties"]
    assert "candidate_id" in props
    assert "topic" in props


def test_get_graph_standing_has_no_required_fields():
    spec = _by_name()["get_graph_standing"]
    assert spec["input_schema"].get("required", []) == []
    props = spec["input_schema"]["properties"]
    assert "candidate_id" in props
    assert "competency" in props


def test_no_propose_tools_in_read_specs():
    names = {spec["name"] for spec in READ_TOOL_SPECS}
    assert not any(n.startswith("propose_") for n in names)


# ---------------------------------------------------------------------------
# Propose tool specs (Phase 2 — 5 action tools, log_insight is Phase 3)
# ---------------------------------------------------------------------------
def test_propose_tools_present():
    names = {spec["name"] for spec in PROPOSE_TOOL_SPECS}
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
    names = {spec["name"] for spec in PROPOSE_TOOL_SPECS}
    assert "propose_log_insight" in names


def test_every_propose_spec_requires_summary_rationale():
    # All ACTION propose tools require summary + rationale; every kind except
    # log_insight also requires candidate_ids (log_insight allows an org-level
    # insight). The UI intents execute nothing and carry minimal inputs:
    # propose_new_debrief restarts the picker (just `scope`);
    # propose_open_scheduler opens a candidate's packet/scheduler (just ids);
    # propose_quick_replies attaches tappable pills (just `options`).
    for spec in PROPOSE_TOOL_SPECS:
        schema = spec["input_schema"]
        assert schema["type"] == "object"
        required = set(schema["required"])
        if spec["name"] == "propose_new_debrief":
            assert required == {"scope"}
            continue
        if spec["name"] == "propose_open_scheduler":
            assert required == {"candidate_ids"}
            continue
        if spec["name"] == "propose_quick_replies":
            assert required == {"options"}
            continue
        assert {"summary", "rationale"} <= required
        props = schema["properties"]
        assert props["candidate_ids"]["type"] == "array"
        assert props["candidate_ids"]["items"]["type"] == "string"
        if spec["name"] != "propose_log_insight":
            assert "candidate_ids" in required
        else:
            assert "candidate_ids" not in required


def test_propose_new_debrief_fields():
    spec = _propose_by_name()["propose_new_debrief"]
    schema = spec["input_schema"]
    assert set(schema["required"]) == {"scope"}
    assert set(schema["properties"]["scope"]["enum"]) == {"same_role", "different_role"}
    # The runner intercepts it like every propose tool — never executes it.
    lowered = spec["description"].lower()
    assert "picker" in lowered


def test_propose_log_insight_fields():
    spec = _propose_by_name()["propose_log_insight"]
    schema = spec["input_schema"]
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
        if spec["name"] in (
            "propose_new_debrief",
            "propose_open_scheduler",
            "propose_quick_replies",
        ):
            continue
        desc = spec["description"].lower()
        assert "propose" in desc
        assert "confirm" in desc


def test_propose_add_round_kind_specific_fields():
    spec = _propose_by_name()["propose_add_round"]
    props = spec["input_schema"]["properties"]
    assert "name" in props
    assert "name" in spec["input_schema"]["required"]
    for opt in ("category", "duration_minutes", "skills"):
        assert opt in props


def test_propose_open_scheduler_fields():
    spec = _propose_by_name()["propose_open_scheduler"]
    schema = spec["input_schema"]
    assert set(schema["required"]) == {"candidate_ids"}
    assert "round_ref" in schema["properties"]
    lowered = spec["description"].lower()
    # Scheduling happens in the app UI — the tool must forbid chat date-collection.
    assert "schedul" in lowered
    assert "never" in lowered


def test_propose_request_feedback_requires_interviewer_email():
    spec = _propose_by_name()["propose_request_feedback"]
    schema = spec["input_schema"]
    assert "interviewer_email" in schema["required"]
    assert "round_ref" in schema["properties"]
    assert "interviewer_name" in schema["properties"]


def test_propose_record_decision_verdict_enum():
    spec = _propose_by_name()["propose_record_decision"]
    schema = spec["input_schema"]
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
    schema = spec["input_schema"]
    assert "outcome" in schema["required"]
    assert "round_ref" in schema["properties"]
    assert set(schema["properties"]["outcome"]["enum"]) == {"advance", "reject", "hold"}


def test_propose_quick_replies_fields():
    spec = _propose_by_name()["propose_quick_replies"]
    schema = spec["input_schema"]
    assert set(schema["required"]) == {"options"}
    assert schema["properties"]["options"]["items"]["type"] == "string"
    lowered = spec["description"].lower()
    # Pills replace prose enumerations — the description must say so.
    assert "instead of" in lowered
