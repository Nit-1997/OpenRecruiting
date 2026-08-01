"""Schema tests for PATCH /api/v2/intake/sessions/{id}/answers."""

import pytest
from pydantic import ValidationError

from app.api.v2.schemas.intake import PatchAnswersRequest, PatchAnswersResponse


def test_patch_answers_request_accepts_text_and_status():
    req = PatchAnswersRequest.model_validate({
        "patch": {
            "q4_must_haves": {"text": "Python, PG, Kafka", "status": "validated"},
            "q1_role_overview": {"text": "payments infra"},
        }
    })
    assert "q4_must_haves" in req.patch
    assert req.patch["q4_must_haves"].text == "Python, PG, Kafka"
    assert req.patch["q4_must_haves"].status == "validated"
    assert req.patch["q1_role_overview"].status is None


def test_patch_answers_request_rejects_unknown_qid():
    with pytest.raises(ValidationError) as exc:
        PatchAnswersRequest.model_validate({
            "patch": {"q99_nonsense": {"text": "x"}}
        })
    assert "q99_nonsense" in str(exc.value) or "qid" in str(exc.value).lower()


def test_patch_answers_request_rejects_invalid_status():
    with pytest.raises(ValidationError):
        PatchAnswersRequest.model_validate({
            "patch": {"q1_role_overview": {"status": "kinda_done"}}
        })


def test_patch_answers_request_rejects_empty_patch():
    with pytest.raises(ValidationError) as exc:
        PatchAnswersRequest.model_validate({"patch": {}})
    assert "empty" in str(exc.value).lower() or "min" in str(exc.value).lower()


def test_patch_answers_request_rejects_entry_with_no_fields():
    """Each per-qid entry must have at least text or status — otherwise it's a no-op."""
    with pytest.raises(ValidationError):
        PatchAnswersRequest.model_validate({
            "patch": {"q1_role_overview": {}}
        })


def test_patch_answers_response_shape():
    resp = PatchAnswersResponse(applied=["q4_must_haves", "q1_role_overview"])
    dumped = resp.model_dump()
    assert dumped == {"applied": ["q4_must_haves", "q1_role_overview"]}
