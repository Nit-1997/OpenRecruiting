"""Workable native CandidatesPort — résumé via /candidates/{id}.resume_url (direct)."""

from app.integrations.ats.core.errors import AtsNotSupportedError
from app.integrations.ats.core.models import (
    AtsApplication, AtsCandidate, CandidateSearchCriteria, Page,
)
from app.integrations.ats.passthrough.workable.mapping import candidate_to_application
from app.integrations.ats.unified_knit.transport import KnitTransport


class WorkableCandidatesAdapter:
    def __init__(self, transport: KnitTransport, integration_id: str) -> None:
        self._t = transport
        self._iid = integration_id

    async def get_application(self, application_id: str, candidate_id: str) -> AtsApplication:
        resp = await self._t.passthrough(self._iid, "GET", f"/candidates/{candidate_id}")
        c = (resp or {}).get("candidate") or resp or {}
        return candidate_to_application(application_id, c)

    async def search_candidates(self, criteria: CandidateSearchCriteria) -> list[AtsCandidate]:
        raise AtsNotSupportedError("workable native search_candidates not implemented in SS1b")

    async def list_applications(self, page_token: str | None = None) -> Page[AtsApplication]:
        raise AtsNotSupportedError("workable native list_applications not implemented in SS1b")
