"""BE-T1: admin candidate assessment-evaluation/instance endpoint coverage."""
import httpx

from tests.helpers.supabase_mocks import rest_url
from tests.helpers.mock_data import CANDIDATE_ROUND_ID, CANDIDATE_ID, ROUND_ID, NOW

V2_ROOT = "/api/v2"
ADMIN = f"{V2_ROOT}/admin"


def _cr_no_assessment():
    return {
        "id": CANDIDATE_ROUND_ID,
        "candidate_id": CANDIDATE_ID,
        "round_id": ROUND_ID,
        "status": "completed",
        "summary": None,
        "rating": None,
        "rounds": {"id": ROUND_ID, "assessment_template_id": None},
        "candidates": {"id": CANDIDATE_ID, "email": "a@b.com", "name": "A"},
    }


def _cr_with_assessment():
    cr = _cr_no_assessment()
    cr["rounds"]["assessment_template_id"] = "00000000-0000-0000-0000-0000000000aa"
    return cr


# ── get_assessment_evaluation ────────────────────────────────────────────────

def test_get_assessment_evaluation_404(staff_client, respx_mock):
    respx_mock.get(rest_url("candidate_rounds")).mock(
        return_value=httpx.Response(200, json=[])
    )
    resp = staff_client.get(
        f"{ADMIN}/candidate-rounds/{CANDIDATE_ROUND_ID}/assessment-evaluation"
    )
    assert resp.status_code == 404, resp.text


def test_get_assessment_evaluation_not_assessment_400(staff_client, respx_mock):
    respx_mock.get(rest_url("candidate_rounds")).mock(
        return_value=httpx.Response(200, json=[_cr_no_assessment()])
    )
    resp = staff_client.get(
        f"{ADMIN}/candidate-rounds/{CANDIDATE_ROUND_ID}/assessment-evaluation"
    )
    assert resp.status_code == 400, resp.text


def test_get_assessment_evaluation_no_instance(staff_client, respx_mock):
    respx_mock.get(rest_url("candidate_rounds")).mock(
        return_value=httpx.Response(200, json=[_cr_with_assessment()])
    )
    respx_mock.get(rest_url("assessment_instances")).mock(
        return_value=httpx.Response(200, json=[])
    )
    resp = staff_client.get(
        f"{ADMIN}/candidate-rounds/{CANDIDATE_ROUND_ID}/assessment-evaluation"
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["assessment_instance_id"] is None


def test_get_assessment_evaluation_with_instance(staff_client, respx_mock):
    respx_mock.get(rest_url("candidate_rounds")).mock(
        return_value=httpx.Response(200, json=[_cr_with_assessment()])
    )
    respx_mock.get(rest_url("assessment_instances")).mock(
        return_value=httpx.Response(
            200,
            json=[{
                "id": "00000000-0000-0000-0000-0000000000bb",
                "status": "evaluated",
                "evaluation_result": {"passed": True},
                "evaluation_notes": "ok",
                "evaluated_at": NOW,
            }],
        )
    )
    resp = staff_client.get(
        f"{ADMIN}/candidate-rounds/{CANDIDATE_ROUND_ID}/assessment-evaluation"
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["evaluation_result"] == {"passed": True}


# ── get_assessment_instance ──────────────────────────────────────────────────

def test_get_assessment_instance_404(staff_client, respx_mock):
    respx_mock.get(rest_url("candidate_rounds")).mock(
        return_value=httpx.Response(200, json=[])
    )
    resp = staff_client.get(
        f"{ADMIN}/candidate-rounds/{CANDIDATE_ROUND_ID}/assessment-instance"
    )
    assert resp.status_code == 404, resp.text


def test_get_assessment_instance_not_assessment_400(staff_client, respx_mock):
    respx_mock.get(rest_url("candidate_rounds")).mock(
        return_value=httpx.Response(200, json=[_cr_no_assessment()])
    )
    resp = staff_client.get(
        f"{ADMIN}/candidate-rounds/{CANDIDATE_ROUND_ID}/assessment-instance"
    )
    assert resp.status_code == 400, resp.text


def test_get_assessment_instance_no_instance(staff_client, respx_mock):
    respx_mock.get(rest_url("candidate_rounds")).mock(
        return_value=httpx.Response(200, json=[_cr_with_assessment()])
    )
    respx_mock.get(rest_url("assessment_instances")).mock(
        return_value=httpx.Response(200, json=[])
    )
    resp = staff_client.get(
        f"{ADMIN}/candidate-rounds/{CANDIDATE_ROUND_ID}/assessment-instance"
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["assessment_instance"] is None


# ── update_assessment_evaluation 404 / not-assessment ────────────────────────

def test_update_assessment_evaluation_404(staff_client, respx_mock):
    respx_mock.get(rest_url("candidate_rounds")).mock(
        return_value=httpx.Response(200, json=[])
    )
    resp = staff_client.put(
        f"{ADMIN}/candidate-rounds/{CANDIDATE_ROUND_ID}/assessment-evaluation",
        json={"category_scores": []},
    )
    assert resp.status_code == 404, resp.text


def test_update_assessment_evaluation_not_assessment_400(staff_client, respx_mock):
    respx_mock.get(rest_url("candidate_rounds")).mock(
        return_value=httpx.Response(200, json=[_cr_no_assessment()])
    )
    resp = staff_client.put(
        f"{ADMIN}/candidate-rounds/{CANDIDATE_ROUND_ID}/assessment-evaluation",
        json={"category_scores": []},
    )
    assert resp.status_code == 400, resp.text


def _cr_with_template():
    cr = _cr_with_assessment()
    cr["rounds"]["assessment_templates"] = {
        "evaluation_rubric": {
            "rubric_metadata": {"total_possible_points": 100, "passing_threshold_percentage": 70}
        }
    }
    return cr


def test_update_assessment_evaluation_no_instance_400(staff_client, respx_mock):
    respx_mock.get(rest_url("candidate_rounds")).mock(
        return_value=httpx.Response(200, json=[_cr_with_template()])
    )
    respx_mock.get(rest_url("assessment_instances")).mock(
        return_value=httpx.Response(200, json=[])
    )
    resp = staff_client.put(
        f"{ADMIN}/candidate-rounds/{CANDIDATE_ROUND_ID}/assessment-evaluation",
        json={"category_scores": []},
    )
    assert resp.status_code == 400, resp.text


def test_update_assessment_evaluation_success(staff_client, respx_mock):
    respx_mock.get(rest_url("candidate_rounds")).mock(
        return_value=httpx.Response(200, json=[_cr_with_template()])
    )
    respx_mock.get(rest_url("assessment_instances")).mock(
        return_value=httpx.Response(200, json=[{"id": "00000000-0000-0000-0000-0000000000bb"}])
    )
    respx_mock.patch(rest_url("assessment_instances")).mock(
        return_value=httpx.Response(200, json=[])
    )
    respx_mock.patch(rest_url("candidate_rounds")).mock(
        return_value=httpx.Response(200, json=[])
    )
    resp = staff_client.put(
        f"{ADMIN}/candidate-rounds/{CANDIDATE_ROUND_ID}/assessment-evaluation",
        json={
            "category_scores": [
                {
                    "category_name": "Coding",
                    "category_index": 0,
                    "weight_percentage": 100,
                    "criterion_scores": [
                        {
                            "criterion_id": "c1",
                            "criterion_name": "Correctness",
                            "score": 80,
                            "max_points": 100,
                            "level": "good",
                        }
                    ],
                }
            ],
            "round_summary": "ok",
            "round_rating": "hire",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["passed"] is True
    assert body["overall_percentage"] == 80.0


# ── reschedule_assessment 404 / not-assessment ───────────────────────────────

def test_reschedule_assessment_404(staff_client, respx_mock):
    respx_mock.get(rest_url("candidate_rounds")).mock(
        return_value=httpx.Response(200, json=[])
    )
    resp = staff_client.post(
        f"{ADMIN}/candidate-rounds/{CANDIDATE_ROUND_ID}/reschedule-assessment",
        json={},
    )
    assert resp.status_code == 404, resp.text
