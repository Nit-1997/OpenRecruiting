def test_calendar_intelligence_service_imports():
    from app.services import calendar_intelligence_service as s
    for sym in ("analyze_event", "llm_classify_and_extract", "resolve_organizer",
                "resolve_role_matches", "transition_detection_status", "build_detection_blocks",
                "resolve_candidate_name", "resolve_interviewer_email", "merge_interaction_context"):
        assert hasattr(s, sym), f"missing {sym}"
