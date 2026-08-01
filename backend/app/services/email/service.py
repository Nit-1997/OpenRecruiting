import os
from functools import lru_cache
from typing import Optional

from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.logging_config import get_logger
from app.services.supabase import get_supabase_admin_client
from app.services.email.base import EmailProvider, EmailMessage, EmailResult
from app.services.email.zoho_provider import get_email_provider

logger = get_logger(__name__)


class EmailService:
    def __init__(self, provider: EmailProvider, template_env: Environment):
        self.provider = provider
        self.templates = template_env

    def render_template(self, template_name: str, context: dict) -> str:
        template = self.templates.get_template(template_name)
        return template.render(**context)

    async def send_email(self, message: EmailMessage) -> EmailResult:
        return await self.provider.send_email(message)

    async def send_templated_email(
        self,
        to_email: str,
        to_name: Optional[str],
        subject: str,
        template_name: str,
        context: dict,
        reply_to: Optional[str] = None,
    ) -> EmailResult:
        html_body = self.render_template(template_name, context)
        message = EmailMessage(
            to_email=to_email,
            to_name=to_name,
            subject=subject,
            html_body=html_body,
            reply_to=reply_to,
        )
        return await self.provider.send_email(message)

    async def get_scheduler_email(self, candidate_round_id: str) -> tuple[str, str] | None:
        """
        ROUTE-01: Get scheduler email from created_by_user_id
        ROUTE-04: Fallback to first org user if scheduler deleted/deactivated
        Returns (email, full_name) or None if no valid recipient found
        """
        supabase = get_supabase_admin_client()

        cr_result = await supabase.table("candidate_rounds")\
            .select("created_by_user_id, candidates!inner(requisition_id)")\
            .eq("id", candidate_round_id)\
            .single()\
            .execute_async()

        if not cr_result.data:
            logger.warning(f"EmailService: Candidate round not found: {candidate_round_id}")
            return None

        scheduler_id = cr_result.data.get("created_by_user_id")
        candidate_data = cr_result.data.get("candidates")
        if not candidate_data:
            logger.warning(f"EmailService: No candidate data for round: {candidate_round_id}")
            return None

        requisition_id = candidate_data.get("requisition_id")

        req_result = await supabase.table("requisitions")\
            .select("organization_id")\
            .eq("id", requisition_id)\
            .single()\
            .execute_async()

        if not req_result.data:
            logger.warning(f"EmailService: Requisition not found: {requisition_id}")
            return None

        org_id = req_result.data.get("organization_id")

        if scheduler_id:
            scheduler = await supabase.table("profiles")\
                .select("email, full_name, deleted_at")\
                .eq("id", scheduler_id)\
                .single()\
                .execute_async()

            if scheduler.data and not scheduler.data.get("deleted_at"):
                email = scheduler.data.get("email")
                name = scheduler.data.get("full_name") or ""
                logger.debug(f"EmailService: Found scheduler email for round {candidate_round_id}: {email}")
                return (email, name)
            else:
                logger.info(f"EmailService: Scheduler {scheduler_id} deleted/deactivated, falling back to org admin")

        fallback = await supabase.table("profiles")\
            .select("email, full_name")\
            .eq("organization_id", org_id)\
            .is_null("deleted_at")\
            .order("created_at", desc=False)\
            .execute_async()

        if fallback.data and len(fallback.data) > 0:
            first_user = fallback.data[0]
            email = first_user.get("email")
            name = first_user.get("full_name") or ""
            logger.info(f"EmailService: Using fallback org admin for round {candidate_round_id}: {email}")
            return (email, name)

        logger.error(f"EmailService: No valid recipient found for round {candidate_round_id}")
        return None

    async def get_interviewer_email(self, candidate_round_id: str) -> tuple[str, str] | None:
        """
        ROUTE-03: Get interviewer email only if provided during scheduling
        Returns (email, name) or None
        """
        supabase = get_supabase_admin_client()

        cr_result = await supabase.table("candidate_rounds")\
            .select("interviewer_email")\
            .eq("id", candidate_round_id)\
            .single()\
            .execute_async()

        if not cr_result.data:
            logger.warning(f"EmailService: Candidate round not found: {candidate_round_id}")
            return None

        email = cr_result.data.get("interviewer_email")
        if not email:
            logger.debug(f"EmailService: No interviewer email for round {candidate_round_id}")
            return None

        name = email.split("@")[0].replace(".", " ").replace("_", " ").title()
        logger.debug(f"EmailService: Found interviewer email for round {candidate_round_id}: {email}")
        return (email, name)


@lru_cache()
def get_email_service() -> EmailService:
    provider = get_email_provider()

    template_dir = os.path.join(os.path.dirname(__file__), "templates")
    template_env = Environment(
        loader=FileSystemLoader(template_dir),
        autoescape=select_autoescape(["html", "xml"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )

    return EmailService(provider=provider, template_env=template_env)
