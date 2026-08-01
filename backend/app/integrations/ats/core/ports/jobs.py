"""Provider-agnostic jobs port. unified_knit implements it now; passthrough
providers (ashby/workable native) implement the same surface in phase 2+."""

from typing import Protocol

from app.integrations.ats.core.models import AtsJob, AtsJobCreate, Page


class JobsPort(Protocol):
    async def list_jobs(self, page_token: str | None = None) -> Page[AtsJob]: ...

    async def get_job(self, job_id: str) -> AtsJob: ...

    async def create_job(self, draft: AtsJobCreate) -> str:
        """Returns the provider's new job id. May raise AtsNotSupportedError."""
        ...
