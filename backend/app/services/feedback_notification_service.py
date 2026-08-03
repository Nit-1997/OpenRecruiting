from datetime import datetime, timezone, timedelta
from functools import lru_cache
from typing import Optional

from app.config import get_settings
from app.logging_config import get_logger
from app.services.supabase import get_supabase_admin_client
from app.services.email.service import get_email_service
from app.services.otp_service import get_otp_service

logger = get_logger(__name__)


class FeedbackNotificationService:
    def __init__(self):
        self._email_service = None
        self._otp_service = None
        self._settings = None

    @property
    def email_service(self):
        if self._email_service is None:
            self._email_service = get_email_service()
        return self._email_service

    @property
    def otp_service(self):
        if self._otp_service is None:
            self._otp_service = get_otp_service()
        return self._otp_service

    @property
    def settings(self):
        if self._settings is None:
            self._settings = get_settings()
        return self._settings

    async def send_happy_path_emails(self, candidate_round_id: str) -> dict:
        """
        Send feedback-ready emails after successful feedback processing.
        HAPPY-02: Update scorecard_status to 'complete'
        HAPPY-03: Notify scheduler
        HAPPY-04: Notify interviewer
        """
        result = {
            "candidate_round_id": candidate_round_id,
            "scheduler": None,
            "interviewer": None,
        }

        cr_context = await self._get_candidate_round_context(candidate_round_id)
        if not cr_context:
            logger.error(f"FeedbackNotificationService: Cannot find context for round {candidate_round_id}")
            return {"error": "candidate_round_not_found"}

        supabase = get_supabase_admin_client()
        await supabase.table("candidate_rounds").update({
            "scorecard_status": "complete",
            "processing_status": "completed",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", candidate_round_id).execute_async()
        logger.info(f"FeedbackNotificationService: Updated scorecard_status and processing_status to 'complete' for round {candidate_round_id}")

        scheduler = await self.email_service.get_scheduler_email(candidate_round_id)
        interviewer = await self.email_service.get_interviewer_email(candidate_round_id)
        has_interviewer_email = interviewer is not None

        if scheduler:
            scheduler_result = await self._send_feedback_ready_to_scheduler(
                scheduler, cr_context, has_interviewer_email
            )
            result["scheduler"] = scheduler_result

        if interviewer:
            interviewer_result = await self._send_feedback_ready_to_interviewer(
                interviewer, cr_context, candidate_round_id
            )
            result["interviewer"] = interviewer_result

        return result

    async def _get_candidate_round_context(self, candidate_round_id: str) -> Optional[dict]:
        """Get context needed for email rendering."""
        supabase = get_supabase_admin_client()

        cr_result = await supabase.table("candidate_rounds")\
            .select("id, round_id, interviewer_email, candidates!inner(id, name, requisition_id)")\
            .eq("id", candidate_round_id)\
            .single()\
            .execute_async()

        if not cr_result.data:
            return None

        candidate_data = cr_result.data.get("candidates")
        if not candidate_data:
            return None

        requisition_id = candidate_data.get("requisition_id")

        req_result = await supabase.table("requisitions")\
            .select("id, role_title")\
            .eq("id", requisition_id)\
            .single()\
            .execute_async()

        round_name = "interview"
        if req_result.data:
            round_name = req_result.data.get("role_title") or "interview"

        return {
            "candidate_round_id": candidate_round_id,
            "round_id": cr_result.data.get("round_id"),
            "candidate_id": candidate_data.get("id"),
            "candidate_name": candidate_data.get("name") or "the candidate",
            "round_name": round_name,
            "interviewer_email": cr_result.data.get("interviewer_email"),
            "requisition_id": requisition_id,
        }

    def _build_base_email_context(self, cr_context: dict) -> dict:
        return {
            "candidate_name": cr_context.get("candidate_name", "the candidate"),
            "round_name": cr_context.get("round_name", "interview"),
        }

    async def _send_feedback_ready_to_scheduler(
        self,
        scheduler: tuple,
        cr_context: dict,
        has_interviewer_email: bool
    ) -> dict:
        """Send feedback-ready notification to scheduler."""
        scheduler_email, scheduler_name = scheduler
        candidate_id = cr_context.get("candidate_id")
        candidate_name = cr_context.get("candidate_name", "the candidate")
        candidate_round_id = cr_context.get("candidate_round_id")

        requisition_id = cr_context.get("requisition_id")
        view_link = f"{self.settings.APP_URL}/view/roles/{requisition_id}?candidate={candidate_id}"

        context = self._build_base_email_context(cr_context)
        context.update({
            "scheduler_name": scheduler_name or "there",
            "has_interviewer_email": has_interviewer_email,
            "candidate_link": view_link,
        })

        subject = f"Feedback ready: {candidate_name}"

        result = await self.email_service.send_templated_email(
            to_email=scheduler_email,
            to_name=scheduler_name,
            subject=subject,
            template_name="feedback_ready_recruiter.html",
            context=context,
        )

        logger.info(f"FeedbackNotificationService: Sent feedback-ready email to scheduler {scheduler_email}")
        return {"email": scheduler_email, "sent": result.success, "message_id": result.message_id}

    async def _send_feedback_ready_to_interviewer(
        self,
        interviewer: tuple,
        cr_context: dict,
        candidate_round_id: str
    ) -> dict:
        """Send feedback notification to interviewer - goes to review page since feedback is processed."""
        interviewer_email, interviewer_name = interviewer
        candidate_name = cr_context.get("candidate_name", "the candidate")

        is_registered_user = await self.otp_service.is_interviewer_registered(interviewer_email)

        context = self._build_base_email_context(cr_context)
        context.update({
            "interviewer_name": interviewer_name or "there",
        })

        token = await self._ensure_feedback_token(candidate_round_id, interviewer_email, is_registered_user=is_registered_user)

        if is_registered_user:
            feedback_link = f"{self.settings.APP_URL}/feedback/{token}/verify?platform_auth=pending&redirect=feedback"
            context["feedback_link"] = feedback_link
            context["is_registered_user"] = True
        else:
            otp_code = self.otp_service.generate_otp()
            await self._store_otp_for_token(candidate_round_id, otp_code)

            feedback_link = f"{self.settings.APP_URL}/feedback/{token}/verify?otp={otp_code}&redirect=feedback"
            context["feedback_link"] = feedback_link
            context["otp_code"] = otp_code
            context["otp_validity"] = "12 hours"
            context["is_registered_user"] = False

        subject = f"Interview Feedback Report: {candidate_name}"

        result = await self.email_service.send_templated_email(
            to_email=interviewer_email,
            to_name=interviewer_name,
            subject=subject,
            template_name="feedback_ready_interviewer.html",
            context=context,
        )

        logger.info(f"FeedbackNotificationService: Sent feedback email to interviewer {interviewer_email} (openrecruiting_user={is_registered_user})")
        return {
            "email": interviewer_email,
            "sent": result.success,
            "message_id": result.message_id,
            "is_registered_user": is_registered_user,
        }

    async def send_capture_request_to_interviewer(
        self,
        interviewer: tuple,
        cr_context: dict,
        candidate_round_id: str
    ) -> dict:
        """Send feedback capture request to interviewer (link to record/edit voice feedback)."""
        interviewer_email, interviewer_name = interviewer
        candidate_name = cr_context.get("candidate_name", "the candidate")

        is_registered_user = await self.otp_service.is_interviewer_registered(interviewer_email)

        context = self._build_base_email_context(cr_context)
        context.update({
            "interviewer_name": interviewer_name or "there",
        })

        token = await self._ensure_feedback_token(candidate_round_id, interviewer_email, is_registered_user=is_registered_user)

        if is_registered_user:
            feedback_link = f"{self.settings.APP_URL}/feedback/{token}/verify?platform_auth=pending&redirect=feedback"
            context["feedback_link"] = feedback_link
            context["is_registered_user"] = True
        else:
            otp_code = self.otp_service.generate_otp()
            await self._store_otp_for_token(candidate_round_id, otp_code)

            feedback_link = f"{self.settings.APP_URL}/feedback/{token}/verify?otp={otp_code}&redirect=feedback"
            context["feedback_link"] = feedback_link
            context["otp_code"] = otp_code
            context["otp_validity"] = "12 hours"
            context["is_registered_user"] = False

        subject = f" Feedback for {candidate_name} is pending"

        result = await self.email_service.send_templated_email(
            to_email=interviewer_email,
            to_name=interviewer_name,
            subject=subject,
            template_name="feedback_reminder_interviewer.html",
            context=context,
        )

        logger.info(f"FeedbackNotificationService: Sent capture request to interviewer {interviewer_email} (openrecruiting_user={is_registered_user})")
        return {
            "email": interviewer_email,
            "sent": result.success,
            "message_id": result.message_id,
            "is_registered_user": is_registered_user,
        }

    async def _ensure_feedback_token(self, candidate_round_id: str, interviewer_email: Optional[str] = None, is_registered_user: Optional[bool] = None) -> str:
        """Ensure a feedback access token exists, creating one if needed. Updates email and is_registered_user if changed."""
        supabase = get_supabase_admin_client()

        existing = await supabase.table("feedback_access_tokens")\
            .select("token, interviewer_email, is_registered_user")\
            .eq("candidate_round_id", candidate_round_id)\
            .execute_async()

        if existing.data and len(existing.data) > 0:
            existing_token = existing.data[0]
            token = existing_token.get("token")
            current_email = existing_token.get("interviewer_email")
            current_is_registered = existing_token.get("is_registered_user")

            update_data = {}

            if interviewer_email and interviewer_email != current_email:
                update_data.update({
                    "interviewer_email": interviewer_email,
                    "otp_code": None,
                    "otp_expires_at": None,
                    "otp_attempts": 0,
                    "otp_success_count": 0,
                    "otp_locked_until": None,
                    "is_registered_user": is_registered_user,
                })
                logger.info(f"FeedbackNotificationService: Updated feedback token email from {current_email} to {interviewer_email}")
            elif is_registered_user is not None and is_registered_user != current_is_registered:
                update_data["is_registered_user"] = is_registered_user

            if update_data:
                update_data["updated_at"] = datetime.now(timezone.utc).isoformat()
                await supabase.table("feedback_access_tokens").update(update_data)\
                    .eq("candidate_round_id", candidate_round_id).execute_async()

            return token

        token = self.otp_service.generate_feedback_token()
        email = interviewer_email or "unknown@example.com"

        await supabase.table("feedback_access_tokens").insert({
            "token": token,
            "candidate_round_id": candidate_round_id,
            "interviewer_email": email,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }).execute_async()

        logger.info(f"FeedbackNotificationService: Created feedback token for round {candidate_round_id}")
        return token

    async def _store_otp_for_token(self, candidate_round_id: str, otp_code: str) -> None:
        """Store OTP in the feedback_access_tokens table."""
        supabase = get_supabase_admin_client()
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(minutes=self.otp_service.OTP_VALIDITY_MINUTES)

        await supabase.table("feedback_access_tokens").update({
            "otp_code": otp_code,
            "otp_expires_at": expires_at.isoformat(),
            "otp_attempts": 0,
            "otp_success_count": 0,
            "otp_locked_until": None,
            "updated_at": now.isoformat(),
        }).eq("candidate_round_id", candidate_round_id).execute_async()

        logger.debug(f"FeedbackNotificationService: Stored OTP for round {candidate_round_id}")

    async def send_optional_feedback_enhancement_email(self, candidate_round_id: str) -> dict:
        """
        Send OPTIONAL enhancement email when feedback wasn't captured during interview.
        Feedback will be generated from transcript - this allows the interviewer to enrich it.
        """
        result = {"candidate_round_id": candidate_round_id, "interviewer": None}

        cr_context = await self._get_candidate_round_context(candidate_round_id)
        if not cr_context:
            logger.warning(f"FeedbackNotificationService: Cannot find context for enhancement email: {candidate_round_id}")
            return {"error": "candidate_round_not_found"}

        interviewer = await self.email_service.get_interviewer_email(candidate_round_id)
        if not interviewer:
            logger.info(f"FeedbackNotificationService: No interviewer email for optional enhancement: {candidate_round_id}")
            return {"skipped": "no_interviewer_email"}

        interviewer_email, interviewer_name = interviewer
        candidate_name = cr_context.get("candidate_name", "the candidate")

        is_registered_user = await self.otp_service.is_interviewer_registered(interviewer_email)
        token = await self._ensure_feedback_token(candidate_round_id, interviewer_email, is_registered_user=is_registered_user)

        context = self._build_base_email_context(cr_context)
        context.update({
            "interviewer_name": interviewer_name or "there",
            "is_optional": True,
        })

        if is_registered_user:
            feedback_link = f"{self.settings.APP_URL}/feedback/{token}/verify?platform_auth=pending&redirect=feedback"
            context["feedback_link"] = feedback_link
            context["is_registered_user"] = True
        else:
            otp_code = self.otp_service.generate_otp()
            await self._store_otp_for_token(candidate_round_id, otp_code)
            feedback_link = f"{self.settings.APP_URL}/feedback/{token}/verify?otp={otp_code}&redirect=feedback"
            context["feedback_link"] = feedback_link
            context["otp_code"] = otp_code
            context["otp_validity"] = "12 hours"
            context["is_registered_user"] = False

        subject = f"Optional: Enhance your feedback for {candidate_name}"

        email_result = await self.email_service.send_templated_email(
            to_email=interviewer_email,
            to_name=interviewer_name,
            subject=subject,
            template_name="feedback_enhancement_optional.html",
            context=context,
        )

        logger.info(f"FeedbackNotificationService: Sent optional enhancement email to {interviewer_email}")
        result["interviewer"] = {"email": interviewer_email, "sent": email_result.success, "is_registered_user": is_registered_user}
        return result

    async def send_interview_complete_emails(self, candidate_round_id: str) -> dict:
        """
        Send emails when interview is complete but no feedback was captured.
        - Interviewer: "Add your feedback" email with link to unified feedback page
        - Recruiter: "Interview complete, awaiting feedback" notification
        """
        result = {
            "candidate_round_id": candidate_round_id,
            "interviewer": None,
            "scheduler": None,
        }

        cr_context = await self._get_candidate_round_context(candidate_round_id)
        if not cr_context:
            logger.warning(f"FeedbackNotificationService: Cannot find context for interview complete emails: {candidate_round_id}")
            return {"error": "candidate_round_not_found"}

        candidate_name = cr_context.get("candidate_name", "the candidate")
        round_name = cr_context.get("round_name", "Interview")

        interviewer = await self.email_service.get_interviewer_email(candidate_round_id)
        if interviewer:
            interviewer_email, interviewer_name = interviewer
            is_registered_user = await self.otp_service.is_interviewer_registered(interviewer_email)
            token = await self._ensure_feedback_token(candidate_round_id, interviewer_email, is_registered_user=is_registered_user)

            context = self._build_base_email_context(cr_context)
            context.update({
                "interviewer_name": interviewer_name or "there",
            })

            if is_registered_user:
                feedback_link = f"{self.settings.APP_URL}/feedback/{token}/verify?platform_auth=pending&redirect=feedback"
                context["feedback_link"] = feedback_link
                context["is_registered_user"] = True
            else:
                otp_code = self.otp_service.generate_otp()
                await self._store_otp_for_token(candidate_round_id, otp_code)
                feedback_link = f"{self.settings.APP_URL}/feedback/{token}/verify?otp={otp_code}&redirect=feedback"
                context["feedback_link"] = feedback_link
                context["otp_code"] = otp_code
                context["otp_validity"] = "12 hours"
                context["is_registered_user"] = False

            subject = f"Feedback for {candidate_name} is pending"

            email_result = await self.email_service.send_templated_email(
                to_email=interviewer_email,
                to_name=interviewer_name,
                subject=subject,
                template_name="feedback_reminder_interviewer.html",
                context=context,
            )

            logger.info(f"FeedbackNotificationService: Sent feedback pending email to interviewer {interviewer_email}")
            result["interviewer"] = {"email": interviewer_email, "sent": email_result.success, "is_registered_user": is_registered_user}

        scheduler = await self.email_service.get_scheduler_email(candidate_round_id)
        if scheduler:
            scheduler_email, scheduler_name = scheduler

            context = self._build_base_email_context(cr_context)
            context.update({
                "scheduler_name": scheduler_name or "there",
                "has_interviewer": interviewer is not None,
            })

            subject = f"Interviewer feedback still pending: {candidate_name} - {round_name}"

            email_result = await self.email_service.send_templated_email(
                to_email=scheduler_email,
                to_name=scheduler_name,
                subject=subject,
                template_name="feedback_not_there_recruiter.html",
                context=context,
            )

            logger.info(f"FeedbackNotificationService: Sent feedback missing email to scheduler {scheduler_email}")
            result["scheduler"] = {"email": scheduler_email, "sent": email_result.success}

        return result

    async def send_fallback_emails(self, candidate_round_id: str) -> dict:
        """
        Send fallback emails when feedback was not captured automatically.
        FALL-01: Skip if feedback already complete
        FALL-02: Notify scheduler with shareable link
        FALL-03: Send reminder to interviewer
        """
        result = {
            "candidate_round_id": candidate_round_id,
            "scheduler": None,
            "interviewer": None,
        }

        supabase = get_supabase_admin_client()
        cr_check = await supabase.table("candidate_rounds")\
            .select("scorecard_status")\
            .eq("id", candidate_round_id)\
            .single()\
            .execute_async()

        if cr_check.data and cr_check.data.get("scorecard_status") == "complete":
            logger.info(f"FeedbackNotificationService: Skipping fallback for round {candidate_round_id} - feedback already complete")
            return {"skipped": "feedback_already_complete"}

        cr_context = await self._get_candidate_round_context(candidate_round_id)
        if not cr_context:
            logger.error(f"FeedbackNotificationService: Cannot find context for round {candidate_round_id}")
            return {"error": "candidate_round_not_found"}

        interviewer_email = cr_context.get("interviewer_email")
        token = await self._ensure_feedback_token(candidate_round_id, interviewer_email)
        shareable_link = f"{self.settings.APP_URL}/feedback/{token}/verify"

        scheduler = await self.email_service.get_scheduler_email(candidate_round_id)
        interviewer = await self.email_service.get_interviewer_email(candidate_round_id)
        has_interviewer_email = interviewer is not None

        if scheduler:
            scheduler_result = await self._send_feedback_missing_to_scheduler(
                scheduler, cr_context, shareable_link, has_interviewer_email
            )
            result["scheduler"] = scheduler_result

        if interviewer:
            interviewer_result = await self._send_reminder_to_interviewer(
                interviewer, cr_context, shareable_link
            )
            result["interviewer"] = interviewer_result

        return result

    async def _send_feedback_missing_to_scheduler(
        self,
        scheduler: tuple,
        cr_context: dict,
        shareable_link: str,
        has_interviewer_email: bool
    ) -> dict:
        """Send feedback-missing notification to scheduler."""
        scheduler_email, scheduler_name = scheduler
        candidate_name = cr_context.get("candidate_name", "the candidate")
        candidate_round_id = cr_context.get("candidate_round_id")

        requisition_id = cr_context.get("requisition_id")
        candidate_id = cr_context.get("candidate_id")
        candidate_link = f"{self.settings.APP_URL}/view/roles/{requisition_id}?candidate={candidate_id}"

        context = self._build_base_email_context(cr_context)
        context.update({
            "scheduler_name": scheduler_name or "there",
            "has_interviewer_email": has_interviewer_email,
            "shareable_link": shareable_link,
            "candidate_link": candidate_link,
        })

        subject = f"Feedback needed: {candidate_name}"

        result = await self.email_service.send_templated_email(
            to_email=scheduler_email,
            to_name=scheduler_name,
            subject=subject,
            template_name="feedback_missing_recruiter.html",
            context=context,
        )

        logger.info(f"FeedbackNotificationService: Sent feedback-missing email to scheduler {scheduler_email}")
        return {"email": scheduler_email, "sent": result.success, "message_id": result.message_id}

    async def _send_reminder_to_interviewer(
        self,
        interviewer: tuple,
        cr_context: dict,
        feedback_link: str
    ) -> dict:
        """Send reminder to interviewer to complete feedback."""
        interviewer_email, interviewer_name = interviewer
        candidate_round_id = cr_context.get("candidate_round_id")

        is_registered_user = await self.otp_service.is_interviewer_registered(interviewer_email)

        context = self._build_base_email_context(cr_context)
        context.update({
            "interviewer_name": interviewer_name or "there",
            "feedback_link": feedback_link,
        })

        if not is_registered_user:
            supabase = get_supabase_admin_client()
            otp_code = self.otp_service.generate_otp()
            now = datetime.now(timezone.utc)
            expires_at = now + timedelta(minutes=self.otp_service.OTP_VALIDITY_MINUTES)

            await supabase.table("feedback_access_tokens").update({
                "otp_code": otp_code,
                "otp_expires_at": expires_at.isoformat(),
                "otp_attempts": 0,
                "otp_success_count": 0,
                "otp_locked_until": None,
                "updated_at": now.isoformat(),
            }).eq("candidate_round_id", candidate_round_id).execute_async()

            feedback_link_with_otp = f"{feedback_link}?otp={otp_code}"
            context["feedback_link"] = feedback_link_with_otp
            context["otp_code"] = otp_code
            context["otp_validity"] = "12 hours"
            context["is_registered_user"] = False
        else:
            feedback_link_with_auth = f"{feedback_link}?platform_auth=pending"
            context["feedback_link"] = feedback_link_with_auth
            context["is_registered_user"] = True

        subject = "Reminder: Complete your interview feedback"

        result = await self.email_service.send_templated_email(
            to_email=interviewer_email,
            to_name=interviewer_name,
            subject=subject,
            template_name="feedback_reminder_interviewer.html",
            context=context,
        )

        logger.info(f"FeedbackNotificationService: Sent feedback reminder to interviewer {interviewer_email}")
        return {
            "email": interviewer_email,
            "sent": result.success,
            "message_id": result.message_id,
            "is_registered_user": is_registered_user,
        }


@lru_cache()
def get_feedback_notification_service() -> FeedbackNotificationService:
    return FeedbackNotificationService()
