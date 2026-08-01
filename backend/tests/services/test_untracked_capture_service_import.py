def test_untracked_capture_service_imports():
    from app.services import untracked_capture_service as s
    for sym in ("capture_untracked_interview", "materialize_untracked_capture",
                "is_untracked_capture_enabled", "GENERIC_TEMPLATE_CONFIG",
                "get_auto_join_untracked_preference"):
        assert hasattr(s, sym), f"missing {sym}"
