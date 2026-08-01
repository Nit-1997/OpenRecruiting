"""Provider-agnostic candidates/applications port."""

from typing import Protocol

from app.integrations.ats.core.models import (
    AtsApplication,
    AtsCandidate,
    CandidateSearchCriteria,
    Page,
)


class CandidatesPort(Protocol):
    async def search_candidates(
        self, criteria: CandidateSearchCriteria
    ) -> list[AtsCandidate]: ...

    async def list_applications(
        self, page_token: str | None = None
    ) -> Page[AtsApplication]: ...

    async def get_application(
        self, application_id: str, candidate_id: str
    ) -> AtsApplication: ...
