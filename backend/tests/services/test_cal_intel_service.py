"""BE-T2 characterization tests for calendar_intelligence_service pure functions.

These pin CURRENT behavior of the rich pure-function layer (title/name
extraction + fuzzy matching, timezone coercion, requisition filtering /
truncation "never silently pick" logic, confidence tiers, Block Kit builders)
so a later decomposition refactor cannot silently change behavior.

All outputs were captured by running the production functions and asserting the
observed result. Comments tagged CHARACTERIZED note surprising-but-current
behavior that an unaware refactor might "fix" — these assert the status quo.

No production code is modified by this file.
"""

from datetime import datetime, timezone

import pytest

import app.services.calendar_intelligence_service as s


# ---------------------------------------------------------------------------
# transition_detection_status — state machine guard
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "current,new",
    [
        ("detected", "notified"),
        ("notified", "awaiting_role"),
        ("notified", "confirmed"),
        ("awaiting_role", "awaiting_round"),
        ("awaiting_round", "confirmed"),
        ("awaiting_confirm", "confirmed"),
        ("confirming", "confirmed"),
        ("confirmed", "undone"),
        ("orphan_no_response", "notified"),
        ("orphan_role", "awaiting_role"),
        ("orphan_round", "confirmed"),
        ("orphan_confirm", "dismissed"),
    ],
)
def test_transition_valid(current, new):
    assert s.transition_detection_status(current, new) == new


@pytest.mark.parametrize(
    "current,new",
    [
        ("detected", "confirmed"),       # detected can only go to notified
        ("confirmed", "notified"),       # confirmed can only go to undone
        ("undone", "notified"),          # undone is terminal (no transitions)
        ("notified", "notified"),        # self-transition not allowed
        ("bogus_status", "notified"),    # unknown source status
    ],
)
def test_transition_invalid_raises(current, new):
    with pytest.raises(ValueError):
        s.transition_detection_status(current, new)


# ---------------------------------------------------------------------------
# _extract_candidate_from_title — best-effort fallback
# ---------------------------------------------------------------------------


def test_extract_candidate_from_title_name_and_email():
    assert s._extract_candidate_from_title("John Smith <> Acme") == ("John Smith", "")


def test_extract_candidate_from_title_email_extracted_lowercased():
    name, email = s._extract_candidate_from_title("Chat with JANE@X.COM 1:1")
    assert email == "jane@x.com"


def test_extract_candidate_from_title_pipe_role_chunk_wins():
    # CHARACTERIZED: "Interview: Jane Doe" contains the stop-word "interview",
    # so that chunk is skipped and the role chunk "Senior Engineer" is returned
    # as the (mis-labelled) candidate name. Refactor must preserve this.
    assert s._extract_candidate_from_title(
        "Interview: Jane Doe | Senior Engineer"
    ) == ("Senior Engineer", "")


def test_extract_candidate_from_title_empty():
    assert s._extract_candidate_from_title("") == ("", "")


def test_extract_candidate_from_title_only_stopwords():
    assert s._extract_candidate_from_title("<> <>") == ("", "")


# ---------------------------------------------------------------------------
# _normalize_person_name / _email_local_to_name / _extract_emails_from_text
# ---------------------------------------------------------------------------


def test_normalize_person_name_strips_nonalpha_and_lowers():
    assert s._normalize_person_name("Jean-Luc O Brien 3") == "jeanlucobrien"


def test_email_local_to_name_splits_separators():
    assert s._email_local_to_name("john.q.public@x.com") == "John Q Public"


def test_email_local_to_name_no_at():
    assert s._email_local_to_name("bob") == "Bob"


def test_extract_emails_from_text_multiple():
    assert s._extract_emails_from_text("a@x.com and b@y.io") == ["a@x.com", "b@y.io"]


def test_extract_emails_from_text_empty():
    assert s._extract_emails_from_text("") == []


# ---------------------------------------------------------------------------
# _extract_title_name_candidates — dedup + chunking
# ---------------------------------------------------------------------------


def test_extract_title_name_candidates_two_names():
    assert s._extract_title_name_candidates("Jane Doe <> John Smith") == [
        "Jane Doe",
        "John Smith",
    ]


def test_extract_title_name_candidates_dedup_normalized():
    # Same normalized key keeps only the first.
    assert s._extract_title_name_candidates("Jane Doe / jane doe") == ["Jane Doe"]


def test_extract_title_name_candidates_drops_stopword_chunks():
    assert s._extract_title_name_candidates("Interview <> John Smith") == ["John Smith"]


# ---------------------------------------------------------------------------
# _attendee_name_hints / _email_local_hints
# ---------------------------------------------------------------------------


def test_attendee_name_hints_from_display_and_email():
    hints = s._attendee_name_hints(
        [{"email": "john.smith@acme.com", "display_name": "John Smith"}]
    )
    assert hints == {"john", "smith", "johnsmith"}


def test_email_local_hints_strips_digits_and_adds_prefix():
    # single-token local >= 3 chars also yields a 3-char prefix
    assert s._email_local_hints("jsmith2@x.com") == {"jsmith", "jsm"}


def test_email_local_hints_short_single_token_no_prefix():
    assert s._email_local_hints("ab@x.com") == {"ab"}


def test_attendee_name_hints_filtered_by_email():
    attendees = [
        {"email": "a@x.com", "display_name": "Alice"},
        {"email": "b@x.com", "display_name": "Bob"},
    ]
    hints = s._attendee_name_hints(attendees, email="b@x.com")
    assert "bob" in hints and "alice" not in hints


# ---------------------------------------------------------------------------
# _name_hint_score / _best_title_name_match — SequenceMatcher thresholds
# ---------------------------------------------------------------------------


def test_name_hint_score_exact_token():
    assert s._name_hint_score("John", {"john"}) == 1.0


def test_name_hint_score_empty_inputs():
    assert s._name_hint_score("John", set()) == 0.0
    assert s._name_hint_score("", {"john"}) == 0.0


def test_best_title_name_match_picks_highest():
    names = ["Jane Doe", "John Smith"]
    name, score = s._best_title_name_match(names, {"john", "smith"})
    assert name == "John Smith"
    assert score == 1.0


def test_best_title_name_match_no_hints():
    assert s._best_title_name_match(["Jane Doe"], set()) == ("", 0.0)


# ---------------------------------------------------------------------------
# _extract_candidate_name_from_title — disambiguation (never silently guess)
# ---------------------------------------------------------------------------


def test_candidate_name_single_name_returned():
    assert s._extract_candidate_name_from_title("Jane Doe", []) == "Jane Doe"


def test_candidate_name_two_names_internal_disambiguates():
    internal = [{"email": "john.smith@acme.com", "display_name": "John Smith"}]
    # John Smith matches the internal interviewer at >=0.88 → the OTHER name
    # (Jane Doe) is the candidate.
    assert (
        s._extract_candidate_name_from_title("Jane Doe <> John Smith", internal)
        == "Jane Doe"
    )


def test_candidate_name_two_names_ambiguous_returns_empty():
    # CHARACTERIZED: no hints to disambiguate → do NOT guess, return "".
    assert s._extract_candidate_name_from_title("Jane Doe <> John Smith", []) == ""


def test_candidate_name_external_email_match():
    external = [{"email": "jane.doe@cand.com", "display_name": "Jane Doe"}]
    result = s._extract_candidate_name_from_title(
        "Jane Doe <> John Smith",
        [],
        external_attendees=external,
        candidate_email="jane.doe@cand.com",
    )
    assert result == "Jane Doe"


def test_candidate_name_no_names_empty():
    assert s._extract_candidate_name_from_title("<> <>", []) == ""


# ---------------------------------------------------------------------------
# _extract_interviewer_from_title / _extract_interviewer_name_from_title
# ---------------------------------------------------------------------------


def test_extract_interviewer_from_title_requires_separator():
    assert s._extract_interviewer_from_title("John Smith | Engineer") == ""


def test_extract_interviewer_from_title_left_of_separator():
    assert s._extract_interviewer_from_title("John Smith <> Jane Doe") == "John Smith"


def test_extract_interviewer_name_from_title_other_of_two():
    internal = [{"email": "john.smith@acme.com", "display_name": "John Smith"}]
    # interviewer email matches John → returns John
    result = s._extract_interviewer_name_from_title(
        "Jane Doe <> John Smith",
        internal,
        interviewer_email="john.smith@acme.com",
    )
    assert result == "John Smith"


# ---------------------------------------------------------------------------
# build_app_action_url
# ---------------------------------------------------------------------------


def test_build_app_action_url_no_ids_returns_base():
    url = s.build_app_action_url({})
    assert url.endswith("/dashboard")


def test_build_app_action_url_with_ids():
    url = s.build_app_action_url(
        detection_id="det-1", requisition_id="req-1", candidate_round_id="cr-1"
    )
    assert "detection_id=det-1" in url
    assert "requisition_id=req-1" in url
    assert "candidate_round_id=cr-1" in url


def test_build_app_action_url_reads_detection_dict():
    url = s.build_app_action_url(
        {"id": "d9", "matched_requisition_id": "r9"}
    )
    assert "detection_id=d9" in url and "requisition_id=r9" in url


# ---------------------------------------------------------------------------
# extract_meeting_url / detect_meeting_platform
# ---------------------------------------------------------------------------


def test_extract_meeting_url_from_conference_data():
    ev = {
        "raw": {
            "conferenceData": {
                "entryPoints": [
                    {"entryPointType": "video", "uri": "https://meet.google.com/abc"}
                ]
            }
        }
    }
    assert s.extract_meeting_url(ev) == "https://meet.google.com/abc"


def test_extract_meeting_url_from_location():
    ev = {"raw": {"location": "https://zoom.us/j/99", "description": ""}}
    assert s.extract_meeting_url(ev) == "https://zoom.us/j/99"


def test_extract_meeting_url_from_description():
    ev = {"raw": {"description": "join here https://teams.microsoft.com/l/x"}}
    assert s.extract_meeting_url(ev) == "https://teams.microsoft.com/l/x"


def test_extract_meeting_url_none():
    assert s.extract_meeting_url({"raw": {}}) is None


@pytest.mark.parametrize(
    "url,platform",
    [
        ("https://meet.google.com/x", "google_meet"),
        ("https://zoom.us/j/1", "zoom"),
        ("https://teams.microsoft.com/l/x", "teams"),
        ("https://company.webex.com/m", "webex"),
        ("https://example.com/", None),
        ("", None),
    ],
)
def test_detect_meeting_platform(url, platform):
    assert s.detect_meeting_platform(url) == platform


# ---------------------------------------------------------------------------
# extract_attendees — internal vs external by domain
# ---------------------------------------------------------------------------


def test_extract_attendees_splits_by_domain_and_skips_blank():
    ev = {
        "raw": {
            "attendees": [
                {"email": "a@acme.com", "displayName": "A"},
                {"email": "c@gmail.com"},
                {"email": ""},
            ]
        }
    }
    external, internal = s.extract_attendees(ev, "acme.com")
    assert [a["email"] for a in external] == ["c@gmail.com"]
    assert [a["email"] for a in internal] == ["a@acme.com"]
    assert internal[0]["display_name"] == "A"


# ---------------------------------------------------------------------------
# analyze_event — the multi-guard filter
# ---------------------------------------------------------------------------


def _make_event(**overrides):
    raw = {
        "summary": "Jane <> John",
        "conferenceData": {
            "entryPoints": [
                {"entryPointType": "video", "uri": "https://meet.google.com/x"}
            ]
        },
        "attendees": [{"email": "jane@cand.com"}, {"email": "john@acme.com"}],
        "start": {"dateTime": "2025-01-15T14:00:00+00:00"},
        "end": {"dateTime": "2025-01-15T14:45:00+00:00"},
    }
    raw.update(overrides)
    return {"raw": raw}


def test_analyze_event_happy_path():
    result = s.analyze_event(_make_event(), "acme.com")
    assert result is not None
    assert result["event_title"] == "Jane <> John"
    assert result["duration_minutes"] == 45.0
    assert result["meeting_platform"] == "google_meet"
    assert isinstance(result["event_start"], datetime)


def test_analyze_event_no_meeting_url_returns_none():
    ev = _make_event(conferenceData={}, location="", description="")
    assert s.analyze_event(ev, "acme.com") is None


def test_analyze_event_no_external_returns_none():
    ev = _make_event(
        attendees=[{"email": "x@acme.com"}, {"email": "y@acme.com"}]
    )
    assert s.analyze_event(ev, "acme.com") is None


def test_analyze_event_recurring_returns_none():
    ev = _make_event(recurringEventId="rec1")
    assert s.analyze_event(ev, "acme.com") is None


def test_analyze_event_too_short_returns_none():
    ev = _make_event(end={"dateTime": "2025-01-15T14:05:00+00:00"})
    assert s.analyze_event(ev, "acme.com") is None


def test_analyze_event_too_long_returns_none():
    ev = _make_event(end={"dateTime": "2025-01-15T16:00:00+00:00"})
    assert s.analyze_event(ev, "acme.com") is None


def test_analyze_event_too_many_attendees_returns_none():
    ev = _make_event(
        attendees=[
            {"email": "a@cand.com"},
            {"email": "b@cand.com"},
            {"email": "c@acme.com"},
            {"email": "d@acme.com"},
            {"email": "e@acme.com"},
            {"email": "f@acme.com"},
        ]
    )
    assert s.analyze_event(ev, "acme.com") is None


def test_analyze_event_naive_datetime_coerced_with_event_timezone():
    ev = {
        "raw": {
            "summary": "Jane <> John",
            "conferenceData": {
                "entryPoints": [
                    {"entryPointType": "video", "uri": "https://meet.google.com/x"}
                ]
            },
            "attendees": [{"email": "jane@cand.com"}, {"email": "john@acme.com"}],
            "start": {"dateTime": "2025-01-15T14:00:00", "timeZone": "America/New_York"},
            "end": {"dateTime": "2025-01-15T14:45:00", "timeZone": "America/New_York"},
        }
    }
    result = s.analyze_event(ev, "acme.com")
    assert result is not None
    assert result["event_start"].tzinfo is not None


# ---------------------------------------------------------------------------
# _coerce_timezone_name — alias map + heuristics
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("EST", "America/New_York"),
        ("EDT", "America/New_York"),
        ("PST", "America/Los_Angeles"),
        ("CST", "America/Chicago"),
        ("MST", "America/Denver"),
        ("IST", "Asia/Kolkata"),
        ("APAC", "Asia/Singapore"),
        ("US/Pacific", "America/Los_Angeles"),
        ("Pacific Time", "America/Los_Angeles"),
        ("Eastern Standard", "America/New_York"),
        ("Central", "America/Chicago"),
        ("Mountain", "America/Denver"),
        ("America/New_York", "America/New_York"),
        ("Asia/Kolkata", "Asia/Kolkata"),
        ("", ""),
        ("   ", ""),
        ("EST/PST", ""),          # ambiguous combined alias → fall back
        ("Mars/Phobos", "Mars/Phobos"),  # unknown passthrough
    ],
)
def test_coerce_timezone_name(raw, expected):
    assert s._coerce_timezone_name(raw) == expected


def test_coerce_timezone_name_case_insensitive_iana():
    assert s._coerce_timezone_name("america/new_york") == "America/New_York"


# ---------------------------------------------------------------------------
# _format_event_time / format_event_time_for_email
# ---------------------------------------------------------------------------


def test_format_event_time_utc_no_tz():
    dt = datetime(2025, 1, 15, 14, 30, tzinfo=timezone.utc)
    assert s._format_event_time(dt) == "Jan 15 at 02:30 PM"


def test_format_event_time_with_est_alias():
    dt = datetime(2025, 1, 15, 14, 30, tzinfo=timezone.utc)
    assert s._format_event_time(dt, "EST") == "Jan 15 at 09:30 AM"


def test_format_event_time_iso_string_with_z():
    assert (
        s._format_event_time("2025-01-15T14:30:00Z", "America/New_York")
        == "Jan 15 at 09:30 AM"
    )


def test_format_event_time_bad_string():
    assert s._format_event_time("notadate") == "TBD"


def test_format_event_time_none():
    assert s._format_event_time(None) == "TBD"


def test_format_event_time_for_email_includes_year_and_tz():
    dt = datetime(2025, 1, 15, 14, 30, tzinfo=timezone.utc)
    assert s.format_event_time_for_email(dt, "IST") == "Jan 15, 2025 at 08:00 PM IST"


def test_format_event_time_for_email_none():
    assert s.format_event_time_for_email(None) == "TBD"


# ---------------------------------------------------------------------------
# _display_value / _format_meeting_platform / _interaction_step_label
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value,expected",
    [
        ("unknown", "Not available"),
        ("Not set", "Not available"),
        ("n/a", "Not available"),
        ("null", "Not available"),
        ("", "Not available"),
        ("  Hi  ", "Hi"),
        ("Real Value", "Real Value"),
    ],
)
def test_display_value(value, expected):
    assert s._display_value(value) == expected


def test_display_value_custom_fallback():
    assert s._display_value("", fallback="X") == "X"


@pytest.mark.parametrize(
    "value,expected",
    [
        ("google_meet", "Google Meet"),
        ("zoom", "Zoom"),
        ("teams", "Microsoft Teams"),
        ("webex", "Webex"),
        ("custom_plat", "Custom Plat"),
        ("", "Not available"),
    ],
)
def test_format_meeting_platform(value, expected):
    assert s._format_meeting_platform(value) == expected


def test_interaction_step_label_known():
    assert s._interaction_step_label("role_select") == "Selecting Role"


def test_interaction_step_label_unknown_titlecased():
    assert s._interaction_step_label("some_custom_step") == "Some Custom Step"


def test_interaction_step_label_empty_defaults_detected():
    assert s._interaction_step_label("") == "Detected"


def test_status_to_interaction_step():
    assert s._status_to_interaction_step("awaiting_round") == "round_select"
    assert s._status_to_interaction_step("expired") == "orphan"
    assert s._status_to_interaction_step("garbage") == "detected"


def test_coalesce_text():
    assert s._coalesce_text("", "  ", "first", "second") == "first"
    assert s._coalesce_text("", fallback="fb") == "fb"


# ---------------------------------------------------------------------------
# _similarity / _role_similarity / _location_similarity / _fuzzy_round_match
# ---------------------------------------------------------------------------


def test_similarity_identical():
    assert s._similarity("Hello", "hello") == 1.0


def test_similarity_empty():
    assert s._similarity("", "x") == 0.0


def test_role_similarity_exact_token_overlap_high():
    assert s._role_similarity("Software Engineer", "Software Engineer") == 1.0


def test_role_similarity_short_prefix_guard():
    # CHARACTERIZED: "PR Manager" vs "MR Manager" — same head, diff 1-3 char
    # prefix → forced to 0.0 to avoid false-positive merges.
    assert s._role_similarity("PR Manager", "MR Manager") == 0.0


def test_role_similarity_no_token_overlap_dampened():
    # No shared tokens → seq_sim * 0.6 (or seq_sim if higher via blend path).
    score = s._role_similarity("Backend Engineer", "Marketing Lead")
    assert 0.0 <= score < 0.6


@pytest.mark.parametrize(
    "a,b,expected",
    [
        ("Bangalore", "Bangalore, India", 1.0),
        ("BLR", "Bengaluru", 1.0),
        ("NYC", "New York City", 1.0),
        ("SF", "San Francisco", 1.0),
        ("Remote", "Onsite", 0.0),       # both pure stop-words → empty sets
    ],
)
def test_location_similarity(a, b, expected):
    assert s._location_similarity(a, b) == expected


def test_location_similarity_empty():
    assert s._location_similarity("", "x") == 0.0


def test_fuzzy_round_match_sequence():
    assert s._fuzzy_round_match("Tech Screen", "Technical Screen") is True


def test_fuzzy_round_match_token_overlap():
    assert s._fuzzy_round_match("Final Interview Round", "Final Round") is True


def test_fuzzy_round_match_no_match():
    assert s._fuzzy_round_match("Phone Screen", "System Design") is False


def test_fuzzy_round_match_empty_extracted():
    assert s._fuzzy_round_match("", "Anything") is False


def test_canonical_location_alias_and_stopwords():
    assert s._canonical_location("Bengaluru, India") == "bangalore"
    assert s._canonical_location("Remote") == ""


def test_role_tokens_drops_generic_words():
    assert s._role_tokens("Senior Software Engineer") == ["software", "engineer"]


def test_description_overlap_ratio():
    ratio = s._description_overlap_ratio(
        "Backend Engineer", "We need a backend engineer for payments"
    )
    assert ratio == 1.0


# ---------------------------------------------------------------------------
# email_affinity_lookup / score_role_match / check_interviewer_match
# ---------------------------------------------------------------------------


def test_email_affinity_lookup():
    cands = [
        {"email": "a@x.com", "requisition_id": "r1"},
        {"email": "b@x.com", "requisition_id": "r2"},
    ]
    assert s.email_affinity_lookup({"a@x.com"}, cands) == {"a@x.com": {"r1"}}


def _req():
    return {
        "id": "r1",
        "role_title": "Software Engineer",
        "role_location": "Bangalore",
        "rounds": [{"id": "rd1", "name": "Technical Screen"}],
    }


def test_score_role_match_full_signals_no_email():
    extracted = {
        "role_name": "Software Engineer",
        "location": "Bangalore",
        "round_name": "Technical Screen",
    }
    score, round_id = s.score_role_match(_req(), extracted, set())
    # 0.30 role + 0.25 location + 0.25 round = 0.80
    assert round_id == "rd1"
    assert score == pytest.approx(0.80)


def test_score_role_match_single_email_affinity_boost():
    extracted = {
        "role_name": "Software Engineer",
        "location": "Bangalore",
        "round_name": "Technical Screen",
    }
    score, _ = s.score_role_match(_req(), extracted, {"r1"})
    assert score == pytest.approx(1.0)


def test_score_role_match_no_signals():
    assert s.score_role_match(_req(), {}, set()) == (0.0, None)


def test_check_interviewer_match():
    assert (
        s.check_interviewer_match(
            {"internal_attendees": [{"email": "a@x.com"}]},
            {"default_interviewer_emails": ["A@x.com"]},
        )
        == "match"
    )
    assert (
        s.check_interviewer_match(
            {"internal_attendees": [{"email": "z@x.com"}]},
            {"default_interviewer_emails": ["A@x.com"]},
        )
        == "mismatch"
    )
    assert (
        s.check_interviewer_match({"internal_attendees": []}, {}) == "unset"
    )


# ---------------------------------------------------------------------------
# resolve_interviewer_email — P1..P4 cascade
# ---------------------------------------------------------------------------


def test_resolve_interviewer_email_p1_round_default():
    result = s.resolve_interviewer_email(
        [{"email": "a@x.com"}, {"email": "b@x.com"}],
        {"default_interviewer_emails": ["b@x.com"]},
        "rec@x.com",
    )
    assert result == "b@x.com"


def test_resolve_interviewer_email_p2_sole_internal():
    assert (
        s.resolve_interviewer_email([{"email": "sole@x.com"}], None, "rec@x.com")
        == "sole@x.com"
    )


def test_resolve_interviewer_email_p3_non_recruiter_sorted():
    assert (
        s.resolve_interviewer_email(
            [{"email": "rec@x.com"}, {"email": "z@x.com"}], None, "rec@x.com"
        )
        == "z@x.com"
    )


def test_resolve_interviewer_email_p4_fallback_recruiter():
    assert s.resolve_interviewer_email([], None, "rec@x.com") == "rec@x.com"


def test_resolve_organizer_from_organizer_field():
    ev = {"raw": {"organizer": {"email": "boss@x.com"}, "attendees": []}}
    users = {"boss@x.com": {"profile_id": "p1"}}
    assert s.resolve_organizer(ev, users) == "p1"


def test_resolve_organizer_from_attendee_fallback():
    ev = {
        "raw": {
            "organizer": {"email": "stranger@x.com"},
            "attendees": [{"email": "known@x.com"}],
        }
    }
    users = {"known@x.com": {"profile_id": "p2"}}
    assert s.resolve_organizer(ev, users) == "p2"


def test_resolve_organizer_none():
    assert s.resolve_organizer({"raw": {}}, {}) is None


# ---------------------------------------------------------------------------
# resolve_candidate_name — title > classified > display > email-local
# ---------------------------------------------------------------------------


def test_resolve_candidate_name_single_title_token_short_circuits():
    # CHARACTERIZED: a single-token title that is not a stop word becomes the
    # title-name candidate and short-circuits BEFORE display_name / email-local
    # fallbacks. "Standup" wins over the real attendee display name.
    analyzed = {
        "event_title": "Standup",
        "external_attendees": [{"email": "jane@cand.com", "display_name": "Jane Q"}],
        "internal_attendees": [],
    }
    assert s.resolve_candidate_name(analyzed, "jane@cand.com") == "Standup"


def test_resolve_candidate_name_from_display():
    # Empty title → no title-name candidate → falls through to display_name.
    analyzed = {
        "event_title": "",
        "external_attendees": [{"email": "jane@cand.com", "display_name": "Jane Q"}],
        "internal_attendees": [],
    }
    assert s.resolve_candidate_name(analyzed, "jane@cand.com") == "Jane Q"


def test_resolve_candidate_name_email_local_fallback():
    analyzed = {
        "event_title": "",
        "external_attendees": [{"email": "jane.q@cand.com", "display_name": ""}],
        "internal_attendees": [],
    }
    assert s.resolve_candidate_name(analyzed, "jane.q@cand.com") == "Jane Q"


def test_resolve_candidate_name_classification_path():
    # Title is only a stop word → no title candidate → classification wins.
    analyzed = {
        "event_title": "Interview",
        "detection_signals": {"classification": {"candidate_name": "Classified Cand"}},
        "external_attendees": [{"email": "jane@cand.com", "display_name": "Jane Q"}],
        "internal_attendees": [],
    }
    assert s.resolve_candidate_name(analyzed, "jane@cand.com") == "Classified Cand"


# ---------------------------------------------------------------------------
# build_guidelines_html
# ---------------------------------------------------------------------------


def test_build_guidelines_html_empty():
    assert s.build_guidelines_html(None) == ""
    assert s.build_guidelines_html([]) == ""


def test_build_guidelines_html_escapes_and_formats():
    html = s.build_guidelines_html(
        [{"title": "Tip <1>", "description": "Line1\nLine2"}]
    )
    assert "&lt;1&gt;" in html          # escaped
    assert "<br>" in html               # newline → <br>
    assert "<strong>" in html


def test_build_guidelines_html_skips_non_dict_and_empty():
    html = s.build_guidelines_html(["bad", {"title": "", "description": ""}])
    assert html == ""


# ---------------------------------------------------------------------------
# resolve_role_matches — confidence tiers + "never silently pick" truncation
#
# We always pass extracted_fields so no live LLM call is made.
# ---------------------------------------------------------------------------


_ANALYZED = {"external_attendees": [{"email": "x@cand.com"}], "location": "", "description": ""}


def _two_reqs_close():
    return [
        {
            "id": "r1",
            "role_title": "Software Engineer",
            "role_location": "",
            "rounds": [{"id": "rd1", "name": "Technical"}],
            "created_at": "2025-01-01",
        },
        {
            "id": "r2",
            "role_title": "Software Engineer II",
            "role_location": "",
            "rounds": [{"id": "rd2", "name": "Technical"}],
            "created_at": "2025-01-02",
        },
    ]


def _strong_weak_reqs():
    return [
        {
            "id": "r1",
            "role_title": "Software Engineer",
            "role_location": "Bangalore",
            "rounds": [{"id": "rd1", "name": "Technical"}],
            "created_at": "2025-01-01",
        },
        {
            "id": "r2",
            "role_title": "Marketing Lead",
            "role_location": "NYC",
            "rounds": [],
            "created_at": "2025-01-02",
        },
    ]


async def test_resolve_role_matches_no_reqs():
    ranked, meta = await s.resolve_role_matches(
        _ANALYZED, [], [], extracted_fields={"role_name": "X"}
    )
    assert ranked == []
    assert meta["match_type"] == "no_signal"


async def test_resolve_role_matches_single_auto_select():
    ext = {"role_name": "Software Engineer", "location": "Bangalore", "round_name": "Technical"}
    ranked, meta = await s.resolve_role_matches(
        _ANALYZED, [_strong_weak_reqs()[0]], [], extracted_fields=ext
    )
    assert meta["match_type"] == "auto_select"


async def test_resolve_role_matches_strong_vs_weak_auto_select():
    ext = {"role_name": "Software Engineer", "location": "Bangalore", "round_name": "Technical"}
    ranked, meta = await s.resolve_role_matches(
        _ANALYZED, _strong_weak_reqs(), [], extracted_fields=ext
    )
    # Big score gap (>=0.2) and top>=0.5 → auto_select.
    assert meta["match_type"] == "auto_select"
    assert meta["matched_round_id"] == "rd1"


async def test_resolve_role_matches_two_close_narrowed():
    ext = {"role_name": "Software Engineer", "round_name": "Technical"}
    ranked, meta = await s.resolve_role_matches(
        _ANALYZED, _two_reqs_close(), [], extracted_fields=ext
    )
    # Two similar scores, no decisive gap → narrowed (never auto-pick).
    assert meta["match_type"] == "narrowed"


async def test_resolve_role_matches_truncation_downgrades_auto_to_narrowed():
    # Two visible reqs both score-eligible; truncation forces manual choice.
    ext = {"role_name": "Software Engineer", "location": "Bangalore", "round_name": "Technical"}
    reqs = [
        {
            "id": "r1",
            "role_title": "Software Engineer",
            "role_location": "Bangalore",
            "rounds": [{"id": "rd1", "name": "Technical"}],
            "created_at": "2025-01-02",
        },
        {
            "id": "r2",
            "role_title": "Software Engineer",
            "role_location": "Bangalore",
            "rounds": [{"id": "rd2", "name": "Technical"}],
            "created_at": "2025-01-01",
        },
    ]
    ranked, meta = await s.resolve_role_matches(
        _ANALYZED, reqs, [], extracted_fields=ext, requisitions_truncated=True
    )
    assert meta["match_type"] == "narrowed"
    assert meta["requisitions_truncated"] is True


async def test_resolve_role_matches_truncation_email_anchor_keeps_auto():
    # Candidate email tied to the top visible req → truncation safe-exception.
    ext = {"role_name": "Software Engineer", "location": "Bangalore", "round_name": "Technical"}
    candidates = [{"email": "x@cand.com", "requisition_id": "r1"}]
    ranked, meta = await s.resolve_role_matches(
        _ANALYZED, _strong_weak_reqs(), candidates,
        extracted_fields=ext, requisitions_truncated=True,
    )
    assert meta["match_type"] == "auto_select"
    assert meta["email_req_ids"] == ["r1"]


async def test_resolve_role_matches_truncation_single_downgrades_to_partial():
    ext = {"role_name": "Software Engineer", "location": "Bangalore", "round_name": "Technical"}
    ranked, meta = await s.resolve_role_matches(
        _ANALYZED, [_strong_weak_reqs()[0]], [],
        extracted_fields=ext, requisitions_truncated=True,
    )
    # Single scored req + truncation + no email anchor → partial_signal.
    assert meta["match_type"] == "partial_signal"


async def test_resolve_role_matches_location_mismatch():
    ext = {"role_name": "Software Engineer", "location": "Mars", "round_name": "Technical"}
    ranked, meta = await s.resolve_role_matches(
        _ANALYZED, _strong_weak_reqs(), [], extracted_fields=ext
    )
    assert meta["match_type"] == "location_mismatch"
    assert meta["location_no_match"] is True


# ---------------------------------------------------------------------------
# build_interaction_context — name/email/interviewer resolution
# ---------------------------------------------------------------------------


def _detection():
    return {
        "id": "det-abcdef12",
        "event_title": "Jane Doe <> John Smith",
        "event_start": "2025-01-15T14:00:00+00:00",
        "meeting_platform": "zoom",
        "external_attendees": [{"email": "jane@cand.com", "display_name": "Jane Doe"}],
        "internal_attendees": [
            {"email": "john.smith@acme.com", "display_name": "John Smith", "self": True}
        ],
        "detection_signals": {},
    }


def test_build_interaction_context_resolves_parties():
    ctx = s.build_interaction_context(_detection())
    assert ctx["candidate_name"] == "Jane Doe"
    assert ctx["candidate_email"] == "jane@cand.com"
    assert ctx["interviewer_name"] == "John Smith"
    assert ctx["role_title"] == "Not set"
    assert ctx["round_name"] == "Not set"
    assert ctx["current_step_key"] == "detected"
    assert ctx["current_step"] == "Detected"


def test_build_interaction_context_overrides_win():
    ctx = s.build_interaction_context(
        _detection(), role_title="Backend Eng", round_name="Final", current_step="review"
    )
    assert ctx["role_title"] == "Backend Eng"
    assert ctx["round_name"] == "Final"
    assert ctx["current_step"] == "Review"


def test_merge_interaction_context_writes_into_signals():
    signals = {"existing": "kept"}
    merged = s.merge_interaction_context(signals, _detection(), role_title="X")
    assert merged["existing"] == "kept"
    assert merged["interaction_context"]["role_title"] == "X"


# ---------------------------------------------------------------------------
# Block Kit builders
# ---------------------------------------------------------------------------


def _reqs_one():
    return [
        {
            "id": "req-1",
            "role_title": "Software Engineer",
            "role_location": "Bangalore",
            "rounds": [{"id": "rd1", "name": "Technical"}],
            "created_at": "2025-01-01",
        }
    ]


def test_build_detection_blocks_auto_select_structure():
    meta = {
        "match_type": "auto_select",
        "extraction": {"role_name": "Software Engineer", "location": "Bangalore"},
        "matched_round_id": "rd1",
        "email_req_ids": [],
        "scores": {"req-1": 0.8},
    }
    blocks = s.build_detection_blocks(
        {**_detection(), "detection_confidence": 0.9}, _reqs_one(), meta
    )
    assert [b.get("type") for b in blocks] == [
        "section", "section", "context", "section", "actions", "actions", "divider"
    ]
    # HIGH tier header
    assert ":white_check_mark:" in blocks[1]["text"]["text"]


def test_build_detection_blocks_low_tier_header():
    blocks = s.build_detection_blocks(
        {**_detection(), "detection_confidence": 0.3},
        _reqs_one(),
        {"match_type": "narrowed", "scores": {"req-1": 0.4}, "extraction": {}},
    )
    assert "Potential interview" in blocks[1]["text"]["text"]


def test_build_detection_blocks_location_mismatch_branch():
    meta = {"match_type": "location_mismatch", "location_no_match": True,
            "extraction": {"location": "Mars"}}
    blocks = s.build_detection_blocks(
        {**_detection(), "detection_confidence": 0.9}, _reqs_one(), meta
    )
    action_ids = [
        e.get("action_id")
        for blk in blocks if blk.get("type") == "actions"
        for e in blk.get("elements", [])
    ]
    assert "cal_intel_change_role" in action_ids
    assert "cal_intel_not_interview" in action_ids


def test_build_detection_blocks_no_matches_shows_dismiss():
    blocks = s.build_detection_blocks(
        {**_detection(), "detection_confidence": 0.9}, [],
        {"match_type": "no_signal", "extraction": {}},
    )
    action_ids = [
        e.get("action_id")
        for blk in blocks if blk.get("type") == "actions"
        for e in blk.get("elements", [])
    ]
    assert "cal_intel_dismiss" in action_ids
    assert "cal_intel_not_interview" in action_ids


def test_build_detection_blocks_truncation_warning():
    meta = {"match_type": "narrowed", "requisitions_truncated": True,
            "extraction": {}, "scores": {"req-1": 0.5}}
    blocks = s.build_detection_blocks(
        {**_detection(), "detection_confidence": 0.9}, _reqs_one(), meta
    )
    assert any(
        "newest 100 open roles" in str(b.get("elements", ""))
        for b in blocks if b.get("type") == "context"
    )


def test_build_role_selection_blocks_under_100_is_select():
    block = s.build_role_selection_blocks("det-abcdef12", _reqs_one())
    assert block["accessory"]["type"] == "static_select"
    assert len(block["accessory"]["options"]) == 1


def test_build_role_selection_blocks_over_100_is_link():
    big = [{"id": f"r{i}", "role_title": "R", "role_location": "", "rounds": []}
           for i in range(101)]
    block = s.build_role_selection_blocks("det-1", big)
    assert block["block_id"].startswith("cal_intel_role_link_")
    assert block["accessory"]["type"] == "button"


def test_build_round_selection_single_round_uses_button():
    blocks = s.build_round_selection_blocks(
        "det-abcdef12", [{"id": "rd1", "name": "Technical", "duration_minutes": 45}]
    )
    action_ids = [
        e["action_id"] for blk in blocks if blk.get("type") == "actions"
        for e in blk["elements"]
    ]
    assert "cal_intel_select_round" in action_ids


def test_build_round_selection_many_uses_dropdown():
    rounds = [{"id": f"rd{i}", "name": f"Round {i}", "duration_minutes": 30}
              for i in range(6)]
    blocks = s.build_round_selection_blocks("det-1", rounds)
    assert any(b.get("accessory", {}).get("type") == "static_select" for b in blocks)


def test_build_round_selection_five_or_fewer_uses_buttons():
    rounds = [{"id": f"rd{i}", "name": f"Round {i}", "duration_minutes": 30}
              for i in range(3)]
    blocks = s.build_round_selection_blocks("det-1", rounds)
    select_round_buttons = [
        e for blk in blocks if blk.get("type") == "actions"
        for e in blk["elements"]
        if str(e.get("action_id", "")).startswith("cal_intel_select_round_")
    ]
    assert len(select_round_buttons) == 3


def test_build_confirmation_blocks_action_ids():
    blocks = s.build_confirmation_blocks(
        _detection(), "Jane Doe", "Technical", role_title="SWE"
    )
    action_ids = [
        e.get("action_id") for blk in blocks if blk.get("type") == "actions"
        for e in blk.get("elements", [])
    ]
    assert "cal_intel_send_prep" in action_ids
    assert "cal_intel_undo" in action_ids


def test_build_confirmation_blocks_no_actions():
    blocks = s.build_confirmation_blocks(
        _detection(), "Jane Doe", "Technical", include_actions=False
    )
    # Only the open-in-app action block survives.
    post_action_blocks = [
        b for b in blocks if b.get("type") == "actions"
        and b.get("block_id", "").startswith("cal_intel_post_actions")
    ]
    assert post_action_blocks == []


def test_build_no_req_blocks_reasons():
    blocks_default = s.build_no_req_blocks(_detection())
    assert any("No matching role" in str(b.get("text", "")) for b in blocks_default)
    blocks_no_rounds = s.build_no_req_blocks(_detection(), reason="no_rounds")
    assert any("don't have interview rounds" in str(b.get("text", ""))
               for b in blocks_no_rounds)


def test_build_untracked_captured_blocks_defaults():
    blocks = s.build_untracked_captured_blocks(_detection())
    assert any("Interview captured" in str(b.get("text", "")) for b in blocks)


def test_build_review_blocks_back_button():
    blocks = s.build_review_blocks(
        _detection(), "SWE", {"id": "rd1", "name": "Technical"}, show_back_to_round=True
    )
    action_ids = [
        e.get("action_id") for blk in blocks if blk.get("type") == "actions"
        for e in blk.get("elements", [])
    ]
    assert "cal_intel_confirm_setup" in action_ids
    assert "cal_intel_back_round" in action_ids


def test_build_reminder_blocks_levels():
    b1 = s.build_reminder_blocks(_detection(), 1)
    assert any("Pending interview setup" in str(b.get("text", "")) for b in b1)
    b3 = s.build_reminder_blocks(_detection(), 3)
    assert any("Last chance" in str(b.get("text", "")) for b in b3)


def test_build_error_blocks():
    blocks = s.build_error_blocks("oops")
    assert blocks[0]["text"]["text"] == ":x: oops"


def test_build_role_modal_structure():
    modal = s.build_role_modal("det-1", _reqs_one())
    assert modal["type"] == "modal"
    assert modal["callback_id"] == "cal_intel_modal_det-1"
    assert modal["submit"]["text"] == "Select"
    options = modal["blocks"][0]["element"]["options"]
    assert options[0]["value"] == "req-1"


def test_build_attendee_change_blocks_diffs():
    blocks = s.build_attendee_change_blocks(
        _detection(),
        old_internal_emails={"a@x.com"},
        new_internal_emails={"a@x.com", "b@x.com"},
        old_external_emails={"c@x.com"},
        new_external_emails={"c@x.com"},
    )
    text = " ".join(
        b.get("text", {}).get("text", "") for b in blocks if b.get("type") == "section"
    )
    assert "Added: b@x.com" in text


def test_build_reschedule_blocks():
    old = datetime(2025, 1, 15, 14, 0, tzinfo=timezone.utc)
    new = datetime(2025, 1, 16, 15, 0, tzinfo=timezone.utc)
    blocks = s.build_reschedule_blocks(_detection(), old, new)
    action_ids = [
        e.get("action_id") for blk in blocks if blk.get("type") == "actions"
        for e in blk.get("elements", [])
    ]
    assert "cal_intel_reschedule_update" in action_ids
    assert "cal_intel_undo" in action_ids
