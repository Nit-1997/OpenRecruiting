from app.integrations.ats.passthrough.ashby.mapping import (
    candidate_from_info, attachment_from_handle, application_from_infos,
)


def test_candidate_from_info_maps_structured_fields():
    results = {
        "name": "Jenna Jacobs",
        "primaryEmailAddress": {"value": "j@example.com"},
        "emailAddresses": [{"value": "j@example.com", "type": "Personal"}],
        "phoneNumbers": [{"value": "+1 555", "type": "Personal"}],
        "socialLinks": [{"type": "LinkedIn", "url": "https://linkedin.com/in/j"}],
        "position": "Backend Engineer", "company": "Auction.com", "school": "Yale",
    }
    c = candidate_from_info("cand-1", results)
    assert c.id == "cand-1"
    assert c.first_name == "Jenna" and c.last_name == "Jacobs"
    assert c.emails[0].value == "j@example.com"
    assert c.phones[0].value == "+1 555"
    assert c.links == ["https://linkedin.com/in/j"]
    assert c.social_links == ["https://linkedin.com/in/j"]
    assert c.position == "Backend Engineer" and c.company == "Auction.com" and c.school == "Yale"


def test_application_from_infos_assembles_resume_and_stage():
    cand_results = {"name": "Jenna Jacobs", "emailAddresses": [{"value": "j@example.com"}]}
    app_results = {"status": "ACTIVE", "currentInterviewStage": {"id": "s1", "title": "Recruiter Screen"},
                   "info": {"appliedAt": "2026-06-13T00:00:00Z", "jobId": "job-1"}}
    app = application_from_infos("app-1", cand_results, app_results, resume_url="https://s3/x.pdf", resume_name="r.pdf")
    assert app.id == "app-1" and app.status == "ACTIVE" and app.job_id == "job-1"
    assert app.current_stage.name == "Recruiter Screen"
    assert app.applied_at == "2026-06-13T00:00:00Z"
    assert app.attachments[0].type == "RESUME" and app.attachments[0].url == "https://s3/x.pdf"


def test_split_name_blank_does_not_crash():
    c = candidate_from_info("cand-x", {"name": "   "})
    assert c.first_name is None and c.last_name is None


def test_application_from_infos_handles_null_info_and_no_resume():
    # app_results with explicit null `info` must not crash; no resume → no attachment.
    app = application_from_infos("app-9", {"name": "X", "id": "cand-9"}, {"info": None},
                                 resume_url=None, resume_name=None)
    assert app.id == "app-9"
    assert app.candidate.id == "cand-9"
    assert app.attachments == []
    assert app.status == "ACTIVE"


def test_application_from_infos_non_dict_stage_is_none():
    app = application_from_infos("app-1", {"name": "Y"}, {"currentInterviewStageId": "s1"},
                                 resume_url=None, resume_name=None)
    assert app.current_stage is None


def test_candidate_from_info_tolerates_dirty_social_links():
    c = candidate_from_info("cand-x", {"name": "X Y",
        "socialLinks": ["bad", None, {"type": "LinkedIn", "url": "https://ok"}]})
    assert c.links == ["https://ok"]
