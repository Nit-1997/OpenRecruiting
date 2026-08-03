"""Characterization tests for cal_intel/blocks pure helpers and small builders."""

from unittest.mock import patch
from types import SimpleNamespace

from app.services.cal_intel import blocks as b


def _settings(appurl="http://localhost:3005"):
    return SimpleNamespace(APP_URL=appurl)


# ----------------------- _coalesce_text -----------------------

def test_coalesce_text_first_nonblank():
    assert b._coalesce_text("", "  ", "real", "next") == "real"


def test_coalesce_text_fallback():
    assert b._coalesce_text("", None, fallback="fb") == "fb"


# ----------------------- _display_value -----------------------

def test_display_value_real():
    assert b._display_value("Engineer") == "Engineer"


def test_display_value_placeholder_to_fallback():
    for placeholder in ["unknown", "N/A", "none", "TBD", ""]:
        assert b._display_value(placeholder) == "Not available"


# ----------------------- _format_meeting_platform -----------------------

def test_format_meeting_platform_known():
    assert b._format_meeting_platform("google_meet") == "Google Meet"
    assert b._format_meeting_platform("zoom") == "Zoom"


def test_format_meeting_platform_unknown_titlecased():
    assert b._format_meeting_platform("some_other") == "Some Other"


def test_format_meeting_platform_empty():
    assert b._format_meeting_platform("") == "Not available"


# ----------------------- _interaction_step_label / _status_to_interaction_step -----------------------

def test_interaction_step_label_empty_defaults_detected():
    assert b._interaction_step_label("") == b._INTERACTION_STEP_LABELS["detected"]


def test_interaction_step_label_unknown_titlecased():
    assert b._interaction_step_label("some_step") == "Some Step"


def test_status_to_interaction_step_unknown_defaults():
    assert b._status_to_interaction_step("nonsense_status") == "detected"


# ----------------------- _add_role_url -----------------------

def test_add_role_url_uses_app_url():
    with patch.object(b, "get_settings", lambda: _settings("http://localhost:3005/")):
        assert b._add_role_url() == "http://localhost:3005/dashboard"


def test_add_role_url_fallback_when_unset():
    with patch.object(b, "get_settings", lambda: _settings("")):
        assert b._add_role_url() == "http://localhost:3005/dashboard"


# ----------------------- build_app_action_url -----------------------

def test_build_app_action_url_no_params():
    with patch.object(b, "get_settings", lambda: _settings()):
        assert b.build_app_action_url() == "http://localhost:3005/dashboard"


def test_build_app_action_url_with_params():
    with patch.object(b, "get_settings", lambda: _settings()):
        url = b.build_app_action_url(detection_id="d1", requisition_id="r1")
    assert "detection_id=d1" in url
    assert "requisition_id=r1" in url


def test_build_app_action_url_from_detection_dict():
    with patch.object(b, "get_settings", lambda: _settings()):
        url = b.build_app_action_url({"id": "d9", "matched_requisition_id": "r9"})
    assert "detection_id=d9" in url


# ----------------------- _role_label / _role_option_label -----------------------

def test_role_label_with_location():
    assert b._role_label({"role_title": "Eng", "role_location": "NYC"}) == "Eng (NYC)"


def test_role_label_no_location():
    assert b._role_label({"role_title": "Eng", "role_location": ""}) == "Eng"


def test_role_option_label_appends_created_date():
    out = b._role_option_label({"role_title": "Eng", "role_location": "", "created_at": "2025-01-15T00:00:00Z"})
    assert out.startswith("Eng")


# ----------------------- build_error_blocks / open button -----------------------

def test_build_error_blocks():
    out = b.build_error_blocks("Something broke")
    assert out[0]["block_id"] == "cal_intel_error"
    assert "Something broke" in out[0]["text"]["text"]


def test_build_open_in_app_button():
    with patch.object(b, "get_settings", lambda: _settings()):
        btn = b.build_open_in_app_button({"id": "d1"})
    assert btn["action_id"] == "cal_intel_open_dashboard"
    assert btn["url"]


def test_build_open_in_app_action_block():
    with patch.object(b, "get_settings", lambda: _settings()):
        block = b.build_open_in_app_action_block({"id": "abcdef1234"}, "main")
    assert block["type"] == "actions"
    assert "cal_intel_open_app_main" in block["block_id"]
