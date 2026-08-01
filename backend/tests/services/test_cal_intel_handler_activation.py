def test_cal_intel_handler_imports_and_activates_guards():
    from app.services.calendar_intelligence_handler import (
        handle_cal_intel_action, handle_cal_intel_modal_submit,
    )
    assert callable(handle_cal_intel_action)
    assert callable(handle_cal_intel_modal_submit)


def test_webhooks_slack_can_import_handler():
    import importlib
    mod = importlib.import_module("app.services.calendar_intelligence_handler")
    assert hasattr(mod, "handle_cal_intel_action")
