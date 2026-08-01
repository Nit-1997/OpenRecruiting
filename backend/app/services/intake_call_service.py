import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from app.config import get_settings
from app.services.supabase import get_supabase_admin_client
from app.services.google_calendar_service import get_google_calendar_service
from app.logging_config import get_logger

logger = get_logger(__name__)


class IntakeCallService:
    async def start_intake_call(self, profile_id: str, org_id: str, requisition_id: str) -> dict:
        supabase = get_supabase_admin_client()
        settings = get_settings()

        logger.info(f"start_intake_call called with profile_id={profile_id}, org_id={org_id}, requisition_id={requisition_id}")

        try:
            uuid.UUID(requisition_id)
        except ValueError:
            raise ValueError(f"Invalid requisition_id format: {requisition_id}. Must be a valid UUID.")

        req_result = await supabase.table("requisitions") \
            .select("id, role_title") \
            .eq("id", requisition_id) \
            .eq("organization_id", org_id) \
            .is_null("deleted_at") \
            .execute_async()

        if not req_result.data:
            raise ValueError("Requisition not found")

        req_title = req_result.data[0].get("role_title", "Untitled")

        intake_call_url = f"{settings.APP_URL}/intake?requisition_id={requisition_id}"

        gcal_service = get_google_calendar_service()
        connection = await gcal_service.get_connection(profile_id)
        if not connection:
            raise ValueError("Google Calendar not connected")

        now = datetime.now(timezone.utc)
        start = now.isoformat()
        end = (now + timedelta(minutes=30)).isoformat()

        event = await gcal_service.create_calendar_event(
            profile_id=profile_id,
            title=f"OpenRecruiting Intake Call — {req_title}",
            start=start,
            end=end,
            description=f"Start your intake call here: {intake_call_url}",
            location=intake_call_url,
        )

        return {
            "intake_call_url": intake_call_url,
            "calendar_event_link": event["html_link"],
        }


def get_intake_call_service() -> IntakeCallService:
    return IntakeCallService()
