import asyncio
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import HTTPException, status

from app.models.requisitions import (
    RequisitionCreate,
    RequisitionUpdate,
    IntakeUpdate,
    InterviewPlanCreate,
    RoundCreate,
    RoundUpdate,
    FeedbackQuestionCreate,
    FeedbackQuestionUpdate,
    RoundReorderRequest,
    format_experience,
    format_duration,
)
from app.services.supabase import get_supabase_admin_client, insert_many
from app.api.v2.core.rpc import call_rpc


def build_requisition_response(req: dict) -> dict:
    return {
        **req,
        "experience_display": format_experience(
            req.get("experience_min_years", 0),
            req.get("experience_max_years")
        ),
        "must_have_skills": req.get("must_have_skills") or [],
        "good_to_have_skills": req.get("good_to_have_skills") or [],
        "auto_join_untracked": req.get("auto_join_untracked"),
    }


def build_round_response(round_data: dict) -> dict:
    return {
        **round_data,
        "duration_display": format_duration(round_data.get("duration_minutes", 45)),
        "skills": round_data.get("skills") or [],
        "guidelines": round_data.get("guidelines") or [],
    }


def build_question_response(question: dict) -> dict:
    return {**question}


class RequisitionService:
    def __init__(self, supabase):
        self.supabase = supabase

    async def _attach_org_untracked_flag(self, req: dict) -> dict:
        org_id = req.get("organization_id")
        if not org_id:
            return req

        org_result = await self.supabase.table("organizations") \
            .select("auto_join_untracked") \
            .eq("id", org_id) \
            .limit(1) \
            .execute_async()

        org_row = org_result.data[0] if isinstance(org_result.data, list) and org_result.data else None
        req["auto_join_untracked"] = bool(org_row.get("auto_join_untracked")) if org_row else False
        return req

    def _req_query(self, req_id: str, org_id: str | None = None):
        q = self.supabase.table("requisitions").select("*").eq("id", req_id).is_null("deleted_at").is_("is_system_template", "false")
        if org_id:
            q = q.eq("organization_id", org_id)
        return q

    async def get_requisition(self, req_id: str, org_id: str | None = None) -> dict:
        result = await self._req_query(req_id, org_id).single().execute_async()
        if not result.data:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Requisition not found")
        req_data = await self._attach_org_untracked_flag(result.data)
        return build_requisition_response(req_data)

    async def list_requisitions(self, org_id: str, include_deleted: bool = False, page: int = 1, page_size: int = 25) -> tuple[list, int]:
        list_columns = "id,organization_id,role_title,role_location,experience_min_years,experience_max_years,status,must_have_skills,good_to_have_skills,created_at,updated_at,deleted_at,created_by"
        q = self.supabase.table("requisitions").select(list_columns).eq("organization_id", org_id).is_("is_system_template", "false")
        count_q = self.supabase.table("requisitions").select("id").eq("organization_id", org_id).is_("is_system_template", "false")
        if include_deleted:
            q = q.not_null("deleted_at")
            count_q = count_q.not_null("deleted_at")
        else:
            q = q.is_null("deleted_at")
            count_q = count_q.is_null("deleted_at")

        offset = (page - 1) * page_size
        q = q.order("created_at", desc=True).limit(page_size).offset(offset)

        result, total = await asyncio.gather(
            q.execute_async(),
            count_q.count_async(),
        )
        requisitions = result.data if isinstance(result.data, list) else [result.data] if result.data else []
        return [build_requisition_response(r) for r in requisitions], total

    async def get_requisition_with_plan(self, req_id: str, org_id: str | None = None) -> dict:
        req_q = self.supabase.table("requisitions").select("*").eq("id", req_id).is_null("deleted_at").is_("is_system_template", "false")
        if org_id:
            req_q = req_q.eq("organization_id", org_id)

        req_result, rounds_result = await asyncio.gather(
            req_q.single().execute_async(),
            self.supabase.table("rounds").select("*").eq("requisition_id", req_id).is_null("deleted_at").execute_async()
        )

        if not req_result.data:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Requisition not found")

        rounds = rounds_result.data if isinstance(rounds_result.data, list) else [rounds_result.data] if rounds_result.data else []
        rounds = sorted(rounds, key=lambda r: r.get("round_number", 0))

        round_ids = [r["id"] for r in rounds]
        questions_by_round: dict[str, list] = {}
        if round_ids:
            all_q_result = await self.supabase.table("feedback_questions").select("*").in_("round_id", round_ids).is_null("deleted_at").execute_async()
            for q in (all_q_result.data or []):
                questions_by_round.setdefault(q["round_id"], []).append(q)
            for rid in questions_by_round:
                questions_by_round[rid] = sorted(questions_by_round[rid], key=lambda q: q.get("question_number", 0))

        rounds_with_questions = []
        total_duration = 0
        for round_data in rounds:
            questions = questions_by_round.get(round_data["id"], [])
            rr = build_round_response(round_data)
            rr["feedback_questions"] = [build_question_response(q) for q in questions]
            rounds_with_questions.append(rr)
            total_duration += round_data.get("duration_minutes", 0)

        req_data = await self._attach_org_untracked_flag(req_result.data)
        req_response = build_requisition_response(req_data)
        plan = None
        if rounds_with_questions:
            plan = {
                "requisition_id": req_id,
                "total_rounds": len(rounds_with_questions),
                "total_duration_minutes": total_duration,
                "total_duration_display": format_duration(total_duration),
                "rounds": rounds_with_questions,
            }
        req_response["plan"] = plan
        return req_response

    async def get_interview_plan(self, req_id: str, org_id: str | None = None) -> dict:
        req_q = self.supabase.table("requisitions").select("id").eq("id", req_id).is_null("deleted_at").is_("is_system_template", "false")
        if org_id:
            req_q = req_q.eq("organization_id", org_id)

        req_result, rounds_result = await asyncio.gather(
            req_q.single().execute_async(),
            self.supabase.table("rounds").select("*").eq("requisition_id", req_id).is_null("deleted_at").execute_async()
        )

        if not req_result.data:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Requisition not found")

        rounds = rounds_result.data if isinstance(rounds_result.data, list) else [rounds_result.data] if rounds_result.data else []
        rounds = sorted(rounds, key=lambda r: r.get("round_number", 0))

        if not rounds:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "No interview plan found for this requisition")

        round_ids = [r["id"] for r in rounds]
        questions_by_round: dict[str, list] = {}
        if round_ids:
            all_q_result = await self.supabase.table("feedback_questions").select("*").in_("round_id", round_ids).is_null("deleted_at").execute_async()
            for q in (all_q_result.data or []):
                questions_by_round.setdefault(q["round_id"], []).append(q)
            for rid in questions_by_round:
                questions_by_round[rid] = sorted(questions_by_round[rid], key=lambda q: q.get("question_number", 0))

        assessment_template_ids = [r.get("assessment_template_id") for r in rounds if r.get("assessment_template_id")]
        templates_by_id = {}
        if assessment_template_ids:
            templates_result = await self.supabase.table("assessment_templates").select("*").in_("id", assessment_template_ids).execute_async()
            templates = templates_result.data if isinstance(templates_result.data, list) else [templates_result.data] if templates_result.data else []
            templates_by_id = {t["id"]: t for t in templates}

        rounds_with_questions = []
        total_duration = 0
        for idx, round_data in enumerate(rounds):
            questions = questions_by_round.get(round_data["id"], [])
            rr = build_round_response(round_data)
            rr["feedback_questions"] = [build_question_response(q) for q in questions]
            rr["round_number"] = idx + 1
            template_id = round_data.get("assessment_template_id")
            if template_id and template_id in templates_by_id:
                rr["assessment_template"] = templates_by_id[template_id]
            rounds_with_questions.append(rr)
            total_duration += round_data.get("duration_minutes", 0)

        return {
            "requisition_id": req_id,
            "total_rounds": len(rounds_with_questions),
            "total_duration_minutes": total_duration,
            "total_duration_display": format_duration(total_duration),
            "rounds": rounds_with_questions,
        }

    async def create_requisition(self, org_id: str, data: RequisitionCreate, created_by: str) -> dict:
        insert_data = {
            "organization_id": org_id,
            "created_by": created_by,
            "role_title": data.role_title,
            "role_location": data.role_location,
            "experience_min_years": data.experience_min_years,
            "experience_max_years": data.experience_max_years,
            "status": "intake_pending",
        }
        result = await self.supabase.table("requisitions").insert(insert_data).execute_async()
        if not result.data:
            raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Failed to create requisition")
        req_data = result.data[0] if isinstance(result.data, list) else result.data
        return build_requisition_response(req_data)

    async def update_requisition(self, req_id: str, data: RequisitionUpdate, org_id: str | None = None) -> dict:
        existing = await self._req_query(req_id, org_id).single().execute_async()
        if not existing.data:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Requisition not found")

        update_data = {}
        if data.role_title is not None:
            update_data["role_title"] = data.role_title
        if data.role_location is not None:
            update_data["role_location"] = data.role_location
        if data.experience_min_years is not None:
            update_data["experience_min_years"] = data.experience_min_years
        if data.experience_max_years is not None:
            update_data["experience_max_years"] = data.experience_max_years

        if not update_data:
            return build_requisition_response(existing.data)

        result = await self.supabase.table("requisitions").update(update_data).eq("id", req_id).execute_async()
        if not result.data:
            raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Failed to update requisition")
        req_data = result.data[0] if isinstance(result.data, list) else result.data
        return build_requisition_response(req_data)

    async def update_intake(self, req_id: str, data: IntakeUpdate, org_id: str | None = None) -> dict:
        existing = await self._req_query(req_id, org_id).single().execute_async()
        if not existing.data:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Requisition not found")

        update_data = {}
        if data.intake_notes is not None:
            update_data["intake_notes"] = data.intake_notes
        if data.job_description is not None:
            update_data["job_description"] = data.job_description
        if data.must_have_skills is not None:
            update_data["must_have_skills"] = data.must_have_skills
        if data.good_to_have_skills is not None:
            update_data["good_to_have_skills"] = data.good_to_have_skills

        if not update_data:
            return build_requisition_response(existing.data)

        result = await self.supabase.table("requisitions").update(update_data).eq("id", req_id).execute_async()
        if not result.data:
            raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Failed to update intake")
        req_data = result.data[0] if isinstance(result.data, list) else result.data
        return build_requisition_response(req_data)

    async def update_status(self, req_id: str, new_status: str, org_id: str | None = None, allowed_statuses: list[str] | None = None) -> dict:
        if allowed_statuses and new_status not in allowed_statuses:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Invalid status. Must be one of: {', '.join(allowed_statuses)}")

        existing = await self._req_query(req_id, org_id).single().execute_async()
        if not existing.data:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Requisition not found")

        result = await self.supabase.table("requisitions").update({"status": new_status}).eq("id", req_id).execute_async()
        if not result.data:
            raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Failed to update status")
        req_data = result.data[0] if isinstance(result.data, list) else result.data

        if new_status == "planned":
            try:
                from app.services.sqs_publisher import publish_event
                org_id = req_data.get("organization_id") or existing.data.get("organization_id", "")
                await publish_event("intake_complete", {
                    "requisition_id": req_id,
                    "organization_id": str(org_id),
                })
            except Exception:
                pass

        return build_requisition_response(req_data)

    async def get_intake_status(self, req_id: str, org_id: str | None = None) -> dict:
        query = self._req_query(req_id, org_id).select(
            "id, intake_voice_session_status, intake_processing_status, intake_summary, intake_transcript"
        )
        result = await query.single().execute_async()
        if not result.data:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Requisition not found")
        return {
            "requisition_id": req_id,
            "intake_voice_session_status": result.data.get("intake_voice_session_status"),
            "intake_processing_status": result.data.get("intake_processing_status"),
            "intake_summary": result.data.get("intake_summary"),
            "has_transcript": bool(result.data.get("intake_transcript")),
        }

    async def create_intake_call_session(self, req_id: str, org_id: str | None = None) -> dict:
        existing = await self._req_query(req_id, org_id).single().execute_async()
        if not existing.data:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Requisition not found")

        if existing.data.get("status") == "active":
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Cannot start intake call for an active requisition")

        await self.delete_rounds_cascade(req_id)

        session_token = str(uuid4())
        result = await self.supabase.table("requisitions").update({
            "intake_voice_session_token": session_token,
            "intake_voice_session_status": "pending",
            "intake_processing_status": None,
            "intake_processing_error": None,
            "intake_transcript": None,
        }).eq("id", req_id).execute_async()

        if not result.data:
            raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Failed to create intake call session")

        return {"session_token": session_token, "requisition_id": req_id}

    async def soft_delete_requisition(self, req_id: str) -> dict:
        existing = await self.supabase.table("requisitions").select("id, deleted_at").eq("id", req_id).single().execute_async()
        if not existing.data:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Requisition not found")
        if existing.data.get("deleted_at"):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Requisition is already deleted")

        deleted_at = datetime.now(timezone.utc).isoformat()

        rounds_result = await self.supabase.table("rounds").select("id").eq("requisition_id", req_id).is_null("deleted_at").execute_async()
        round_ids = [r["id"] for r in (rounds_result.data or [])]

        update_tasks = [
            self.supabase.table("feedback_questions").update({"deleted_at": deleted_at}).eq("round_id", rid).execute_async()
            for rid in round_ids
        ]
        if update_tasks:
            await asyncio.gather(*update_tasks)

        await asyncio.gather(
            self.supabase.table("rounds").update({"deleted_at": deleted_at}).eq("requisition_id", req_id).execute_async(),
            self.supabase.table("candidates").update({"deleted_at": deleted_at}).eq("requisition_id", req_id).execute_async(),
            self.supabase.table("requisitions").update({"deleted_at": deleted_at}).eq("id", req_id).execute_async(),
        )
        return {"message": "Requisition deleted successfully", "id": req_id}

    async def restore_requisition(self, req_id: str) -> dict:
        existing = await self.supabase.table("requisitions").select("id, deleted_at").eq("id", req_id).single().execute_async()
        if not existing.data:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Requisition not found")
        if not existing.data.get("deleted_at"):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Requisition is not deleted")

        await self.supabase.table("requisitions").update({"deleted_at": None}).eq("id", req_id).execute_async()
        await self.supabase.table("rounds").update({"deleted_at": None}).eq("requisition_id", req_id).execute_async()

        rounds_result = await self.supabase.table("rounds").select("id").eq("requisition_id", req_id).execute_async()
        round_ids = [r["id"] for r in (rounds_result.data or [])]

        if round_ids:
            await self.supabase.table("feedback_questions").update({"deleted_at": None}).in_("round_id", round_ids).execute_async()

        await self.supabase.table("candidates").update({"deleted_at": None}).eq("requisition_id", req_id).execute_async()
        return {"message": "Requisition restored successfully", "id": req_id}

    async def delete_rounds_cascade(self, req_id: str) -> None:
        existing_rounds = await self.supabase.table("rounds").select("id").eq("requisition_id", req_id).is_null("deleted_at").execute_async()
        if not existing_rounds.data:
            return

        now = datetime.now(timezone.utc).isoformat()
        rounds_list = existing_rounds.data if isinstance(existing_rounds.data, list) else [existing_rounds.data]
        round_ids = [r["id"] for r in rounds_list]

        await self.supabase.table("feedback_questions").update({"deleted_at": now}).in_("round_id", round_ids).execute_async()
        await self.supabase.table("rounds").update({"deleted_at": now}).in_("id", round_ids).execute_async()

    async def _persist_round_questions(self, round_id: str, feedback_questions) -> list[dict]:
        """Insert the feedback questions for a round (numbered 1..N) and return
        their built responses. Shared by create_interview_plan and
        update_interview_plan to keep the two paths byte-for-byte identical."""
        if not feedback_questions:
            return []

        questions_data = [
            {
                "round_id": round_id,
                "question_number": q_idx + 1,
                "heading": qi.heading,
                "description": qi.description,
            }
            for q_idx, qi in enumerate(feedback_questions)
        ]
        questions_result = await insert_many(self.supabase, "feedback_questions", questions_data).execute_async()
        if not questions_result.data:
            return []
        return [build_question_response(q_data) for q_data in questions_result.data]

    async def create_interview_plan(self, req_id: str, plan: InterviewPlanCreate, org_id: str | None = None) -> dict:
        req_q = self.supabase.table("requisitions").select("id, status").eq("id", req_id).is_null("deleted_at")
        if org_id:
            req_q = req_q.eq("organization_id", org_id)
        req_result = await req_q.single().execute_async()
        if not req_result.data:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Requisition not found")

        existing_rounds = await self.supabase.table("rounds").select("id").eq("requisition_id", req_id).is_null("deleted_at").execute_async()
        if existing_rounds.data:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Requisition already has an interview plan. Use PUT to update.")

        created_rounds = []
        total_duration = 0

        for idx, round_input in enumerate(plan.rounds):
            round_data = {
                "requisition_id": req_id,
                "round_number": idx + 1,
                "name": round_input.name,
                "category": round_input.category,
                "duration_minutes": round_input.duration_minutes,
                "description": round_input.description,
                "skills": round_input.skills,
                "guidelines": [{"title": g.title, "description": g.description} for g in round_input.guidelines],
                "round_type": "interview",
                "default_interviewer_emails": round_input.default_interviewer_emails or [],
            }

            round_result = await self.supabase.table("rounds").insert(round_data).execute_async()
            if not round_result.data:
                raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, f"Failed to create round: {round_input.name}")

            round_id = round_result.data["id"]
            total_duration += round_input.duration_minutes

            created_questions = await self._persist_round_questions(round_id, round_input.feedback_questions)

            rd = round_result.data[0] if isinstance(round_result.data, list) else round_result.data
            rr = build_round_response(rd)
            rr["feedback_questions"] = created_questions
            created_rounds.append(rr)

        return {
            "requisition_id": req_id,
            "total_rounds": len(created_rounds),
            "total_duration_minutes": total_duration,
            "total_duration_display": format_duration(total_duration),
            "rounds": created_rounds,
        }

    async def update_interview_plan(self, req_id: str, plan: InterviewPlanCreate, org_id: str | None = None) -> dict:
        req_q = self.supabase.table("requisitions").select("id").eq("id", req_id).is_null("deleted_at")
        if org_id:
            req_q = req_q.eq("organization_id", org_id)
        req_result = await req_q.single().execute_async()
        if not req_result.data:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Requisition not found")

        existing_rounds_result = await self.supabase.table("rounds").select("id, round_number, name").eq("requisition_id", req_id).is_null("deleted_at").execute_async()
        existing_rounds = existing_rounds_result.data or []
        existing_by_number = {r["round_number"]: r for r in existing_rounds}

        candidates_result = await self.supabase.table("candidates").select("id").eq("requisition_id", req_id).is_null("deleted_at").execute_async()
        candidates = candidates_result.data or []

        deleted_at = datetime.now(timezone.utc).isoformat()
        created_rounds = []
        total_duration = 0
        processed_round_numbers = set()

        for idx, round_input in enumerate(plan.rounds):
            new_round_number = idx + 1
            processed_round_numbers.add(new_round_number)

            if new_round_number in existing_by_number:
                existing_round = existing_by_number[new_round_number]
                round_id = existing_round["id"]

                round_update_data = {
                    "name": round_input.name,
                    "category": round_input.category,
                    "duration_minutes": round_input.duration_minutes,
                    "description": round_input.description,
                    "skills": round_input.skills,
                    "guidelines": [{"title": g.title, "description": g.description} for g in round_input.guidelines],
                    "round_type": round_input.round_type or "interview",
                    "assessment_template_id": str(round_input.assessment_template_id) if round_input.assessment_template_id else None,
                    "default_interviewer_emails": round_input.default_interviewer_emails or [],
                }
                await self.supabase.table("rounds").update(round_update_data).eq("id", round_id).execute_async()
                await self.supabase.table("feedback_questions").update({"deleted_at": deleted_at}).eq("round_id", round_id).execute_async()

                created_questions = await self._persist_round_questions(round_id, round_input.feedback_questions)

                round_result = await self.supabase.table("rounds").select("*").eq("id", round_id).single().execute_async()
                rr = build_round_response(round_result.data)
                rr["feedback_questions"] = created_questions
                created_rounds.append(rr)
                total_duration += round_input.duration_minutes
            else:
                round_data = {
                    "requisition_id": req_id,
                    "round_number": new_round_number,
                    "name": round_input.name,
                    "category": round_input.category,
                    "duration_minutes": round_input.duration_minutes,
                    "description": round_input.description,
                    "skills": round_input.skills,
                    "guidelines": [{"title": g.title, "description": g.description} for g in round_input.guidelines],
                    "round_type": round_input.round_type or "interview",
                    "assessment_template_id": str(round_input.assessment_template_id) if round_input.assessment_template_id else None,
                    "default_interviewer_emails": round_input.default_interviewer_emails or [],
                }

                round_result = await self.supabase.table("rounds").insert(round_data).execute_async()
                if not round_result.data:
                    raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, f"Failed to create round: {round_input.name}")

                new_round_data = round_result.data[0] if isinstance(round_result.data, list) else round_result.data
                round_id = new_round_data["id"]
                total_duration += round_input.duration_minutes

                created_questions = await self._persist_round_questions(round_id, round_input.feedback_questions)

                if candidates:
                    candidate_rounds_data = [
                        {"candidate_id": c["id"], "round_id": round_id, "status": "pending"}
                        for c in candidates
                    ]
                    await insert_many(self.supabase, "candidate_rounds", candidate_rounds_data).execute_async()

                rr = build_round_response(new_round_data)
                rr["feedback_questions"] = created_questions
                created_rounds.append(rr)

        rounds_to_delete = [r for r in existing_rounds if r["round_number"] not in processed_round_numbers]
        for old_round in rounds_to_delete:
            await self.supabase.table("feedback_questions").update({"deleted_at": deleted_at}).eq("round_id", old_round["id"]).execute_async()
            await self.supabase.table("rounds").update({"deleted_at": deleted_at}).eq("id", old_round["id"]).execute_async()

        return {
            "requisition_id": req_id,
            "total_rounds": len(created_rounds),
            "total_duration_minutes": total_duration,
            "total_duration_display": format_duration(total_duration),
            "rounds": created_rounds,
        }

    async def delete_interview_plan(self, req_id: str) -> dict:
        req_result = await self.supabase.table("requisitions").select("id").eq("id", req_id).is_null("deleted_at").single().execute_async()
        if not req_result.data:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Requisition not found")

        deleted_at = datetime.now(timezone.utc).isoformat()

        existing_rounds = await self.supabase.table("rounds").select("id").eq("requisition_id", req_id).is_null("deleted_at").execute_async()
        round_ids = [r["id"] for r in (existing_rounds.data or [])]

        delete_tasks = [
            self.supabase.table("feedback_questions").update({"deleted_at": deleted_at}).eq("round_id", rid).execute_async()
            for rid in round_ids
        ]
        if delete_tasks:
            await asyncio.gather(*delete_tasks)

        await asyncio.gather(
            self.supabase.table("rounds").update({"deleted_at": deleted_at}).eq("requisition_id", req_id).execute_async(),
            self.supabase.table("requisitions").update({"status": "intake_pending"}).eq("id", req_id).execute_async(),
        )
        return {"message": "Interview plan deleted successfully"}

    async def add_round(self, req_id: str, data: RoundCreate, org_id: str | None = None) -> dict:
        req_q = self.supabase.table("requisitions").select("id").eq("id", req_id).is_null("deleted_at")
        if org_id:
            req_q = req_q.eq("organization_id", org_id)

        req_result, existing_rounds = await asyncio.gather(
            req_q.single().execute_async(),
            self.supabase.table("rounds").select("round_number").eq("requisition_id", req_id).is_null("deleted_at").execute_async(),
        )

        if not req_result.data:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Requisition not found")

        max_round_number = max([r["round_number"] for r in (existing_rounds.data or [])], default=0)

        insert_data = {
            "requisition_id": req_id,
            "round_number": max_round_number + 1,
            "name": data.name,
            "category": data.category,
            "duration_minutes": data.duration_minutes,
            "description": data.description,
            "skills": data.skills,
            "round_type": data.round_type or "interview",
        }
        if data.assessment_template_id:
            insert_data["assessment_template_id"] = str(data.assessment_template_id)

        result = await self.supabase.table("rounds").insert(insert_data).execute_async()
        if not result.data:
            raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Failed to create round")

        new_round = result.data[0] if isinstance(result.data, list) else result.data
        new_round_id = new_round["id"]

        candidates_result = await self.supabase.table("candidates").select("id").eq("requisition_id", req_id).is_null("deleted_at").execute_async()
        candidates = candidates_result.data or []

        if candidates:
            candidate_rounds_data = [
                {"candidate_id": c["id"], "round_id": new_round_id, "status": "pending"}
                for c in candidates
            ]
            await insert_many(self.supabase, "candidate_rounds", candidate_rounds_data).execute_async()

        response = build_round_response(result.data)
        response["feedback_questions"] = []
        return response

    async def update_round(self, round_id: str, data: RoundUpdate) -> dict:
        existing = await self.supabase.table("rounds").select("id").eq("id", round_id).is_null("deleted_at").single().execute_async()
        if not existing.data:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Round not found")

        update_data = {}
        if data.name is not None:
            update_data["name"] = data.name
        if data.category is not None:
            update_data["category"] = data.category
        if data.duration_minutes is not None:
            update_data["duration_minutes"] = data.duration_minutes
        if data.description is not None:
            update_data["description"] = data.description
        if data.skills is not None:
            update_data["skills"] = data.skills
        if data.default_interviewer_emails is not None:
            update_data["default_interviewer_emails"] = data.default_interviewer_emails

        if not update_data:
            result = await self.supabase.table("rounds").select("*").eq("id", round_id).single().execute_async()
            return build_round_response(result.data)

        result = await self.supabase.table("rounds").update(update_data).eq("id", round_id).execute_async()
        if not result.data:
            raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Failed to update round")
        return build_round_response(result.data)

    async def delete_round(self, round_id: str) -> dict:
        existing = await self.supabase.table("rounds").select("id, deleted_at").eq("id", round_id).single().execute_async()
        if not existing.data:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Round not found")
        if existing.data.get("deleted_at"):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Round is already deleted")

        deleted_at = datetime.now(timezone.utc).isoformat()
        await asyncio.gather(
            self.supabase.table("feedback_questions").update({"deleted_at": deleted_at}).eq("round_id", round_id).execute_async(),
            self.supabase.table("rounds").update({"deleted_at": deleted_at}).eq("id", round_id).execute_async(),
        )
        return {"message": "Round deleted successfully", "id": round_id}

    async def restore_round(self, round_id: str) -> dict:
        existing = await self.supabase.table("rounds").select("id, deleted_at").eq("id", round_id).single().execute_async()
        if not existing.data:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Round not found")
        if not existing.data.get("deleted_at"):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Round is not deleted")

        await asyncio.gather(
            self.supabase.table("rounds").update({"deleted_at": None}).eq("id", round_id).execute_async(),
            self.supabase.table("feedback_questions").update({"deleted_at": None}).eq("round_id", round_id).execute_async(),
        )
        return {"message": "Round restored successfully", "id": round_id}

    async def reorder_rounds(self, req_id: str, reorder_data: RoundReorderRequest, org_id: str | None = None) -> dict:
        req_q = self.supabase.table("requisitions").select("id").eq("id", req_id).is_null("deleted_at")
        if org_id:
            req_q = req_q.eq("organization_id", org_id)
        req_result = await req_q.single().execute_async()
        if not req_result.data:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Requisition not found")

        existing_rounds = await self.supabase.table("rounds").select("id").eq("requisition_id", req_id).is_null("deleted_at").execute_async()
        existing_round_ids = {r["id"] for r in (existing_rounds.data or [])}

        for order_item in reorder_data.round_orders:
            if str(order_item.round_id) not in existing_round_ids:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Round {order_item.round_id} not found in this requisition")

        # Order the round ids by their requested round_number so the array
        # position maps to the final 1..N number. One atomic SECURITY DEFINER
        # RPC replaces the old non-transactional two-phase loop (migration 107)
        # so no negative interim round_number can be left committed on a crash.
        ordered_ids = [
            str(item.round_id)
            for item in sorted(reorder_data.round_orders, key=lambda o: o.round_number)
        ]
        result = await call_rpc(
            self.supabase,
            "reorder_requisition_rounds",
            {"p_requisition_id": req_id, "p_ordered_round_ids": ordered_ids},
        )
        return result or {"message": "Rounds reordered successfully"}

    async def add_question(self, round_id: str, data: FeedbackQuestionCreate) -> dict:
        round_result, existing_questions = await asyncio.gather(
            self.supabase.table("rounds").select("id").eq("id", round_id).is_null("deleted_at").single().execute_async(),
            self.supabase.table("feedback_questions").select("question_number").eq("round_id", round_id).is_null("deleted_at").execute_async(),
        )

        if not round_result.data:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Round not found")

        max_question_number = max([q["question_number"] for q in (existing_questions.data or [])], default=0)

        insert_data = {
            "round_id": round_id,
            "question_number": max_question_number + 1,
            "heading": data.heading,
            "description": data.description,
        }

        result = await self.supabase.table("feedback_questions").insert(insert_data).execute_async()
        if not result.data:
            raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Failed to create question")
        return build_question_response(result.data)

    async def update_question(self, question_id: str, data: FeedbackQuestionUpdate) -> dict:
        existing = await self.supabase.table("feedback_questions").select("id").eq("id", question_id).is_null("deleted_at").single().execute_async()
        if not existing.data:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Question not found")

        update_data = {}
        if data.heading is not None:
            update_data["heading"] = data.heading
        if data.description is not None:
            update_data["description"] = data.description

        if not update_data:
            result = await self.supabase.table("feedback_questions").select("*").eq("id", question_id).single().execute_async()
            return build_question_response(result.data)

        result = await self.supabase.table("feedback_questions").update(update_data).eq("id", question_id).execute_async()
        if not result.data:
            raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Failed to update question")
        return build_question_response(result.data)

    async def delete_question(self, question_id: str) -> dict:
        existing = await self.supabase.table("feedback_questions").select("id, deleted_at").eq("id", question_id).single().execute_async()
        if not existing.data:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Question not found")
        if existing.data.get("deleted_at"):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Question is already deleted")

        deleted_at = datetime.now(timezone.utc).isoformat()
        await self.supabase.table("feedback_questions").update({"deleted_at": deleted_at}).eq("id", question_id).execute_async()
        return {"message": "Question deleted successfully", "id": question_id}

    async def restore_question(self, question_id: str) -> dict:
        existing = await self.supabase.table("feedback_questions").select("id, deleted_at").eq("id", question_id).single().execute_async()
        if not existing.data:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Question not found")
        if not existing.data.get("deleted_at"):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Question is not deleted")

        await self.supabase.table("feedback_questions").update({"deleted_at": None}).eq("id", question_id).execute_async()
        return {"message": "Question restored successfully", "id": question_id}


def get_requisition_service() -> RequisitionService:
    return RequisitionService(get_supabase_admin_client())
