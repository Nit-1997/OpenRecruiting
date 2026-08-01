from uuid import UUID
from datetime import datetime, timezone

STAFF_USER_ID = "00000000-0000-0000-0000-000000000001"
STAFF_EMAIL = "staff@example.com"

RECRUITER_USER_ID = "00000000-0000-0000-0000-000000000002"
RECRUITER_EMAIL = "recruiter@test.com"

ORG_ID = "00000000-0000-0000-0000-000000000010"
ORG_2_ID = "00000000-0000-0000-0000-000000000011"

REQ_ID = "00000000-0000-0000-0000-000000000020"
ROUND_ID = "00000000-0000-0000-0000-000000000030"
ROUND_2_ID = "00000000-0000-0000-0000-000000000031"
CANDIDATE_ID = "00000000-0000-0000-0000-000000000040"
CANDIDATE_ROUND_ID = "00000000-0000-0000-0000-000000000050"
FEEDBACK_QUESTION_ID = "00000000-0000-0000-0000-000000000060"
TEMPLATE_ID = "00000000-0000-0000-0000-000000000070"
INSTANCE_ID = "00000000-0000-0000-0000-000000000080"
BOT_ID = "00000000-0000-0000-0000-000000000090"
FEEDBACK_ID = "00000000-0000-0000-0000-000000000091"
FEEDBACK_TOKEN_ID = "00000000-0000-0000-0000-0000000000a0"

NOW = "2025-01-15T10:00:00+00:00"


def make_org(org_id=ORG_ID, name="Test Org", domain="test.com", deleted_at=None):
    return {
        "id": org_id,
        "name": name,
        "domain": domain,
        "description": None,
        "created_at": NOW,
        "updated_at": NOW,
        "deleted_at": deleted_at,
    }


def make_profile(
    user_id=RECRUITER_USER_ID,
    email=RECRUITER_EMAIL,
    org_id=ORG_ID,
    is_staff=False,
    full_name="Test Recruiter",
    role="recruiter",
    deleted_at=None,
):
    return {
        "id": user_id,
        "email": email,
        "full_name": full_name,
        "organization_id": org_id,
        "role": role,
        "is_staff": is_staff,
        "created_at": NOW,
        "updated_at": NOW,
        "invitation_status": "accepted",
        "invitation_sent_at": NOW,
        "deleted_at": deleted_at,
    }


def make_requisition(req_id=REQ_ID, org_id=ORG_ID, status="open", deleted_at=None):
    return {
        "id": req_id,
        "organization_id": org_id,
        "created_by": RECRUITER_USER_ID,
        "role_title": "Software Engineer",
        "role_location": "Remote",
        "experience_min_years": 3,
        "experience_max_years": 5,
        "experience_display": "3-5 years",
        "status": status,
        "intake_notes": None,
        "job_description": None,
        "must_have_skills": [],
        "good_to_have_skills": [],
        "created_at": NOW,
        "updated_at": NOW,
        "deleted_at": deleted_at,
    }


def make_round(round_id=ROUND_ID, req_id=REQ_ID, round_number=1, name="Technical"):
    return {
        "id": round_id,
        "requisition_id": req_id,
        "round_number": round_number,
        "name": name,
        "category": "coding",
        "duration_minutes": 45,
        "duration_display": "45 mins",
        "description": "Technical interview",
        "skills": ["Python", "SQL"],
        "guidelines": [],
        "round_type": "interview",
        "assessment_template_id": None,
        "created_at": NOW,
        "updated_at": NOW,
    }


def make_feedback_question(fq_id=FEEDBACK_QUESTION_ID, round_id=ROUND_ID, num=1):
    return {
        "id": fq_id,
        "round_id": round_id,
        "question_number": num,
        "heading": "Problem Solving",
        "description": "Evaluate problem solving skills",
        "created_at": NOW,
        "updated_at": NOW,
    }


def make_candidate(cand_id=CANDIDATE_ID, req_id=REQ_ID, status="active"):
    return {
        "id": cand_id,
        "requisition_id": req_id,
        "name": "John Doe",
        "email": "john@example.com",
        "phone": None,
        "resume_url": None,
        "status": status,
        "final_verdict": None,
        "created_at": NOW,
        "updated_at": NOW,
    }


def make_candidate_round(
    cr_id=CANDIDATE_ROUND_ID,
    cand_id=CANDIDATE_ID,
    round_id=ROUND_ID,
    status="pending",
):
    return {
        "id": cr_id,
        "candidate_id": cand_id,
        "round_id": round_id,
        "round_name": "Technical",
        "round_number": 1,
        "status": status,
        "scheduled_at": None,
        "completed_at": None,
        "outcome": None,
        "outcome_notes": None,
        "bot_session_id": None,
        "transcript_url": None,
        "recording_url": None,
        "meeting_url": None,
        "interviewer_email": None,
        "created_at": NOW,
        "updated_at": NOW,
        "round_type": "interview",
        "can_reschedule": None,
    }


def make_assessment_template(tmpl_id=TEMPLATE_ID, status="active"):
    return {
        "id": tmpl_id,
        "name": "React Assessment",
        "description": "React coding assessment",
        "category": "frontend",
        "difficulty": "medium",
        "duration_minutes": 60,
        "status": status,
        "content": {"tasks": []},
        "created_at": NOW,
        "updated_at": NOW,
    }


def make_recall_bot(
    bot_id=BOT_ID,
    cr_id=CANDIDATE_ROUND_ID,
    status="in_call_recording",
    feedback_status=None,
    voice_session_token=None,
    voice_session_status="dormant",
    detection_completed=False,
    detected_candidate_participant_id=None,
    detection_confidence=0,
    tracked_participants=None,
):
    return {
        "id": bot_id,
        "candidate_round_id": cr_id,
        "recall_bot_id": "recall-bot-ext-123",
        "meeting_url": "https://zoom.us/j/123",
        "status": status,
        "candidate_name": "John Doe",
        "tracked_participants": tracked_participants,
        "feedback_status": feedback_status,
        "voice_session_token": voice_session_token,
        "voice_session_status": voice_session_status,
        "detection_completed": detection_completed,
        "detected_candidate_participant_id": detected_candidate_participant_id,
        "detection_confidence": detection_confidence,
        "created_at": NOW,
        "updated_at": NOW,
    }


def make_tracked_participant(pid, name, is_host=False, is_tenant=None, left_at=None, platform="zoom"):
    p = {
        "id": pid,
        "name": name,
        "is_host": is_host,
        "platform": platform,
        "extra_data": {},
        "email": f"{name.lower().replace(' ', '.')}@test.com",
        "joined_at": NOW,
        "left_at": left_at,
    }
    if is_tenant is not None:
        p["is_tenant"] = is_tenant
    return p


def make_feedback_access_token(token_id=FEEDBACK_TOKEN_ID, cr_id=CANDIDATE_ROUND_ID):
    return {
        "id": token_id,
        "token": "test-feedback-token-abc",
        "candidate_round_id": cr_id,
        "interviewer_email": "interviewer@test.com",
        "is_registered_user": False,
        "otp_code": None,
        "otp_expires_at": None,
        "otp_attempts": 0,
        "otp_locked_until": None,
        "session_expires_at": None,
        "created_at": NOW,
        "updated_at": NOW,
    }


TRANSCRIPT_ID = "00000000-0000-0000-0000-0000000000b0"


def make_assessment_instance(
    instance_id=INSTANCE_ID,
    template_id=TEMPLATE_ID,
    cand_id=CANDIDATE_ID,
    round_id=ROUND_ID,
    status="pending",
):
    return {
        "id": instance_id,
        "template_id": template_id,
        "candidate_id": cand_id,
        "candidate_email": "john@example.com",
        "candidate_name": "John Doe",
        "access_code": "ABCD1234",
        "access_code_hash": "fakehash",
        "access_code_expires_at": NOW,
        "status": status,
        "expires_at": NOW,
        "round_id": round_id,
        "started_at": None,
        "submitted_at": None,
        "submission_data": None,
        "work_data": None,
        "evaluation_result": None,
        "evaluation_notes": None,
        "evaluated_at": None,
        "created_at": NOW,
        "updated_at": NOW,
    }


def make_transcript(
    transcript_id=TRANSCRIPT_ID,
    cr_id=CANDIDATE_ROUND_ID,
    segments=None,
    feedback_transcript=None,
):
    return {
        "id": transcript_id,
        "candidate_round_id": cr_id,
        "segments": segments,
        "feedback_transcript": feedback_transcript,
        "duration_seconds": 1800,
        "created_at": NOW,
        "updated_at": NOW,
    }
