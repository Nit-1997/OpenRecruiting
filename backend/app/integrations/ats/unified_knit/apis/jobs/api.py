"""Knit implementation of JobsPort.

Knit's unified ATS has NO single-job GET (verified 2026-06-11) — get_job is a
paged scan over ats.job.list, capped at _MAX_GET_JOB_PAGES. Native passthrough
providers override this with a real by-id fetch in phase 2+.
"""

from app.integrations.ats.core.errors import AtsResourceNotFoundError
from app.integrations.ats.core.models import AtsJob, AtsJobCreate, Page
from app.integrations.ats.unified_knit.apis.jobs.mapping import to_ats_job
from app.integrations.ats.unified_knit.apis.jobs.wire_models import KnitListJobsData
from app.integrations.ats.unified_knit.transport import KnitTransport

_MAX_GET_JOB_PAGES = 20


class KnitJobsApi:
    def __init__(self, transport: KnitTransport, integration_id: str) -> None:
        self._transport = transport
        self._integration_id = integration_id

    async def list_jobs(self, page_token: str | None = None) -> Page[AtsJob]:
        params = {"pageToken": page_token} if page_token else None
        body = await self._transport.request(
            "GET",
            "/ats.job.list",
            integration_id=self._integration_id,
            params=params,
        )
        data = KnitListJobsData.model_validate(body.get("data") or {})
        return Page[AtsJob](
            items=[to_ats_job(job) for job in (data.jobs or [])],
            next_page_token=data.next_page_token,
        )

    async def get_job(self, job_id: str) -> AtsJob:
        page_token: str | None = None
        for _ in range(_MAX_GET_JOB_PAGES):
            page = await self.list_jobs(page_token)
            for job in page.items:
                if job.id == job_id:
                    return job
            if not page.next_page_token:
                break
            page_token = page.next_page_token
        raise AtsResourceNotFoundError(f"job {job_id} not found in connected ATS")

    async def create_job(self, draft: AtsJobCreate) -> str:
        payload: dict = {"title": draft.title}
        if draft.description is not None:
            payload["description"] = draft.description
        if draft.status is not None:
            payload["status"] = draft.status
        body = await self._transport.request(
            "POST",
            "/ats.job.create",
            integration_id=self._integration_id,
            json=payload,
        )
        return str((body.get("data") or {}).get("jobId") or "")
