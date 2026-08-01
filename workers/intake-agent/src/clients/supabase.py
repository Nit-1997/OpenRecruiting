import json
import uuid as _uuid
from datetime import datetime, timezone
from typing import Any

import httpx

from src.config import get_settings
from src.logging import get_logger

logger = get_logger(__name__)

_async_client: httpx.AsyncClient | None = None


def get_async_http_client() -> httpx.AsyncClient:
    global _async_client
    if _async_client is None or _async_client.is_closed:
        _async_client = httpx.AsyncClient(
            timeout=httpx.Timeout(30.0, connect=10.0),
            limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
        )
    return _async_client


class SupabaseClient:
    def __init__(self):
        settings = get_settings()
        self.url = settings.supabase_url
        self.headers = {
            "apikey": settings.supabase_secret_key,
            "Authorization": f"Bearer {settings.supabase_secret_key}",
            "Content-Type": "application/json",
        }

    async def get_session_context(self, session_id: str) -> dict[str, Any]:
        """Load the v2 session row + a flattened role-context object compatible with
        the v1 IntakePipeline interface (so the rounds-design + round-details stages
        keep working without large rewrites).
        """
        client = get_async_http_client()
        resp = await client.get(
            f"{self.url}/rest/v1/intake_sessions",
            params={
                "id": f"eq.{session_id}",
                "select": "id,requisition_id,organization_id,user_id,form_data,"
                          "current_answers,turns,modalities_used,duration_min,"
                          "questions_version,questions_snapshot",
            },
            headers=self.headers,
        )
        data = resp.json()
        if not data:
            raise ValueError(f"Session {session_id} not found")
        sess = data[0]

        form_data = sess.get("form_data") or {}
        current = sess.get("current_answers") or {}

        return {
            "session_id": sess["id"],
            "requisition_id": sess["requisition_id"],
            "organization_id": sess["organization_id"],
            "role_title": form_data.get("role_name") or "Unknown",
            "role_location": form_data.get("location") or "Unknown",
            "experience_min_years": form_data.get("experience_min") or 0,
            "experience_max_years": form_data.get("experience_max"),
            "job_description": form_data.get("jd_text") or "",
            "intake_summary_struct": current,
            "turns": sess.get("turns") or [],
            "modalities_used": sess.get("modalities_used") or [],
            "duration_min": sess.get("duration_min"),
            "questions_version": sess.get("questions_version"),
            "questions_snapshot": sess.get("questions_snapshot") or [],
        }

    async def save_round_skeletons(self, requisition_id: str, round_skeletons: list[dict]) -> list[str]:
        """Insert rounds rows for this requisition. Returns round IDs in order."""
        client = get_async_http_client()
        # Idempotency: this worker is at-least-once (async Event invokes retry on
        # error; a failed-then-resubmitted session re-runs the whole pipeline).
        # Replace any rounds left by a prior partial run for this requisition
        # instead of appending a second full set (mirrors the backend publish()
        # delete-then-insert). raise_for_status so a failed delete can't silently
        # let the insert duplicate.
        del_resp = await client.request(
            "DELETE",
            f"{self.url}/rest/v1/rounds",
            params={"requisition_id": f"eq.{requisition_id}"},
            headers=self.headers,
        )
        del_resp.raise_for_status()
        round_ids: list[str] = []
        for idx, r in enumerate(round_skeletons):
            payload = {
                "requisition_id": requisition_id,
                "name": r["name"],
                "category": r.get("category"),
                "description": r.get("description"),
                "duration_minutes": r.get("duration_minutes", 45),
                "skills": r.get("skills", []),
                "round_number": idx + 1,
            }
            resp = await client.post(
                f"{self.url}/rest/v1/rounds",
                json=payload,
                headers={**self.headers, "Prefer": "return=representation"},
            )
            resp.raise_for_status()
            body = resp.json()
            # PostgREST with Prefer=return=representation returns a list of inserted
            # rows. Guard the shape explicitly: a dict/None body would make body[0]
            # raise KeyError(0) — which stringifies to a contextless "0" in
            # process_error. Fail with a descriptive error instead.
            if not isinstance(body, list) or not body or "id" not in body[0]:
                raise ValueError(
                    f"Failed to insert round {idx} ('{r.get('name')}'): "
                    f"unexpected insert response (type={type(body).__name__})"
                )
            round_ids.append(body[0]["id"])
        logger.info("rounds_inserted", requisition_id=requisition_id, count=len(round_ids))
        return round_ids

    async def save_round_details(self, round_id: str, details: dict) -> None:
        """Write guidelines + feedback_questions for one round."""
        client = get_async_http_client()

        await client.patch(
            f"{self.url}/rest/v1/rounds",
            params={"id": f"eq.{round_id}"},
            json={"guidelines": details.get("guidelines", [])},
            headers=self.headers,
        )

        questions = details.get("feedback_questions", [])
        for i, q in enumerate(questions):
            await client.post(
                f"{self.url}/rest/v1/feedback_questions",
                json={
                    "round_id": round_id,
                    "heading": q["heading"],
                    "description": q.get("description") or "",
                    "question_number": i + 1,
                },
                headers=self.headers,
            )
        logger.info("round_details_saved", round_id=round_id, question_count=len(questions))

    async def finalize_interview_plan(
        self,
        session_id: str,
        requisition_id: str,
        organization_id: str,
        interview_plan: dict,
    ) -> None:
        """Write the editable artifact to intake_sessions.interview_plan, set status,
        and publish the intake_v2_completed SQS event.
        """
        client = get_async_http_client()
        now = datetime.now(timezone.utc).isoformat()

        await client.patch(
            f"{self.url}/rest/v1/intake_sessions",
            params={"id": f"eq.{session_id}"},
            json={
                "interview_plan": interview_plan,
                "status": "submitted",
                "submitted_at": now,
                "process_status": "idle",
                "updated_at": now,
            },
            headers={**self.headers, "Prefer": "return=representation"},
        )
        logger.info("interview_plan_finalized", session_id=session_id, requisition_id=requisition_id)

        try:
            self._publish_sqs_event(
                "intake_v2_completed",
                {
                    "source_id": str(session_id),
                    "org_id": str(organization_id),
                    "last_touch_at": datetime.now(timezone.utc).isoformat(),
                    "event_pk": str(_uuid.uuid4()),
                    "requisition_id": str(requisition_id),
                },
            )
        except Exception as e:
            logger.warning("sqs_publish_failed", error=str(e))

    async def mark_session_failed(self, session_id: str, error: str) -> None:
        client = get_async_http_client()
        await client.patch(
            f"{self.url}/rest/v1/intake_sessions",
            params={"id": f"eq.{session_id}"},
            json={
                "status": "ready",
                "process_status": "failed",
                "process_error": (error or "")[:500],
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
            headers=self.headers,
        )

    def _publish_sqs_event(self, event_type: str, data: dict) -> None:
        settings = get_settings()
        queue_url = settings.sqs_queue_url
        if not queue_url:
            return
        import boto3
        sqs = boto3.client("sqs", region_name=settings.sqs_region or "us-west-1")
        sqs.send_message(
            QueueUrl=queue_url,
            MessageBody=json.dumps({"event_type": event_type, **data}),
            MessageGroupId=data.get("org_id", "default"),
        )
        logger.info("sqs_event_published", event_type=event_type)


async def close_async_http_client() -> None:
    """Per CLAUDE.md Lambda mandatory rules — must be called from the entry
    coroutine's finally block to avoid binding the httpx client to a dead loop on
    warm-container reuse.
    """
    global _async_client
    if _async_client is not None:
        try:
            await _async_client.aclose()
        except Exception as close_err:
            logger.warning("async_client_close_failed", error=str(close_err))
        _async_client = None
