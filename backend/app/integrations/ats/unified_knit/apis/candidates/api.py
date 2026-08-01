"""Knit implementation of CandidatesPort. Knit search is structured-only
(no free-text); list-applications has no job filter (verified 2026-06-11)."""

from app.integrations.ats.core.models import (
    AtsApplication,
    AtsCandidate,
    CandidateSearchCriteria,
    Page,
)
from app.integrations.ats.unified_knit.apis.candidates.mapping import (
    to_ats_application,
    to_ats_candidate,
)
from app.integrations.ats.unified_knit.apis.candidates.wire_models import (
    KnitApplication,
    KnitCandidate,
    KnitListApplicationsData,
)
from app.integrations.ats.unified_knit.transport import KnitTransport


class KnitCandidatesApi:
    def __init__(self, transport: KnitTransport, integration_id: str) -> None:
        self._transport = transport
        self._integration_id = integration_id

    async def search_candidates(
        self, criteria: CandidateSearchCriteria
    ) -> list[AtsCandidate]:
        payload: dict = {}
        if criteria.first_name:
            payload["firstName"] = criteria.first_name
        if criteria.last_name:
            payload["lastName"] = criteria.last_name
        if criteria.email:
            payload["emails"] = [criteria.email]
        if criteria.phone:
            payload["phones"] = [criteria.phone]
        body = await self._transport.request(
            "POST",
            "/ats.candidates.search",
            integration_id=self._integration_id,
            json=payload,
        )
        candidates = (body.get("data") or {}).get("candidates") or []
        return [
            to_ats_candidate(KnitCandidate.model_validate(c)) for c in candidates
        ]

    async def list_applications(
        self, page_token: str | None = None
    ) -> Page[AtsApplication]:
        params = {"pageToken": page_token} if page_token else None
        body = await self._transport.request(
            "GET",
            "/ats.application.list",
            integration_id=self._integration_id,
            params=params,
        )
        data = KnitListApplicationsData.model_validate(body.get("data") or {})
        return Page[AtsApplication](
            items=[to_ats_application(a) for a in data.applications],
            next_page_token=data.next_page_token,
        )

    async def get_application(
        self, application_id: str, candidate_id: str
    ) -> AtsApplication:
        body = await self._transport.request(
            "GET",
            "/ats.application.get",
            integration_id=self._integration_id,
            params={"applicationId": application_id, "candidateId": candidate_id},
        )
        wire = KnitApplication.model_validate(
            ((body.get("data") or {}).get("application")) or {}
        )
        return to_ats_application(wire)
