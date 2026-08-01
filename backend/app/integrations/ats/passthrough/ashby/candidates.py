"""Ashby native CandidatesPort — résumé via candidate.info → file.info, plus
application.info for status/stage. Knit unified returns attachments:[] for Ashby."""

from app.integrations.ats.core.errors import AtsNotSupportedError
from app.integrations.ats.core.models import (
    AtsApplication, AtsCandidate, CandidateSearchCriteria, Page,
)
from app.integrations.ats.passthrough.ashby.mapping import application_from_infos
from app.integrations.ats.unified_knit.transport import KnitTransport


class AshbyCandidatesAdapter:
    def __init__(self, transport: KnitTransport, integration_id: str) -> None:
        self._t = transport
        self._iid = integration_id

    async def get_application(self, application_id: str, candidate_id: str) -> AtsApplication:
        cand = await self._t.passthrough(self._iid, "POST", "/candidate.info", {"id": candidate_id})
        cand_results = (cand or {}).get("results") or {}

        resume_url = resume_name = None
        rfh = cand_results.get("resumeFileHandle") or {}
        handle = rfh.get("handle")
        if handle:
            fi = await self._t.passthrough(self._iid, "POST", "/file.info", {"fileHandle": handle})
            resume_url = ((fi or {}).get("results") or {}).get("url")
            resume_name = rfh.get("name")

        app = await self._t.passthrough(
            self._iid, "POST", "/application.info", {"applicationId": application_id}
        )
        app_results = (app or {}).get("results") or {}

        return application_from_infos(
            application_id, cand_results, app_results,
            resume_url=resume_url, resume_name=resume_name,
        )

    async def search_candidates(self, criteria: CandidateSearchCriteria) -> list[AtsCandidate]:
        raise AtsNotSupportedError("ashby native search_candidates not implemented in SS1")

    async def list_applications(self, page_token: str | None = None) -> Page[AtsApplication]:
        raise AtsNotSupportedError("ashby native list_applications not implemented in SS1")
