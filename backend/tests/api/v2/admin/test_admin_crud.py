"""BE-T1: broad CRUD/read coverage for the admin router surface.

Covers the directly-DB-mockable admin handlers (assessment_templates,
blog_posts, promotions, organizations, users, candidates) on their success and
404/409 paths, complementing the atomicity-focused tests in the sibling files
and the staff-gate audit in test_staff_gate. RPC/service-delegating groups
(requisitions, feedback_jobs, intake_jobs) are covered separately.
"""
import httpx

from tests.helpers.supabase_mocks import rest_url
from tests.helpers.mock_data import (
    ORG_ID,
    REQ_ID,
    ROUND_ID,
    CANDIDATE_ID,
    CANDIDATE_ROUND_ID,
    TEMPLATE_ID,
    RECRUITER_USER_ID,
    NOW,
    make_org,
    make_profile,
    make_requisition,
    make_round,
    make_candidate,
    make_candidate_round,
)

V2_ROOT = "/api/v2"
ADMIN = f"{V2_ROOT}/admin"


def _count(n):
    return httpx.Response(200, headers={"content-range": f"0-0/{n}"}, json=[])


# ── assessment templates ─────────────────────────────────────────────────────

def _template_row(tid=TEMPLATE_ID, status_val="draft"):
    return {
        "id": tid,
        "title": "Frontend Sim",
        "description": "desc",
        "role_seniority": "senior",
        "tools_enabled": ["whiteboard"],
        "time_limit_minutes": 45,
        "task_definition": {"x": 1},
        "evaluation_rubric": {"y": 2},
        "version": "1.0",
        "status": status_val,
        "created_at": NOW,
        "updated_at": NOW,
    }


def test_list_assessment_templates(staff_client, respx_mock):
    respx_mock.get(rest_url("assessment_templates")).mock(
        return_value=httpx.Response(200, json=[_template_row()])
    )
    resp = staff_client.get(f"{ADMIN}/assessment-templates")
    assert resp.status_code == 200, resp.text
    assert resp.json()["total"] == 1


def test_create_assessment_template(staff_client, respx_mock):
    respx_mock.post(rest_url("assessment_templates")).mock(
        return_value=httpx.Response(201, json=[_template_row()])
    )
    resp = staff_client.post(
        f"{ADMIN}/assessment-templates",
        json={
            "title": "Frontend Sim",
            "task_definition": {"x": 1},
            "evaluation_rubric": {"y": 2},
        },
    )
    assert resp.status_code == 201, resp.text


def test_get_assessment_template_404(staff_client, respx_mock):
    respx_mock.get(rest_url("assessment_templates")).mock(
        return_value=httpx.Response(200, json=[])
    )
    resp = staff_client.get(f"{ADMIN}/assessment-templates/{TEMPLATE_ID}")
    assert resp.status_code == 404, resp.text


def test_update_assessment_template_404(staff_client, respx_mock):
    respx_mock.get(rest_url("assessment_templates")).mock(
        return_value=httpx.Response(200, json=[])
    )
    resp = staff_client.put(
        f"{ADMIN}/assessment-templates/{TEMPLATE_ID}", json={"title": "x"}
    )
    assert resp.status_code == 404, resp.text


def test_delete_assessment_template(staff_client, respx_mock):
    respx_mock.get(rest_url("assessment_templates")).mock(
        return_value=httpx.Response(200, json=[_template_row()])
    )
    respx_mock.delete(rest_url("assessment_templates")).mock(
        return_value=httpx.Response(200, json=[])
    )
    resp = staff_client.delete(f"{ADMIN}/assessment-templates/{TEMPLATE_ID}")
    assert resp.status_code == 200, resp.text


# ── blog posts ───────────────────────────────────────────────────────────────

def _blog_row(slug="hello-world"):
    return {
        "id": "00000000-0000-0000-0000-0000000000d1",
        "slug": slug,
        "title": "Hello",
        "excerpt": "ex",
        "content": "body",
        "author_name": "OpenRecruiting Team",
        "tags": [],
        "likes": 0,
        "status": "draft",
        "created_at": NOW,
        "updated_at": NOW,
    }


def test_create_blog_post_conflict(staff_client, respx_mock):
    respx_mock.get(rest_url("blog_posts")).mock(
        return_value=httpx.Response(200, json=[{"id": "x"}])
    )
    resp = staff_client.post(
        f"{ADMIN}/blog-posts",
        json={"title": "Hello", "slug": "hello-world", "excerpt": "e", "content": "c"},
    )
    assert resp.status_code == 409, resp.text


def test_create_blog_post_success(staff_client, respx_mock):
    respx_mock.get(rest_url("blog_posts")).mock(
        return_value=httpx.Response(200, json=[])
    )
    respx_mock.post(rest_url("blog_posts")).mock(
        return_value=httpx.Response(201, json=[_blog_row()])
    )
    resp = staff_client.post(
        f"{ADMIN}/blog-posts",
        json={"title": "Hello", "slug": "hello-world", "excerpt": "e", "content": "c"},
    )
    assert resp.status_code == 201, resp.text


def test_list_blog_posts(staff_client, respx_mock):
    def _blog(request):
        if request.headers.get("Prefer") == "count=exact":
            return _count(1)
        return httpx.Response(200, json=[_blog_row()])

    respx_mock.get(rest_url("blog_posts")).mock(side_effect=_blog)
    resp = staff_client.get(f"{ADMIN}/blog-posts")
    assert resp.status_code == 200, resp.text
    assert resp.json()["total"] == 1


def test_get_blog_post_404(staff_client, respx_mock):
    respx_mock.get(rest_url("blog_posts")).mock(
        return_value=httpx.Response(200, json=[])
    )
    resp = staff_client.get(f"{ADMIN}/blog-posts/missing")
    assert resp.status_code == 404, resp.text


def test_update_blog_post_success(staff_client, respx_mock):
    respx_mock.patch(rest_url("blog_posts")).mock(
        return_value=httpx.Response(200, json=[_blog_row()])
    )
    resp = staff_client.put(
        f"{ADMIN}/blog-posts/hello-world", json={"title": "Updated"}
    )
    assert resp.status_code == 200, resp.text


def test_update_blog_post_slug_conflict(staff_client, respx_mock):
    respx_mock.get(rest_url("blog_posts")).mock(
        return_value=httpx.Response(200, json=[{"id": "other"}])
    )
    resp = staff_client.put(
        f"{ADMIN}/blog-posts/hello-world", json={"slug": "taken-slug"}
    )
    assert resp.status_code == 409, resp.text


def test_update_blog_post_404(staff_client, respx_mock):
    respx_mock.patch(rest_url("blog_posts")).mock(
        return_value=httpx.Response(200, json=[])
    )
    resp = staff_client.put(
        f"{ADMIN}/blog-posts/hello-world", json={"title": "Updated"}
    )
    assert resp.status_code == 404, resp.text


def test_delete_blog_post(staff_client, respx_mock):
    respx_mock.delete(rest_url("blog_posts")).mock(
        return_value=httpx.Response(200, json=[])
    )
    resp = staff_client.delete(f"{ADMIN}/blog-posts/hello-world")
    assert resp.status_code == 200, resp.text


# ── promotions ───────────────────────────────────────────────────────────────

def _promo_row(pid="00000000-0000-0000-0000-0000000000f1", active=True):
    return {
        "id": pid,
        "code": "SAVE20",
        "percent_off": 20,
        "is_active": active,
        "created_at": NOW,
    }


def test_list_promotions(staff_client, respx_mock):
    def _promos(request):
        if request.headers.get("Prefer") == "count=exact":
            return _count(1)
        return httpx.Response(200, json=[_promo_row()])

    respx_mock.get(rest_url("promotions")).mock(side_effect=_promos)
    resp = staff_client.get(f"{ADMIN}/promotions")
    assert resp.status_code == 200, resp.text
    assert resp.json()["total"] == 1


def test_create_promotion_deactivates_others(staff_client, respx_mock):
    respx_mock.patch(rest_url("promotions")).mock(
        return_value=httpx.Response(200, json=[])
    )
    respx_mock.post(rest_url("promotions")).mock(
        return_value=httpx.Response(201, json=[_promo_row()])
    )
    resp = staff_client.post(
        f"{ADMIN}/promotions",
        json={"code": "save20", "percent_off": 20, "is_active": True},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["code"] == "SAVE20"


def test_update_promotion_404(staff_client, respx_mock):
    respx_mock.patch(rest_url("promotions")).mock(
        return_value=httpx.Response(200, json=[])
    )
    resp = staff_client.put(
        f"{ADMIN}/promotions/00000000-0000-0000-0000-0000000000f1",
        json={"percent_off": 30},
    )
    assert resp.status_code == 404, resp.text


def test_delete_promotion(staff_client, respx_mock):
    respx_mock.delete(rest_url("promotions")).mock(
        return_value=httpx.Response(200, json=[])
    )
    resp = staff_client.delete(
        f"{ADMIN}/promotions/00000000-0000-0000-0000-0000000000f1"
    )
    assert resp.status_code == 200, resp.text


# ── organizations CRUD / reads ───────────────────────────────────────────────

def test_create_organization(staff_client, respx_mock):
    respx_mock.post(rest_url("organizations")).mock(
        return_value=httpx.Response(201, json=[make_org()])
    )
    resp = staff_client.post(
        f"{ADMIN}/organizations", json={"name": "Acme", "domain": "acme.com"}
    )
    assert resp.status_code == 201, resp.text


def test_list_organizations(staff_client, respx_mock):
    def _orgs(request):
        if request.headers.get("Prefer") == "count=exact":
            return _count(1)
        return httpx.Response(200, json=[make_org()])

    respx_mock.get(rest_url("organizations")).mock(side_effect=_orgs)
    resp = staff_client.get(f"{ADMIN}/organizations")
    assert resp.status_code == 200, resp.text
    assert resp.json()["total"] == 1


def test_list_archived_organizations(staff_client, respx_mock):
    respx_mock.get(rest_url("organizations")).mock(
        return_value=httpx.Response(200, json=[make_org(deleted_at=NOW)])
    )
    resp = staff_client.get(f"{ADMIN}/organizations/archived")
    assert resp.status_code == 200, resp.text


def test_get_organization_404(staff_client, respx_mock):
    respx_mock.get(rest_url("organizations")).mock(
        return_value=httpx.Response(200, json=[])
    )
    resp = staff_client.get(f"{ADMIN}/organizations/{ORG_ID}")
    assert resp.status_code == 404, resp.text


def test_update_org_calendar_settings(staff_client, respx_mock):
    respx_mock.patch(rest_url("organizations")).mock(
        return_value=httpx.Response(200, json=[make_org()])
    )
    resp = staff_client.patch(
        f"{ADMIN}/organizations/{ORG_ID}/calendar-intelligence",
        json={"auto_join_enabled": True},
    )
    assert resp.status_code == 200, resp.text


def test_update_org_calendar_settings_no_fields(staff_client, respx_mock):
    resp = staff_client.patch(
        f"{ADMIN}/organizations/{ORG_ID}/calendar-intelligence", json={}
    )
    assert resp.status_code == 400, resp.text


def test_list_org_slack_connections(staff_client, respx_mock):
    respx_mock.get(rest_url("slack_connections")).mock(
        return_value=httpx.Response(200, json=[])
    )
    resp = staff_client.get(f"{ADMIN}/organizations/{ORG_ID}/slack-connections")
    assert resp.status_code == 200, resp.text
    assert resp.json() == []


def test_update_org_slack_features(staff_client, respx_mock):
    def _orgs(request):
        if request.method == "GET":
            return httpx.Response(200, json=[{"slack_features": None}])
        return httpx.Response(200, json=[make_org()])

    respx_mock.get(rest_url("organizations")).mock(side_effect=_orgs)
    respx_mock.patch(rest_url("organizations")).mock(
        return_value=httpx.Response(200, json=[make_org()])
    )
    resp = staff_client.patch(
        f"{ADMIN}/organizations/{ORG_ID}/slack-features",
        json={"assistant_read": True},
    )
    assert resp.status_code == 200, resp.text


def test_update_org_slack_features_404(staff_client, respx_mock):
    respx_mock.get(rest_url("organizations")).mock(
        return_value=httpx.Response(200, json=[])
    )
    resp = staff_client.patch(
        f"{ADMIN}/organizations/{ORG_ID}/slack-features",
        json={"assistant_read": True},
    )
    assert resp.status_code == 404, resp.text


def test_update_user_slack_features(staff_client, respx_mock):
    respx_mock.get(rest_url("slack_connections")).mock(
        return_value=httpx.Response(
            200, json=[{"id": "conn-1", "user_slack_features": {}}]
        )
    )
    respx_mock.patch(rest_url("slack_connections")).mock(
        return_value=httpx.Response(200, json=[{"id": "conn-1"}])
    )
    resp = staff_client.patch(
        f"{ADMIN}/organizations/{ORG_ID}/users/{RECRUITER_USER_ID}/slack-features",
        json={"calendar_notifications": False},
    )
    assert resp.status_code == 200, resp.text


def test_update_user_slack_features_404(staff_client, respx_mock):
    respx_mock.get(rest_url("slack_connections")).mock(
        return_value=httpx.Response(200, json=[])
    )
    resp = staff_client.patch(
        f"{ADMIN}/organizations/{ORG_ID}/users/{RECRUITER_USER_ID}/slack-features",
        json={"calendar_notifications": False},
    )
    assert resp.status_code == 404, resp.text


def test_reset_user_slack_features(staff_client, respx_mock):
    respx_mock.patch(rest_url("slack_connections")).mock(
        return_value=httpx.Response(200, json=[{"id": "conn-1"}])
    )
    resp = staff_client.delete(
        f"{ADMIN}/organizations/{ORG_ID}/users/{RECRUITER_USER_ID}/slack-features"
    )
    assert resp.status_code == 200, resp.text


def test_reset_user_slack_features_404(staff_client, respx_mock):
    respx_mock.patch(rest_url("slack_connections")).mock(
        return_value=httpx.Response(200, json=[])
    )
    resp = staff_client.delete(
        f"{ADMIN}/organizations/{ORG_ID}/users/{RECRUITER_USER_ID}/slack-features"
    )
    assert resp.status_code == 404, resp.text


# ── users list / delete / restore ────────────────────────────────────────────

def test_list_users(staff_client, respx_mock):
    def _profiles(request):
        if request.headers.get("Prefer") == "count=exact":
            return _count(1)
        return httpx.Response(200, json=[make_profile()])

    respx_mock.get(rest_url("profiles")).mock(side_effect=_profiles)
    resp = staff_client.get(f"{ADMIN}/users")
    assert resp.status_code == 200, resp.text
    assert resp.json()["total"] == 1


def test_delete_user_success(staff_client, respx_mock):
    respx_mock.get(rest_url("profiles")).mock(
        return_value=httpx.Response(
            200, json=[{"id": CANDIDATE_ID, "email": "u@t.com", "is_staff": False, "deleted_at": None}]
        )
    )
    respx_mock.put(
        url__regex=r"http://test-supabase.local/auth/v1/admin/users/.*"
    ).mock(return_value=httpx.Response(200, json={}))
    respx_mock.patch(rest_url("profiles")).mock(
        return_value=httpx.Response(200, json=[])
    )
    resp = staff_client.delete(f"{ADMIN}/users/{CANDIDATE_ID}")
    assert resp.status_code == 200, resp.text


def test_delete_user_staff_forbidden(staff_client, respx_mock):
    respx_mock.get(rest_url("profiles")).mock(
        return_value=httpx.Response(
            200, json=[{"id": CANDIDATE_ID, "email": "u@t.com", "is_staff": True, "deleted_at": None}]
        )
    )
    resp = staff_client.delete(f"{ADMIN}/users/{CANDIDATE_ID}")
    assert resp.status_code == 403, resp.text


def test_delete_user_already_deleted(staff_client, respx_mock):
    respx_mock.get(rest_url("profiles")).mock(
        return_value=httpx.Response(
            200, json=[{"id": CANDIDATE_ID, "email": "u@t.com", "is_staff": False, "deleted_at": NOW}]
        )
    )
    resp = staff_client.delete(f"{ADMIN}/users/{CANDIDATE_ID}")
    assert resp.status_code == 400, resp.text


def test_restore_user_success(staff_client, respx_mock):
    respx_mock.get(rest_url("profiles")).mock(
        return_value=httpx.Response(
            200, json=[{"id": CANDIDATE_ID, "email": "u@t.com", "deleted_at": NOW}]
        )
    )
    respx_mock.put(
        url__regex=r"http://test-supabase.local/auth/v1/admin/users/.*"
    ).mock(return_value=httpx.Response(200, json={}))
    respx_mock.patch(rest_url("profiles")).mock(
        return_value=httpx.Response(200, json=[])
    )
    resp = staff_client.post(f"{ADMIN}/users/{CANDIDATE_ID}/restore")
    assert resp.status_code == 200, resp.text


def test_restore_user_not_deleted(staff_client, respx_mock):
    respx_mock.get(rest_url("profiles")).mock(
        return_value=httpx.Response(
            200, json=[{"id": CANDIDATE_ID, "email": "u@t.com", "deleted_at": None}]
        )
    )
    resp = staff_client.post(f"{ADMIN}/users/{CANDIDATE_ID}/restore")
    assert resp.status_code == 400, resp.text


def test_list_deleted_org_users(staff_client, respx_mock):
    respx_mock.get(rest_url("profiles")).mock(
        return_value=httpx.Response(200, json=[make_profile(deleted_at=NOW)])
    )
    resp = staff_client.get(f"{ADMIN}/organizations/{ORG_ID}/users/deleted")
    assert resp.status_code == 200, resp.text


# ── candidates add / list / status / delete ─────────────────────────────────

def test_add_candidate_no_plan_400(staff_client, respx_mock):
    def _req(request):
        return httpx.Response(200, json=[make_requisition()])

    def _rounds(request):
        return httpx.Response(200, json=[])

    respx_mock.get(rest_url("requisitions")).mock(side_effect=_req)
    respx_mock.get(rest_url("rounds")).mock(side_effect=_rounds)

    resp = staff_client.post(
        f"{ADMIN}/requisitions/{REQ_ID}/candidates",
        json={"name": "Jane", "email": "jane@x.com"},
    )
    assert resp.status_code == 400, resp.text
    assert "interview plan" in resp.text.lower()


def test_add_candidate_req_not_found_404(staff_client, respx_mock):
    respx_mock.get(rest_url("requisitions")).mock(
        return_value=httpx.Response(200, json=[])
    )
    respx_mock.get(rest_url("rounds")).mock(
        return_value=httpx.Response(200, json=[])
    )
    resp = staff_client.post(
        f"{ADMIN}/requisitions/{REQ_ID}/candidates",
        json={"name": "Jane", "email": "jane@x.com"},
    )
    assert resp.status_code == 404, resp.text


def test_list_candidates_empty(staff_client, respx_mock):
    respx_mock.get(rest_url("requisitions")).mock(
        return_value=httpx.Response(200, json=[make_requisition()])
    )
    respx_mock.get(rest_url("candidates")).mock(
        return_value=httpx.Response(200, json=[])
    )
    respx_mock.get(rest_url("rounds")).mock(
        return_value=httpx.Response(200, json=[make_round()])
    )
    resp = staff_client.get(f"{ADMIN}/requisitions/{REQ_ID}/candidates")
    assert resp.status_code == 200, resp.text
    assert resp.json()["total"] == 0


def test_update_candidate_status_404(staff_client, respx_mock):
    respx_mock.get(rest_url("candidates")).mock(
        return_value=httpx.Response(200, json=[])
    )
    resp = staff_client.put(
        f"{ADMIN}/candidates/{CANDIDATE_ID}/status", json={"status": "hired"}
    )
    assert resp.status_code == 404, resp.text


def test_update_candidate_status_success(staff_client, respx_mock):
    respx_mock.get(rest_url("candidates")).mock(
        return_value=httpx.Response(200, json=[{"id": CANDIDATE_ID}])
    )
    respx_mock.patch(rest_url("candidates")).mock(
        return_value=httpx.Response(200, json=[make_candidate(status="hired")])
    )
    resp = staff_client.put(
        f"{ADMIN}/candidates/{CANDIDATE_ID}/status",
        json={"status": "hired", "final_verdict": "hire"},
    )
    assert resp.status_code == 200, resp.text


def test_delete_candidate_success(staff_client, respx_mock):
    respx_mock.get(rest_url("candidates")).mock(
        return_value=httpx.Response(200, json=[{"id": CANDIDATE_ID}])
    )
    respx_mock.patch(rest_url("candidates")).mock(
        return_value=httpx.Response(200, json=[])
    )
    resp = staff_client.delete(f"{ADMIN}/candidates/{CANDIDATE_ID}")
    assert resp.status_code == 200, resp.text


def test_delete_candidate_404(staff_client, respx_mock):
    respx_mock.get(rest_url("candidates")).mock(
        return_value=httpx.Response(200, json=[])
    )
    resp = staff_client.delete(f"{ADMIN}/candidates/{CANDIDATE_ID}")
    assert resp.status_code == 404, resp.text
