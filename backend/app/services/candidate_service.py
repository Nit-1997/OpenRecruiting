import asyncio
from app.services.supabase import get_supabase_admin_client, insert_many
from app.logging_config import get_logger

logger = get_logger(__name__)


class CandidateService:
    def __init__(self):
        self.supabase = get_supabase_admin_client()

    async def add_candidate(
        self,
        requisition_id: str,
        org_id: str,
        name: str,
        email: str,
        phone: str | None = None,
        resume_url: str | None = None,
    ) -> dict:
        req_result, rounds_result = await asyncio.gather(
            self.supabase.table("requisitions").select("id, role_title, status").eq("id", requisition_id).eq("organization_id", org_id).is_null("deleted_at").single().execute_async(),
            self.supabase.table("rounds").select("id, name, round_number").eq("requisition_id", requisition_id).is_null("deleted_at").order("round_number").execute_async(),
        )

        if not req_result.data:
            raise ValueError("Requisition not found")

        rounds = rounds_result.data or []
        if not rounds:
            raise ValueError("Requisition has no interview plan yet. Complete an intake call and generate a plan first.")

        existing = await self.supabase.table("candidates").select("id").eq("requisition_id", requisition_id).eq("email", email).is_null("deleted_at").execute_async()
        if existing.data:
            raise ValueError(f"A candidate with email {email} already exists for this requisition")

        candidate_row = {
            "requisition_id": requisition_id,
            "name": name,
            "email": email,
            "phone": phone,
            "resume_url": resume_url,
            "status": "active",
        }
        result = await self.supabase.table("candidates").insert(candidate_row).execute_async()
        if not result.data:
            raise ValueError("Failed to create candidate")

        candidate = result.data if isinstance(result.data, dict) else result.data[0]
        candidate_id = candidate["id"]

        cr_rows = [
            {"candidate_id": candidate_id, "round_id": r["id"], "status": "pending"}
            for r in rounds
        ]
        cr_result = await insert_many(self.supabase, "candidate_rounds", cr_rows).execute_async()
        cr_list = cr_result.data if isinstance(cr_result.data, list) else [cr_result.data] if cr_result.data else []
        cr_by_round = {cr["round_id"]: cr for cr in cr_list}

        created_rounds = []
        for r in rounds:
            cr = cr_by_round.get(r["id"], {})
            created_rounds.append({
                "id": r["id"],
                "name": r.get("name", ""),
                "round_number": r.get("round_number"),
                "candidate_round_id": cr.get("id"),
            })

        return {
            "candidate": candidate,
            "rounds": created_rounds,
            "role_title": req_result.data.get("role_title", ""),
        }


def get_candidate_service() -> CandidateService:
    return CandidateService()
