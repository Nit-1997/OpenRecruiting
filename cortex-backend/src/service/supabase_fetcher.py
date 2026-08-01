import structlog
from supabase import AsyncClient, acreate_client

from src.config.settings import get_settings
from src.model.packets import (
    FeedbackPacket,
    PlanPacket,
    DecisionPacket,
    CandidateRoundData,
    RoundData,
    RequisitionData,
    CandidateData,
    FeedbackItemData,
    RoundWithCompetenciesData,
    EpisodicMetadata,
    IntakeMetadata,
)

logger = structlog.get_logger(__name__)


class SupabaseFetcher:
    def __init__(self):
        self._client: AsyncClient | None = None
        self._interviewer_name_cache: dict[str, str | None] = {}
        self._org_cache: dict[str, dict | None] = {}

    async def _get_client(self) -> AsyncClient:
        if self._client is None:
            settings = get_settings()
            self._client = await acreate_client(
                settings.supabase.url,
                settings.supabase.service_role_key,
            )
        return self._client

    async def resolve_interviewer_name(self, email: str) -> str | None:
        lower_email = email.lower()
        if lower_email in self._interviewer_name_cache:
            return self._interviewer_name_cache[lower_email]
        client = await self._get_client()
        try:
            resp = await client.table("profiles").select("full_name").eq("email", lower_email).maybe_single().execute()
            name = resp.data.get("full_name") if resp.data else None
        except Exception as e:
            logger.warning("interviewer_name_lookup_failed", email=lower_email, error=str(e))
            name = None
        self._interviewer_name_cache[lower_email] = name
        return name

    async def resolve_organization(self, organization_id: str) -> dict | None:
        if organization_id in self._org_cache:
            return self._org_cache[organization_id]
        client = await self._get_client()
        try:
            resp = await client.table("organizations").select("id, name, domain").eq("id", organization_id).maybe_single().execute()
            data = resp.data if resp.data else None
        except Exception as e:
            logger.warning("organization_lookup_failed", organization_id=organization_id, error=str(e))
            data = None
        self._org_cache[organization_id] = data
        return data

    async def fetch_feedback_packet(self, candidate_round_id: str) -> FeedbackPacket:
        client = await self._get_client()

        cr_resp = await client.table("candidate_rounds").select("*").eq("id", candidate_round_id).single().execute()
        cr = cr_resp.data

        round_resp = await client.table("rounds").select("*").eq("id", cr["round_id"]).single().execute()
        round_data = round_resp.data

        req_resp = await client.table("requisitions").select("*").eq("id", round_data["requisition_id"]).single().execute()
        req_data = req_resp.data

        cand_resp = await client.table("candidates").select("*").eq("id", cr["candidate_id"]).single().execute()
        cand_data = cand_resp.data

        feedback_resp = await client.table("candidate_feedback").select(
            "id, feedback_question_id, feedback_text, evidence, evidence_status, feedback_questions!inner(heading)"
        ).eq("candidate_round_id", candidate_round_id).execute()
        feedback_items = feedback_resp.data or []

        org_id = req_data["organization_id"]
        org_record = await self.resolve_organization(org_id)
        interviewer_email = cr.get("interviewer_email")
        interviewer_name = None
        if interviewer_email:
            interviewer_name = await self.resolve_interviewer_name(interviewer_email)

        return FeedbackPacket(
            candidate_round=CandidateRoundData(
                id=cr["id"],
                candidate_id=cr["candidate_id"],
                round_id=cr["round_id"],
                requisition_id=round_data["requisition_id"],
                rating=cr.get("rating"),
                interviewer_email=interviewer_email,
                interviewer_name=interviewer_name,
                organization_id=org_id,
            ),
            round=RoundData(
                id=round_data["id"],
                name=round_data["name"],
                requisition_id=round_data["requisition_id"],
                category=round_data.get("category"),
                duration_minutes=round_data.get("duration_minutes"),
                skills=round_data.get("skills") or [],
            ),
            requisition=RequisitionData(
                id=req_data["id"],
                role_title=req_data["role_title"],
                organization_id=org_id,
                organization_name=(org_record or {}).get("name"),
                organization_domain=(org_record or {}).get("domain"),
                status=req_data.get("status"),
                experience_min_years=req_data.get("experience_min_years"),
                experience_max_years=req_data.get("experience_max_years"),
                role_location=req_data.get("role_location"),
                must_have_skills=req_data.get("must_have_skills") or [],
                nice_to_have_skills=req_data.get("good_to_have_skills") or [],
            ),
            candidate=CandidateData(
                id=cand_data["id"],
                name=cand_data["name"],
                organization_id=org_id,
                status=cand_data.get("status"),
            ),
            feedback_items=[
                FeedbackItemData(
                    heading=item["feedback_questions"]["heading"],
                    question_id=item.get("feedback_question_id"),
                    feedback_text=item.get("feedback_text"),
                    evidence=item.get("evidence") or [],
                    evidence_status=item.get("evidence_status"),
                )
                for item in feedback_items
                if item.get("feedback_questions", {}).get("heading")
            ],
        )

    async def fetch_plan_packet(self, requisition_id: str) -> PlanPacket:
        client = await self._get_client()

        req_resp = await client.table("requisitions").select("*").eq("id", requisition_id).single().execute()
        req_data = req_resp.data

        rounds_resp = await client.table("rounds").select("*").eq("requisition_id", requisition_id).is_("deleted_at", "null").order("round_number").execute()
        rounds_raw = rounds_resp.data or []

        rounds = []
        for i, r in enumerate(rounds_raw):
            fq_resp = await client.table("feedback_questions").select("heading").eq("round_id", r["id"]).execute()
            headings = [fq["heading"] for fq in (fq_resp.data or []) if fq.get("heading")]

            rounds.append(RoundWithCompetenciesData(
                id=r["id"],
                name=r["name"],
                category=r.get("category"),
                duration_minutes=r.get("duration_minutes"),
                skills=r.get("skills") or [],
                competency_headings=headings,
                order=r.get("round_number", i),
            ))

        org_record = await self.resolve_organization(req_data["organization_id"])
        return PlanPacket(
            requisition=RequisitionData(
                id=req_data["id"],
                role_title=req_data["role_title"],
                organization_id=req_data["organization_id"],
                organization_name=(org_record or {}).get("name"),
                organization_domain=(org_record or {}).get("domain"),
                status=req_data.get("status"),
                experience_min_years=req_data.get("experience_min_years"),
                experience_max_years=req_data.get("experience_max_years"),
                role_location=req_data.get("role_location"),
                must_have_skills=req_data.get("must_have_skills") or [],
                nice_to_have_skills=req_data.get("good_to_have_skills") or [],
            ),
            rounds=rounds,
        )

    async def fetch_decision_packet(self, candidate_id: str, requisition_id: str | None = None) -> DecisionPacket:
        client = await self._get_client()

        cand_resp = await client.table("candidates").select("*").eq("id", candidate_id).single().execute()
        cand_data = cand_resp.data

        req_id = requisition_id or cand_data.get("requisition_id")
        req_resp = await client.table("requisitions").select("*").eq("id", req_id).single().execute()
        req_data = req_resp.data

        org_id = req_data["organization_id"]
        org_record = await self.resolve_organization(org_id)

        return DecisionPacket(
            candidate=CandidateData(
                id=cand_data["id"],
                name=cand_data["name"],
                organization_id=org_id,
                status=cand_data.get("status"),
            ),
            requisition=RequisitionData(
                id=req_data["id"],
                role_title=req_data["role_title"],
                organization_id=org_id,
                organization_name=(org_record or {}).get("name"),
                organization_domain=(org_record or {}).get("domain"),
                status=req_data.get("status"),
                experience_min_years=req_data.get("experience_min_years"),
                experience_max_years=req_data.get("experience_max_years"),
                role_location=req_data.get("role_location"),
                must_have_skills=req_data.get("must_have_skills") or [],
                nice_to_have_skills=req_data.get("good_to_have_skills") or [],
            ),
        )

    async def fetch_episodic_metadata(self, candidate_round_id: str) -> EpisodicMetadata:
        client = await self._get_client()
        cr_resp = await client.table("candidate_rounds").select("*").eq("id", candidate_round_id).single().execute()
        cr = cr_resp.data
        round_resp = await client.table("rounds").select("*").eq("id", cr["round_id"]).single().execute()
        round_data = round_resp.data
        req_resp = await client.table("requisitions").select("*").eq("id", round_data["requisition_id"]).single().execute()
        req_data = req_resp.data
        cand_resp = await client.table("candidates").select("*").eq("id", cr["candidate_id"]).single().execute()
        cand_data = cand_resp.data
        interviewer_email = cr.get("interviewer_email")
        interviewer_name = None
        if interviewer_email:
            interviewer_name = await self.resolve_interviewer_name(interviewer_email)
        return EpisodicMetadata(
            candidate_round_id=candidate_round_id,
            candidate_id=cr["candidate_id"],
            candidate_name=cand_data["name"],
            round_id=cr["round_id"],
            round_name=round_data["name"],
            round_category=round_data.get("category"),
            requisition_id=round_data["requisition_id"],
            role_title=req_data["role_title"],
            organization_id=req_data["organization_id"],
            interviewer_email=interviewer_email,
            interviewer_ref=interviewer_email,
            interviewer_name=interviewer_name,
        )

    async def fetch_intake_metadata(self, requisition_id: str) -> IntakeMetadata:
        client = await self._get_client()
        req_resp = await client.table("requisitions").select("*").eq("id", requisition_id).single().execute()
        req_data = req_resp.data
        return IntakeMetadata(
            requisition_id=req_data["id"],
            role_title=req_data["role_title"],
            organization_id=req_data["organization_id"],
        )

    async def fetch_interview_segments(self, candidate_round_id: str) -> list[dict]:
        client = await self._get_client()
        resp = await client.table("transcripts").select("segments").eq("candidate_round_id", candidate_round_id).single().execute()
        return resp.data.get("segments") or []

    async def fetch_intake_transcript(self, requisition_id: str) -> str:
        client = await self._get_client()
        resp = await client.table("requisitions").select("intake_transcript").eq("id", requisition_id).single().execute()
        return resp.data.get("intake_transcript") or ""

    async def fetch_question_summaries(self, candidate_round_id: str) -> dict:
        client = await self._get_client()
        resp = await client.table("candidate_rounds").select("question_summaries").eq("id", candidate_round_id).single().execute()
        return resp.data.get("question_summaries") or {}

    async def fetch_feedback_transcript(self, candidate_round_id: str) -> str:
        client = await self._get_client()
        resp = await client.table("transcripts").select("feedback_transcript").eq("candidate_round_id", candidate_round_id).maybe_single().execute()
        if not resp or not resp.data:
            return ""
        return resp.data.get("feedback_transcript") or ""

    async def fetch_job_description(self, requisition_id: str) -> str:
        client = await self._get_client()
        resp = await client.table("requisitions").select("job_description").eq("id", requisition_id).maybe_single().execute()
        if not resp or not resp.data:
            return ""
        return resp.data.get("job_description") or ""

    async def fetch_intake_v2_session(self, session_id: str) -> "IntakeV2Packet":
        """Load an intake_sessions row + derive rounds from interview_plan artifact."""
        from src.model.packets import IntakeV2Packet

        client = await self._get_client()
        resp = await client.table("intake_sessions").select(
            "id,requisition_id,organization_id,user_id,form_data,current_answers,"
            "turns,modalities_used,duration_min,questions_version,interview_plan"
        ).eq("id", session_id).execute()

        if not resp.data:
            raise ValueError(f"intake_sessions row {session_id} not found")
        row = resp.data[0] if isinstance(resp.data, list) else resp.data

        form_data = row.get("form_data") or {}
        plan = row.get("interview_plan") or {}
        rounds = plan.get("rounds") or []

        return IntakeV2Packet(
            session_id=row["id"],
            requisition_id=row["requisition_id"],
            organization_id=row["organization_id"],
            user_id=row.get("user_id"),
            role_title=form_data.get("role_name") or "Unknown",
            role_location=form_data.get("location"),
            experience_min_years=form_data.get("experience_min"),
            experience_max_years=form_data.get("experience_max"),
            form_data=form_data,
            current_answers=row.get("current_answers") or {},
            turns=row.get("turns") or [],
            modalities_used=row.get("modalities_used") or [],
            duration_min=row.get("duration_min"),
            questions_version=row.get("questions_version"),
            interview_plan=plan,
            rounds=rounds,
        )

    async def fetch_candidate_names(self, candidate_ids: list[str]) -> dict[str, str]:
        """Map candidate_id -> name for the given set (debrief scaffold §5).

        Returns only the candidates that exist; the caller fills placeholders for
        any missing id. Empty input short-circuits to avoid a no-op query.
        """
        if not candidate_ids:
            return {}
        client = await self._get_client()
        resp = await client.table("candidates").select("id, name").in_("id", candidate_ids).execute()
        return {row["id"]: row.get("name") for row in (resp.data or []) if row.get("id")}

    async def fetch_candidate_rounds_for_requisition(
        self, requisition_id: str, candidate_ids: list[str]
    ) -> list[dict]:
        """Completed candidate_rounds for a requisition + candidate set (debrief §5/§6.6).

        Filters to `processing_status='completed'` and joins `rounds` (embedded) for
        the round name/category and to scope by requisition. Each row carries
        rating/summary/interviewer for panel votes + a nested `rounds` object.
        """
        if not candidate_ids:
            return []
        client = await self._get_client()
        resp = (
            await client.table("candidate_rounds")
            .select(
                "id, candidate_id, round_id, rating, summary, interviewer_email, "
                "interviewer_name, processing_status, rounds!inner(name, category, requisition_id)"
            )
            .eq("rounds.requisition_id", requisition_id)
            .eq("processing_status", "completed")
            .in_("candidate_id", candidate_ids)
            .execute()
        )
        return resp.data or []

    async def fetch_assessment_scores(self, candidate_round_ids: list[str]) -> list[dict]:
        """assessment_evaluations rows (category_name + score 1..5) for the rounds.

        Returns raw rows {candidate_round_id, category_name, score}; the scaffold maps
        category_name -> dimension and folds duplicates. Empty input short-circuits.
        """
        if not candidate_round_ids:
            return []
        client = await self._get_client()
        resp = (
            await client.table("assessment_evaluations")
            .select("candidate_round_id, category_name, score")
            .in_("candidate_round_id", candidate_round_ids)
            .execute()
        )
        return resp.data or []

    async def fetch_evidence_status_by_dimension(
        self, candidate_round_ids: list[str]
    ) -> list[dict]:
        """candidate_feedback rows joined to feedback_questions.heading (the dimension).

        Returns {candidate_round_id, evidence_status, feedback_questions:{heading}};
        the scaffold maps heading -> dimension and derives per-round feedback presence
        from these rows. Empty input short-circuits.
        """
        if not candidate_round_ids:
            return []
        client = await self._get_client()
        resp = (
            await client.table("candidate_feedback")
            .select("candidate_round_id, evidence_status, feedback_questions!inner(heading)")
            .in_("candidate_round_id", candidate_round_ids)
            .execute()
        )
        return resp.data or []

    async def fetch_transcript_round_ids(self, candidate_round_ids: list[str]) -> list[str]:
        """candidate_round_ids that have a transcripts row (debrief source_stats §6.6)."""
        if not candidate_round_ids:
            return []
        client = await self._get_client()
        resp = (
            await client.table("transcripts")
            .select("candidate_round_id")
            .in_("candidate_round_id", candidate_round_ids)
            .execute()
        )
        return [row["candidate_round_id"] for row in (resp.data or []) if row.get("candidate_round_id")]

    async def close(self) -> None:
        self._client = None
